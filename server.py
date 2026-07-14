"""
Agent Harness - FastAPI Backend + SSE streaming
"""
import asyncio
import json
import os
import posixpath
import re
import sqlite3
import time as _time
from contextlib import asynccontextmanager
from dataclasses import asdict
from urllib.parse import unquote
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from typing import Optional
from pydantic import BaseModel
from harness import AgentHarness, HarnessRun
from config import WORKSPACE_ROOT
from agents import get_finops_db_path

# File lưu trữ lịch sử
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_history.json")

# In-memory store cho run history
run_history: list[dict] = []
_history_lock = asyncio.Lock()


async def load_history():
    global run_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("run_history.json must be a list of objects")
            async with _history_lock:
                run_history.clear()
                run_history.extend(data)
            print(f"[Harness] Loaded {len(run_history)} history entries from run_history.json")
        except Exception as e:
            print(f"[Harness] Error loading history: {e}")
            async with _history_lock:
                run_history.clear()


async def save_history(snapshot: list[dict] | None = None):
    if snapshot is None:
        async with _history_lock:
            snapshot = list(run_history)
    tmp = HISTORY_FILE + ".tmp"
    try:
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        print(f"[Harness] Error saving history: {e}")
        try:
            os.remove(tmp)
        except Exception:
            pass


# ── Swarm Session TTL ──────────────────────────────────────────────────────────
SWARM_SESSION_TTL_SECONDS = 3600  # 1 hour idle TTL for pending sessions
SWARM_LOCK_STALE_SECONDS = 120


def _active_workspace() -> str:
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = ""
    workspace = workspace or (os.getenv("WORKSPACE_ROOT") or "").strip() or WORKSPACE_ROOT
    return os.path.abspath(workspace)


def _wiki_root() -> str:
    return os.path.join(_active_workspace(), "llmwiki", "wiki")


def init_db():
    """Idempotent DB initializer — safe to call multiple times (lifespan + test fixtures)."""
    try:
        conn = sqlite3.connect(get_finops_db_path())
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS swarm_sessions (
            swarm_id    TEXT PRIMARY KEY,
            state       TEXT,
            error_log   TEXT,
            target_files TEXT,
            reproducer_code TEXT,
            suggested_patch TEXT,
            logs        TEXT,
            final_result TEXT,
            expires_at  REAL,
            updated_at  REAL DEFAULT (strftime('%s','now'))
        )
        """)
        existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(swarm_sessions)").fetchall()}
        for name, ddl in {"expires_at": "REAL", "updated_at": "REAL"}.items():
            if name not in existing_cols:
                cursor.execute(f"ALTER TABLE swarm_sessions ADD COLUMN {name} {ddl}")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Harness Server] Error initializing swarm_sessions table: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_history()
    init_db()
    yield


app = FastAPI(title="Agent Harness API", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "HARNESS_CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    expected_key = os.getenv("HARNESS_API_KEY", "")
    raw_path = request.scope.get("raw_path", b"")
    raw_lower = raw_path.lower()
    decoded_path = unquote(raw_path.decode("ascii", errors="ignore") or request.url.path)
    if request.url.path.startswith("/api") and (
        b"%2f" in raw_lower or b"%5c" in raw_lower or b"\\" in raw_path
        or any(part in {".", ".."} for part in decoded_path.split("/"))
        or any(part in {".", ".."} for part in request.url.path.split("/"))
    ):
        return JSONResponse({"detail": "Invalid API path"}, status_code=400)
    normalized_path = posixpath.normpath(request.url.path)
    protected = normalized_path.startswith(("/api/features", "/api/history", "/api/security", "/api/swarm", "/api/run"))
    if expected_key and protected and request.headers.get("x-api-key") != expected_key:
        return JSONResponse({"detail": "Unauthorized: invalid or missing X-API-Key"}, status_code=401)
    return await call_next(request)


class TaskRequest(BaseModel):
    task: str


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(index_path, encoding="utf-8") as f:
        return f.read()


@app.get("/api/models")
async def get_models():
    from config import MODELS
    return asdict(MODELS)


@app.get("/api/history")
async def get_history():
    async with _history_lock:
        return list(run_history[-20:])


@app.post("/api/run/stream")
async def run_stream(req: TaskRequest):
    """SSE endpoint: stream progress events về cho frontend"""

    async def event_generator():
        events: asyncio.Queue[str] = asyncio.Queue()

        async def on_progress(event: str, message: str):
            payload = json.dumps({"event": event, "message": message})
            await events.put(f"data: {payload}\n\n")

        def _sanitize_nan(obj):
            import math
            if isinstance(obj, float):
                return None if not math.isfinite(obj) else obj
            if isinstance(obj, dict):
                return {k: _sanitize_nan(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_sanitize_nan(v) for v in obj]
            if isinstance(obj, set):
                return [_sanitize_nan(v) for v in obj]
            return obj

        async def run_harness():
            import uuid
            import time
            import logging as _logging
            from agents import current_run_id, log_run_to_db
            run_id = f"run-{uuid.uuid4().hex[:8]}"
            token = current_run_id.set(run_id)
            try:
                start_time = time.perf_counter()
                harness = AgentHarness(progress_callback=on_progress)
                result: HarnessRun = await harness.run(req.task)

                duration_ms = int((time.perf_counter() - start_time) * 1000)
                log_run_to_db(run_id, "pipeline", duration_ms)

                async with _history_lock:
                    run_history.append({
                        "run_id":            result.run_id,
                        "task":              result.original_task,
                        "status":            result.status,
                        "total_duration_ms": result.total_duration_ms,
                        "agent_calls":       len(result.agent_results),
                        "final_summary":     result.final_summary[:2000],
                    })
                    history_snapshot = list(run_history)
                await save_history(history_snapshot)
                try:
                    _dump = _sanitize_nan(result.model_dump(mode="json"))
                    result_payload = json.dumps({"event": "result", "data": _dump}, allow_nan=False)
                except (TypeError, ValueError, UnicodeEncodeError):
                    try:
                        _dump = _sanitize_nan(result.model_dump(mode="json"))
                        result_payload = json.dumps({"event": "result", "data": _dump}, default=str, allow_nan=False, ensure_ascii=True)
                    except Exception as _ser_exc:
                        _logging.getLogger(__name__).error("Result serialization failed for run %s: %s", run_id, _ser_exc)
                        result_payload = json.dumps({"event": "error", "run_id": run_id, "message": "Result serialization failed"})
                await events.put(f"data: {result_payload}\n\n")
                await events.put("data: {\"event\": \"end\"}\n\n")
            except Exception as _exc:
                import logging as _logging
                _logging.getLogger(__name__).error("run_harness failed for run %s: %s", run_id, _exc)
                await events.put(f"data: {json.dumps({'event': 'error', 'run_id': run_id, 'message': str(_exc)})}\n\n")
                await events.put("data: {\"event\": \"end\"}\n\n")
            finally:
                try:
                    current_run_id.reset(token)
                except Exception:
                    pass

        # Chạy harness trong background
        task = asyncio.create_task(run_harness())

        # Stream events ra client
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(events.get(), timeout=120.0)
                    yield msg
                    if '"event": "end"' in msg or '"event":"end"' in msg:
                        break
                except asyncio.TimeoutError:
                    yield 'data: {"event": "timeout", "message": "Request timeout"}\n\n'
                    yield 'data: {"event": "end"}\n\n'
                    break
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/api/wiki/pages")
async def get_wiki_pages():
    """Liệt kê tất cả wiki pages (concepts + entities)."""
    wiki_root = _wiki_root()
    pages = []
    for sub in ["concepts", "entities"]:
        subdir = os.path.join(wiki_root, sub)
        if os.path.isdir(subdir):
            for fname in sorted(os.listdir(subdir)):
                if fname.endswith(".md"):
                    fpath = os.path.join(subdir, fname)
                    try:
                        stat = os.stat(fpath)
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            first_line = f.readline().strip()
                        pages.append({
                            "type": sub,
                            "name": fname[:-3],
                            "filename": fname,
                            "size_bytes": stat.st_size,
                            "preview": first_line[:120],
                        })
                    except Exception:
                        pass
    return {"pages": pages, "total": len(pages)}


@app.get("/api/wiki/search")
async def search_wiki(q: str = ""):
    """Tìm kiếm wiki theo keyword."""
    wiki_root = _wiki_root()
    if not q.strip():
        return {"results": [], "query": q}
    keywords = set(w.lower() for w in re.findall(r"\b[a-zA-Z0-9_À-ỹ]{2,}\b", q) if len(w) >= 2)
    results = []
    for sub in ["concepts", "entities"]:
        subdir = os.path.join(wiki_root, sub)
        if not os.path.isdir(subdir):
            continue
        for fname in sorted(os.listdir(subdir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(subdir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                content_lower = content.lower()
                score = sum(content_lower.count(kw) + (5 if kw in fname.lower() else 0) for kw in keywords)
                if score > 0:
                    # Extract first non-frontmatter paragraph as snippet
                    lines = [line for line in content.splitlines() if line.strip() and not line.startswith("---") and not line.startswith("#")]
                    snippet = lines[0][:200] if lines else content[:200]
                    results.append({"type": sub, "name": fname[:-3], "score": score, "snippet": snippet})
            except Exception:
                pass
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results[:10], "query": q}


class SecurityScanRequest(BaseModel):
    files: list[str]


@app.post("/api/security/scan")
async def security_scan(
    req: SecurityScanRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    """Chạy security_autofix: quét + tự động vá lỗi bảo mật Critical/High.
    Nếu env HARNESS_API_KEY được set, yêu cầu header X-API-Key khớp.
    """
    expected_key = os.getenv("HARNESS_API_KEY", "")
    if expected_key and x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-API-Key")
    import support_tools as st
    result = await st.security_autofix(files=req.files)
    return result


class AutoTesterRequest(BaseModel):
    files: list[str]
    findings: list[dict]


class VisualReviewerRequest(BaseModel):
    url: str
    baseline_url: Optional[str] = None


class BenchmarkerRequest(BaseModel):
    code_a: str
    code_b: str
    iterations: Optional[int] = 5


class DependencyUpgraderRequest(BaseModel):
    dry_run: Optional[bool] = True


class SchemaDriftRequest(BaseModel):
    baseline_schema: Optional[str] = None


class TelemetryDebuggerRequest(BaseModel):
    log_content: str


@app.post("/api/features/auto-tester")
async def api_auto_tester(req: AutoTesterRequest):
    import support_tools as st
    return await st.auto_tester(files=req.files, findings=req.findings)


@app.post("/api/features/visual-reviewer")
async def api_visual_reviewer(req: VisualReviewerRequest):
    import support_tools as st
    return await st.visual_reviewer(url=req.url, baseline_url=req.baseline_url)


@app.post("/api/features/benchmarker")
async def api_benchmarker(req: BenchmarkerRequest):
    import support_tools as st
    return await st.benchmarker(code_a=req.code_a, code_b=req.code_b, iterations=req.iterations or 5)


@app.post("/api/features/dependency-upgrader")
async def api_dependency_upgrader(req: DependencyUpgraderRequest):
    import support_tools as st
    return await st.dependency_upgrader(dry_run=req.dry_run if req.dry_run is not None else True)


@app.post("/api/features/schema-drift")
async def api_schema_drift(req: SchemaDriftRequest):
    import support_tools as st
    return await st.schema_drift(baseline_schema=req.baseline_schema)


@app.post("/api/features/doc-sync")
async def api_doc_sync():
    import support_tools as st
    return await st.doc_sync()


@app.post("/api/features/telemetry-debugger")
async def api_telemetry_debugger(req: TelemetryDebuggerRequest):
    import support_tools as st
    return await st.telemetry_debugger(log_content=req.log_content)


class SandboxRunRequest(BaseModel):
    code: str
    timeout: Optional[float] = 5.0


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5


class SwarmDebugRequest(BaseModel):
    error_log: str
    files: Optional[list[str]] = None


@app.post("/api/features/sandbox-run")
async def api_sandbox_run(
    req: SandboxRunRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    expected_key = os.getenv("HARNESS_API_KEY", "")
    if expected_key and x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-API-Key")
    import support_tools as st
    return st.run_in_sandbox(code=req.code, timeout=req.timeout or 5.0)


@app.post("/api/features/semantic-search")
async def api_semantic_search(req: SemanticSearchRequest):
    import support_tools as st
    return await st.semantic_search(query=req.query, top_k=req.top_k or 5)


@app.post("/api/features/swarm-debug")
async def api_swarm_debug(req: SwarmDebugRequest):
    import support_tools as st
    import uuid
    import time
    from agents import current_run_id, log_run_to_db
    
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    token = current_run_id.set(run_id)
    start_time = time.perf_counter()
    try:
        result = await st.swarm_debug(error_log=req.error_log, files=req.files)
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_run_to_db(run_id, "swarm_debug", duration_ms)
        result["run_id"] = run_id
        return result
    finally:
        try:
            current_run_id.reset(token)
        except Exception:
            pass


@app.get("/api/features/finops-stats")
async def api_finops_stats():
    from agents import get_finops_stats
    return get_finops_stats()


# ── 14 New Tool Endpoints ──────────────────────────────────────────────────

class PrGeneratorRequest(BaseModel):
    diff: Optional[str] = None
    branch: Optional[str] = None


class A11yAuditorRequest(BaseModel):
    files: Optional[list[str]] = None


class I18nAuditorRequest(BaseModel):
    files: Optional[list[str]] = None


class PolyglotReviewerRequest(BaseModel):
    files: list[str]


class GitArchaeologistRequest(BaseModel):
    file_path: str
    line_no: Optional[int] = None


class ProfilerRequest(BaseModel):
    code: str
    iterations: Optional[int] = 1


class IncidentResponderRequest(BaseModel):
    log_content: str


class ApiContractTesterRequest(BaseModel):
    endpoints: list[dict]


class ChaosTesterRequest(BaseModel):
    app_run_command: str
    duration: Optional[int] = 5


@app.post("/api/features/pr-generator")
async def api_pr_generator(req: PrGeneratorRequest):
    import support_tools as st
    return await st.pr_generator(diff=req.diff, branch=req.branch)


@app.post("/api/features/license-scanner")
async def api_license_scanner():
    import support_tools as st
    return await st.license_scanner()


@app.post("/api/features/sbom-generator")
async def api_sbom_generator():
    import support_tools as st
    return await st.sbom_generator()


@app.post("/api/features/a11y-auditor")
async def api_a11y_auditor(req: A11yAuditorRequest):
    import support_tools as st
    return await st.a11y_auditor(files=req.files)


@app.post("/api/features/i18n-auditor")
async def api_i18n_auditor(req: I18nAuditorRequest):
    import support_tools as st
    return await st.i18n_auditor(files=req.files)


@app.post("/api/features/polyglot-reviewer")
async def api_polyglot_reviewer(req: PolyglotReviewerRequest):
    import support_tools as st
    return await st.polyglot_reviewer(files=req.files)


@app.post("/api/features/git-archaeologist")
async def api_git_archaeologist(req: GitArchaeologistRequest):
    import support_tools as st
    return await st.git_archaeologist(file_path=req.file_path, line_no=req.line_no)


@app.post("/api/features/feature-flag-auditor")
async def api_feature_flag_auditor():
    import support_tools as st
    return await st.feature_flag_auditor()


@app.post("/api/features/dead-code-scanner")
async def api_dead_code_scanner():
    import support_tools as st
    return await st.dead_code_scanner()


@app.post("/api/features/profiler")
async def api_profiler(req: ProfilerRequest):
    import support_tools as st
    return st.profiler(code=req.code, iterations=req.iterations or 1)


@app.post("/api/features/coverage-analyzer")
async def api_coverage_analyzer():
    import support_tools as st
    return await st.coverage_analyzer()


@app.post("/api/features/incident-responder")
async def api_incident_responder(req: IncidentResponderRequest):
    import support_tools as st
    return await st.incident_responder(log_content=req.log_content)


@app.post("/api/features/api-contract-tester")
async def api_api_contract_tester(req: ApiContractTesterRequest):
    import support_tools as st
    return await st.api_contract_tester(endpoints=req.endpoints)


_chaos_sem = asyncio.Semaphore(1)

@app.post("/api/features/chaos-tester")
async def api_chaos_tester(
    req: ChaosTesterRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    expected_key = os.getenv("HARNESS_API_KEY", "")
    if expected_key and x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-API-Key")
    import support_tools as st
    async with _chaos_sem:
        return await asyncio.to_thread(st.chaos_tester, app_run_command=req.app_run_command, duration=req.duration or 5)


# ── New Phase 4 Endpoints: DevOps Gate, Config Security, Swarm Stepper ────────

def _is_terminal_state(state: str) -> bool:
    return state in ("completed", "rejected", "failed", "cancelled", "expired")


def _normalize_swarm_target_files(files: Optional[list[str]]) -> list[str]:
    if files is None:
        return []
    if not isinstance(files, list):
        raise ValueError("target_files must be a list")
    root = os.path.realpath(_active_workspace())
    normalized: list[str] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, str):
            raise ValueError("target_files entries must be strings")
        raw = item.strip().replace("\\", "/")
        if not raw or re.search(r"[\x00-\x1f]", raw):
            raise ValueError("target_files entries must be non-empty safe paths")
        if posixpath.isabs(raw):
            raise ValueError("target_files must be relative paths")
        rel = posixpath.normpath(raw)
        if rel in {"", ".", ".."} or rel.startswith("../"):
            raise ValueError("target_files cannot escape workspace")
        parts = {p.lower() for p in rel.split("/")}
        if parts & {".git", ".hg", ".svn"} or posixpath.basename(rel).lower() == ".env":
            raise ValueError("target_files cannot include repository metadata or .env")
        full = os.path.realpath(os.path.join(root, rel.replace("/", os.sep)))
        if os.path.commonpath([root, full]) != root:
            raise ValueError("target_files cannot escape workspace")
        if rel not in seen:
            normalized.append(rel)
            seen.add(rel)
    return normalized


def get_swarm_session(swarm_id: str) -> Optional[dict]:
    """Load swarm session; returns None if not found. Expired non-terminal sessions are
    auto-transitioned to 'expired' and backups restored before returning None."""
    init_db()  # lazy-init guard for test isolation
    try:
        conn = sqlite3.connect(get_finops_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM swarm_sessions WHERE swarm_id = ?", (swarm_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        d = dict(row)
        d["target_files"] = _normalize_swarm_target_files(json.loads(d["target_files"]) if d["target_files"] else [])
        d["logs"] = json.loads(d["logs"]) if d["logs"] else []
        d["final_result"] = json.loads(d["final_result"]) if d["final_result"] else {}

        state = d["state"]
        now = _time.time()
        if isinstance(state, str) and state.startswith("_locking_"):
            locked_for = now - float(d.get("updated_at") or 0)
            if locked_for > SWARM_LOCK_STALE_SECONDS:
                recovered_state = state.removeprefix("_locking_")
                cursor.execute(
                    "UPDATE swarm_sessions SET state=?, updated_at=? WHERE swarm_id=? AND state=?",
                    (recovered_state, now, swarm_id, state)
                )
                conn.commit()
                d["state"] = recovered_state
                d["updated_at"] = now
                print(f"[Harness Server] Swarm session {swarm_id} recovered stale lock: {state} -> {recovered_state}.")

        # TTL check: auto-expire non-terminal sessions
        expires_at = d.get("expires_at")
        if expires_at is not None and now > float(expires_at) and not _is_terminal_state(d["state"]):
            import support_tools as st
            backup_paths = d["final_result"].get("backup_paths", [])
            if backup_paths:
                st._restore_session_backups(backup_paths)
            cursor.execute(
                "UPDATE swarm_sessions SET state='expired', updated_at=? WHERE swarm_id=? AND state=?",
                (now, swarm_id, d["state"])
            )
            conn.commit()
            conn.close()
            print(f"[Harness Server] Swarm session {swarm_id} auto-expired (TTL exceeded).")
            return None

        conn.close()
        return d
    except Exception as e:
        print(f"[Harness Server] Error loading swarm session: {e}")
    return None


def save_swarm_session(session: dict):
    """Persist swarm session. Sets/refreshes expires_at for non-terminal states."""
    init_db()  # lazy-init guard
    try:
        # Non-terminal sessions get a fresh TTL window on every save
        state = session["state"]
        target_files = _normalize_swarm_target_files(session.get("target_files", []))
        expires_at = (
            None if _is_terminal_state(state)
            else _time.time() + SWARM_SESSION_TTL_SECONDS
        )
        conn = sqlite3.connect(get_finops_db_path())
        cursor = conn.cursor()
        current = cursor.execute("SELECT state FROM swarm_sessions WHERE swarm_id=?", (session["swarm_id"],)).fetchone()
        if current and _is_terminal_state(str(current[0])) and str(current[0]) != state:
            conn.close()
            print(f"[Harness Server] Refused stale write over terminal swarm session {session['swarm_id']}.")
            return
        cursor.execute("""
            INSERT OR REPLACE INTO swarm_sessions
                (swarm_id, state, error_log, target_files, reproducer_code,
                 suggested_patch, logs, final_result, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["swarm_id"],
            state,
            session["error_log"],
            json.dumps(target_files),
            session.get("reproducer_code", ""),
            session.get("suggested_patch", ""),
            json.dumps(session.get("logs", [])),
            json.dumps(session.get("final_result", {})),
            expires_at,
            _time.time(),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Harness Server] Error saving swarm session: {e}")


def cas_swarm_state(swarm_id: str, expected_state: str, new_state: str) -> bool:
    """Atomic Compare-And-Swap on swarm state to prevent concurrent double-proceed.
    Returns True if the update succeeded (exactly 1 row changed), False otherwise."""
    try:
        conn = sqlite3.connect(get_finops_db_path())
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE swarm_sessions SET state=?, updated_at=? WHERE swarm_id=? AND state=?",
            (new_state, _time.time(), swarm_id, expected_state)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected == 1
    except Exception as e:
        print(f"[Harness Server] CAS error for {swarm_id}: {e}")
        return False

@app.get("/api/features/devops-pipeline")
async def api_devops_pipeline():
    import support_tools as st
    return await st.devops_pipeline()

@app.get("/api/features/config-audit")
async def api_config_audit():
    import support_tools as st
    return await st.config_security_audit()

class SwarmInitRequest(BaseModel):
    error_log: str
    files: Optional[list[str]] = None

@app.post("/api/swarm/init")
async def api_swarm_init(req: SwarmInitRequest):
    import support_tools as st
    import uuid
    try:
        input_files = _normalize_swarm_target_files(req.files)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    
    swarm_id = f"swarm-{uuid.uuid4().hex[:8]}"
    
    # Run Step 1: Architect
    arch_res = await st.swarm_step_architect(req.error_log, input_files)
    if "error" in arch_res:
        return arch_res
    try:
        target_files = _normalize_swarm_target_files(arch_res["target_files"])
        if not target_files:
            raise ValueError("target_files cannot be empty")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
        
    session = {
        "swarm_id": swarm_id,
        "state": "pending_tester",
        "error_log": req.error_log,
        "target_files": target_files,
        "reproducer_code": "",
        "suggested_patch": "",
        "logs": arch_res["logs"],
        "final_result": {
            "root_cause": arch_res["root_cause"],
            "suggested_approach": arch_res["suggested_approach"]
        }
    }
    
    save_swarm_session(session)
    
    return {
        "swarm_id": swarm_id,
        "state": "pending_tester",
        "root_cause": arch_res["root_cause"],
        "suggested_approach": arch_res["suggested_approach"],
        "target_files": target_files,
        "logs": arch_res["logs"],
        "warnings": arch_res.get("warnings", [])
    }

@app.get("/api/swarm/session/{swarm_id}")
async def api_swarm_get_session(swarm_id: str):
    sess = get_swarm_session(swarm_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Swarm session not found")
    return sess

class SwarmProceedBody(BaseModel):
    target_files: Optional[list[str]] = None
    reproducer_code: Optional[str] = None
    patch: Optional[str] = None

@app.post("/api/swarm/proceed/{swarm_id}")
async def api_swarm_proceed(swarm_id: str, body: SwarmProceedBody):
    import support_tools as st
    import time

    sess = get_swarm_session(swarm_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Swarm session not found or expired")

    state = sess["state"]
    final_result = sess["final_result"]
    try:
        if body.target_files is not None:
            body.target_files = _normalize_swarm_target_files(body.target_files)
        sess["target_files"] = _normalize_swarm_target_files(sess.get("target_files", []))
        effective_files = body.target_files if body.target_files is not None else sess["target_files"]
        if not effective_files:
            raise ValueError("target_files cannot be empty")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ── State-transition map for CAS locking ──────────────────────────────────
    _valid_proceed_states = {"pending_tester", "pending_coder", "pending_apply", "pending_review"}
    if state not in _valid_proceed_states:
        raise HTTPException(status_code=400, detail=f"Cannot proceed from state: {state}")

    # Atomic CAS: prevent duplicate/concurrent proceed on same session+state.
    # Sets state to "_locking_<state>" so concurrent proceed calls fail CAS.
    if not cas_swarm_state(swarm_id, state, f"_locking_{state}"):
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: another request is already advancing this session from state '{state}'. Please retry."
        )
    # Refresh TTL with correct locked state so session doesn't expire and lock is not inadvertently released.
    sess["state"] = f"_locking_{state}"
    sess["expires_at"] = _time.time() + SWARM_SESSION_TTL_SECONDS
    sess["updated_at"] = _time.time()
    save_swarm_session(sess)
    try:
        if state == "pending_tester":
            t_files = effective_files
            sess["target_files"] = t_files

            tester_res = await st.swarm_step_tester(
                sess["error_log"],
                final_result.get("root_cause", ""),
                t_files,
                custom_reproducer=body.reproducer_code
            )
            if "error" in tester_res:
                cas_swarm_state(swarm_id, f"_locking_{state}", state)
                return tester_res

            sess["reproducer_code"] = tester_res["reproducer_code"]
            sess["state"] = "pending_coder"
            sess["logs"].extend(tester_res["logs"])

            save_swarm_session(sess)

            return {
                "swarm_id": swarm_id,
                "state": "pending_coder",
                "reproducer_code": tester_res["reproducer_code"],
                "reproducer_failed": tester_res["reproducer_failed"],
                "sandbox_output": tester_res["sandbox_output"],
                "logs": sess["logs"]
            }

        elif state == "pending_coder":
            coder_res = await st.swarm_step_coder(
                sess["error_log"],
                final_result.get("suggested_approach", ""),
                sess["target_files"],
                sess["reproducer_code"]
            )
            if "error" in coder_res:
                cas_swarm_state(swarm_id, f"_locking_{state}", state)
                return coder_res

            sess["suggested_patch"] = coder_res["patch"]
            sess["state"] = "pending_apply"
            sess["logs"].extend(coder_res["logs"])

            save_swarm_session(sess)

            return {
                "swarm_id": swarm_id,
                "state": "pending_apply",
                "patch": coder_res["patch"],
                "logs": sess["logs"]
            }

        elif state == "pending_apply":
            patch_to_use = body.patch if body.patch is not None else sess["suggested_patch"]
            sess["suggested_patch"] = patch_to_use

            apply_res = st.swarm_step_apply_and_test(sess["target_files"], patch_to_use, sess.get("reproducer_code", ""))
            sess["logs"].extend(apply_res["logs"])

            final_result["backup_paths"] = apply_res["backup_paths"]

            if apply_res["status"] == "success":
                sess["state"] = "pending_review"
                sess["final_result"] = final_result
                save_swarm_session(sess)
                return {
                    "swarm_id": swarm_id,
                    "state": "pending_review",
                    "patch_applied": True,
                    "test_passed": True,
                    "logs": sess["logs"]
                }
            else:
                sess["state"] = "failed"
                sess["final_result"] = final_result
                save_swarm_session(sess)
                return {
                    "swarm_id": swarm_id,
                    "state": "failed",
                    "patch_applied": apply_res["patch_applied_successfully"],
                    "test_passed": False,
                    "message": apply_res["message"],
                    "logs": sess["logs"]
                }

        elif state == "pending_review":
            rev_res = await st.swarm_step_reviewer(sess["target_files"], sess["suggested_patch"])
            sess["logs"].extend(rev_res["logs"])

            verdict = rev_res["verdict"]
            summary = rev_res["summary"]

            backup_paths = final_result.get("backup_paths", [])

            if verdict == "approve":
                sess["state"] = "completed"
                st._cleanup_session_backups(backup_paths)
                sess["logs"].append({"role": "coordinator", "message": f"Nghiệm thu: Bản vá được Approve! {summary}", "timestamp": time.time()})
            else:
                sess["state"] = "rejected"
                st._restore_session_backups(backup_paths)
                sess["logs"].append({"role": "coordinator", "message": f"Từ chối: Bản vá bị Reject (Đã rollback). {summary}", "timestamp": time.time()})

            sess["final_result"] = final_result

            save_swarm_session(sess)

            return {
                "swarm_id": swarm_id,
                "state": sess["state"],
                "verdict": verdict,
                "summary": summary,
                "logs": sess["logs"]
            }

        else:
            raise HTTPException(status_code=400, detail=f"Cannot proceed from state: {state}")

    except HTTPException:
        cas_swarm_state(swarm_id, f"_locking_{state}", state)
        sess["state"] = state
        sess["updated_at"] = _time.time()
        save_swarm_session(sess)
        raise
    except Exception as _exc:
        cas_swarm_state(swarm_id, f"_locking_{state}", state)
        sess["state"] = state
        sess["updated_at"] = _time.time()
        save_swarm_session(sess)
        raise

@app.post("/api/swarm/cancel/{swarm_id}")
async def api_swarm_cancel(swarm_id: str):
    import support_tools as st
    import time
    
    sess = get_swarm_session(swarm_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Swarm session not found")
        
    state = sess.get("state") or ""

    if not isinstance(state, str) or state.startswith("_locking_"):
        raise HTTPException(status_code=409, detail="Cannot cancel: a proceed request is currently in progress. Please retry.")
    if _is_terminal_state(state):
        raise HTTPException(status_code=400, detail=f"Cannot cancel terminal session: {state}")
    if not cas_swarm_state(swarm_id, state, f"_locking_{state}"):
        raise HTTPException(status_code=409, detail="Cannot cancel: session state changed. Please retry.")

    backup_paths = sess["final_result"].get("backup_paths", [])
    if not cas_swarm_state(swarm_id, f"_locking_{state}", "cancelled"):
        raise HTTPException(status_code=409, detail="Cannot cancel: session state changed during cancel finalization.")

    if state in ("pending_review", "pending_apply"):
        st._restore_session_backups(backup_paths)
        
    sess["state"] = "cancelled"
    sess["logs"].append({"role": "coordinator", "message": "Quy trình Swarm bị hủy bỏ bởi người dùng.", "timestamp": time.time()})
    
    save_swarm_session(sess)
    return {"status": "success", "state": "cancelled", "logs": sess["logs"]}


if __name__ == "__main__":
    import uvicorn
    import os
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=True)
