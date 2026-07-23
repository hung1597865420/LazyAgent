"""Cross-session coordination for Agent Harness.

Static-first coordinator for multiple Claude/Gemini/Codex/opencode sessions.
It uses SQLite WAL as the source of truth for session heartbeats, file leases,
snapshots, and conflict events. It never calls an LLM.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from runtime_flags import bool_flag, load_feature_flags
from .core import _get_active_workspace

SESSION_TTL_SECONDS = 180.0
LEASE_TTL_SECONDS = 900.0
MAX_EVENT_ROWS = 1000


def _now() -> float:
    return time.time()


def _detect_agent_kind() -> str:
    meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA", "")
    if meta:
        return "gemini-antigravity"
    if os.getenv("CODEX_HOME") or os.getenv("CODEX_SANDBOX"):
        return "codex"
    if os.getenv("CLAUDECODE") or os.getenv("CLAUDE_PROJECT_DIR"):
        return "claude"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_CLI"):
        return "gemini"
    if os.getenv("OPENCODE_SESSION") or os.getenv("OPENCODE_HOME"):
        return "opencode"
    return "unknown"


_PROCESS_SESSION_ID = uuid.uuid4().hex[:10]


def _default_session_id(agent_kind: str | None = None) -> str:
    explicit = os.getenv("HARNESS_SESSION_ID", "").strip()
    if explicit:
        return explicit[:120]
    kind = (agent_kind or _detect_agent_kind() or "unknown").replace(" ", "-")
    return f"{kind}-{_PROCESS_SESSION_ID}"


def _coordination_enabled(root: Path) -> bool:
    return bool_flag("HARNESS_COORDINATION_ENABLED", True, root=root)


def _profile_snapshot(root: Path) -> dict[str, Any]:
    try:
        flags = load_feature_flags(root=root)
        if not isinstance(flags, dict):
            return {"profile": "off", "llm_enabled": False}
        llm = flags.get("llm") if isinstance(flags.get("llm"), dict) else {}
        return {"profile": str(flags.get("profile") or "off"), "llm_enabled": bool(llm.get("enabled"))}
    except Exception:
        return {"profile": "off", "llm_enabled": False}


def _workspace_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(_get_active_workspace()).resolve()


def _git_branch(root: Path) -> str:
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("ref:"):
            return text.rsplit("/", 1)[-1] or "unknown"
        return text[:12] if text else "unknown"
    except OSError:
        return "nogit"


def _workspace_id(root: Path) -> str:
    return hashlib.sha256(f"{root.as_posix()}|{_git_branch(root)}".encode("utf-8", errors="replace")).hexdigest()[:20]


def _coord_dir(root: Path) -> Path:
    mode = os.getenv("HARNESS_COORDINATION_DB_MODE", "").strip().lower()
    if mode in {"repo", "repo-local", "local"}:
        path = root / ".harness"
    else:
        path = Path(os.getenv("USERPROFILE") or str(Path.home())) / ".agent-harness"
    path.mkdir(parents=True, exist_ok=True)
    return path


def coordination_db_path(root: str | Path | None = None) -> Path:
    explicit = os.getenv("HARNESS_COORDINATION_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _coord_dir(_workspace_root(root)) / "coordination.db"


def _connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(coordination_db_path(root)), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            agent_kind TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            workspace_root TEXT NOT NULL,
            worktree_root TEXT,
            git_branch TEXT NOT NULL,
            profile TEXT NOT NULL,
            task_summary TEXT,
            pid INTEGER,
            process_start_id TEXT,
            status TEXT NOT NULL,
            heartbeat_at REAL NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id, heartbeat_at);

        CREATE TABLE IF NOT EXISTS file_leases (
            workspace_id TEXT NOT NULL,
            path TEXT NOT NULL,
            session_id TEXT NOT NULL,
            agent_kind TEXT NOT NULL,
            task_summary TEXT,
            symbols_json TEXT,
            risk TEXT NOT NULL,
            base_hash TEXT,
            base_diff_hash TEXT,
            mtime_ns INTEGER,
            size INTEGER,
            lease_mode TEXT NOT NULL,
            expires_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            claimed_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(workspace_id, path, session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_file_leases_path ON file_leases(workspace_id, path, expires_at);

        CREATE TABLE IF NOT EXISTS symbol_leases (
            workspace_id TEXT NOT NULL,
            path TEXT NOT NULL,
            symbol TEXT NOT NULL,
            session_id TEXT NOT NULL,
            agent_kind TEXT NOT NULL,
            range_start INTEGER,
            range_end INTEGER,
            expires_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY(workspace_id, path, symbol, session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_symbol_leases_path ON symbol_leases(workspace_id, path, symbol, expires_at);

        CREATE TABLE IF NOT EXISTS file_snapshots (
            workspace_id TEXT NOT NULL,
            path TEXT NOT NULL,
            session_id TEXT NOT NULL,
            sha256 TEXT,
            base_diff_hash TEXT,
            mtime_ns INTEGER,
            size INTEGER,
            claimed_at REAL,
            recorded_at REAL NOT NULL,
            PRIMARY KEY(workspace_id, path, session_id)
        );

        CREATE TABLE IF NOT EXISTS conflict_events (
            event_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            path TEXT,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            sessions_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at REAL NOT NULL,
            resolved_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_conflicts_workspace ON conflict_events(workspace_id, status, created_at);

        CREATE TABLE IF NOT EXISTS coordination_events (
            event_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            session_id TEXT,
            event_type TEXT NOT NULL,
            path TEXT,
            payload_json TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_coord_events_workspace ON coordination_events(workspace_id, created_at);

        CREATE TABLE IF NOT EXISTS operation_results (
            operation_key TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            updated_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        """
    )
    _ensure_column(conn, "sessions", "worktree_root", "TEXT")
    _ensure_column(conn, "file_leases", "base_diff_hash", "TEXT")
    _ensure_column(conn, "file_leases", "claimed_at", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "file_snapshots", "base_diff_hash", "TEXT")
    _ensure_column(conn, "file_snapshots", "claimed_at", "REAL")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _iter_file_values(files: Any) -> list[Any]:
    if isinstance(files, str):
        return [files]
    elif isinstance(files, (list, tuple, set)):
        return list(files)
    return []


def _file_record_values(item: Any) -> list[str]:
    if isinstance(item, str):
        return [item]
    if isinstance(item, dict):
        out: list[str] = []
        for key in ("path", "new_path", "old_path"):
            value = item.get(key)
            if isinstance(value, str):
                out.append(value)
        paths = item.get("paths")
        if isinstance(paths, (list, tuple, set)):
            out.extend(str(path) for path in paths if isinstance(path, str))
        return out
    return []


def _norm_files(files: Any, root: Path) -> list[str]:
    items = _iter_file_values(files)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        for value in _file_record_values(item):
            if not isinstance(value, str) or not value.strip():
                continue
            raw = value.strip().replace("\\", "/")
            try:
                candidate = Path(raw)
                if candidate.is_absolute():
                    resolved = candidate.resolve(strict=False)
                    if root != resolved and root not in resolved.parents:
                        continue
                    rel = resolved.relative_to(root).as_posix()
                else:
                    rel = Path(raw).as_posix().strip("/")
                    if rel.startswith("../") or rel == "..":
                        continue
            except Exception:
                continue
            if rel and rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out


def _norm_file_records(files: Any, root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _iter_file_values(files):
        values = _file_record_values(item)
        rels = _norm_files(values, root)
        if not rels:
            continue
        primary = rels[0]
        if primary in seen:
            continue
        seen.add(primary)
        record = {"path": primary}
        if isinstance(item, dict):
            old_paths = _norm_files([item.get("old_path")], root)
            new_paths = _norm_files([item.get("new_path")], root)
            if old_paths:
                record["old_path"] = old_paths[0]
            if new_paths:
                record["new_path"] = new_paths[0]
            if item.get("status"):
                record["status"] = str(item.get("status"))[:40]
        if len(rels) > 1:
            record["paths"] = rels
        records.append(record)
    return records


def _git_worktree_root(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return str(Path(proc.stdout.strip()).resolve())
    except Exception:
        pass
    return str(root)


def _file_diff_hash(root: Path, rel: str) -> str | None:
    try:
        digest = hashlib.sha256()
        for args in (["git", "diff", "--", rel], ["git", "diff", "--cached", "--", rel]):
            proc = subprocess.run(args, cwd=str(root), capture_output=True, timeout=5)
            if proc.returncode == 0:
                digest.update(proc.stdout or b"")
        value = digest.hexdigest()
        return value if value != hashlib.sha256(b"").hexdigest() else None
    except Exception:
        return None


def _snapshot(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    try:
        if path.is_symlink():
            stat = path.lstat()
            return {"sha256": "symlink", "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        if not path.is_file():
            return {"sha256": None, "mtime_ns": None, "size": None}
        stat = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest(), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
    except OSError:
        return {"sha256": None, "mtime_ns": None, "size": None}


def _symbols(value: Any) -> set[str]:
    if isinstance(value, str):
        items: Any = [value]
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = []
    return {str(item).strip() for item in items if str(item or "").strip()}


def _symbols_json(symbols: Any) -> str:
    return json.dumps(sorted(_symbols(symbols)), ensure_ascii=False)


def _risk_for_path(path: str) -> str:
    lower = path.lower().replace("\\", "/")
    name = lower.rsplit("/", 1)[-1]
    if name in {".env", ".env.local", ".env.production", ".env.example"} or any(x in lower for x in ("auth", "security", "permission", "migration", "alembic/versions", "docker", ".github/workflows", "config")):
        return "hard"
    if name.endswith((".db", ".sqlite", ".sqlite3", ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf")):
        return "exclusive"
    if any(part in lower.split("/") for part in {"dist", "build", "coverage", "generated", "__generated__"}) or name.endswith((".min.js", ".min.css", ".map", ".lock")):
        return "generated"
    if name.endswith((".md", ".txt", ".rst")) or "/test" in lower or name.startswith("test_"):
        return "soft"
    if name.endswith((".css", ".scss", ".html", ".jsx", ".tsx", ".vue", ".svelte")):
        return "soft"
    return "hard"


def _severity_for(path: str, symbols_a: set[str], symbols_b: set[str]) -> str:
    risk = _risk_for_path(path)
    if risk in {"exclusive", "hard"}:
        return risk
    if risk == "generated":
        return "warning"
    if symbols_a and symbols_b and symbols_a.isdisjoint(symbols_b):
        return "warning"
    return "soft"


def _cleanup_stale(conn: sqlite3.Connection, workspace_id: str, now: float) -> int:
    stale_cutoff = now - SESSION_TTL_SECONDS
    stale_sessions = [
        str(row["session_id"])
        for row in conn.execute(
            "SELECT session_id FROM sessions WHERE workspace_id=? AND heartbeat_at<?",
            (workspace_id, stale_cutoff),
        )
    ]
    conn.execute("UPDATE sessions SET status='stale' WHERE workspace_id=? AND heartbeat_at<?", (workspace_id, stale_cutoff))
    conn.execute("DELETE FROM file_leases WHERE workspace_id=? AND expires_at<?", (workspace_id, now))
    conn.execute("DELETE FROM symbol_leases WHERE workspace_id=? AND expires_at<?", (workspace_id, now))
    for sid in stale_sessions:
        conn.execute("DELETE FROM file_leases WHERE workspace_id=? AND session_id=?", (workspace_id, sid))
        conn.execute("DELETE FROM symbol_leases WHERE workspace_id=? AND session_id=?", (workspace_id, sid))
    old_event_cutoff = now - 86400 * 7
    conn.execute("DELETE FROM coordination_events WHERE workspace_id=? AND created_at<?", (workspace_id, old_event_cutoff))
    conn.execute("DELETE FROM operation_results WHERE workspace_id=? AND expires_at<?", (workspace_id, now))
    return len(stale_sessions)


def _record_event(conn: sqlite3.Connection, workspace_id: str, event_type: str, *, session_id: str | None = None, path: str | None = None, payload: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO coordination_events(event_id, workspace_id, session_id, event_type, path, payload_json, created_at) VALUES(?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, workspace_id, session_id, event_type, path, json.dumps(payload or {}, ensure_ascii=False, default=str), _now()),
    )
    count = conn.execute("SELECT COUNT(*) AS c FROM coordination_events WHERE workspace_id=?", (workspace_id,)).fetchone()["c"]
    if count > MAX_EVENT_ROWS:
        conn.execute(
            "DELETE FROM coordination_events WHERE event_id IN (SELECT event_id FROM coordination_events WHERE workspace_id=? ORDER BY created_at ASC LIMIT ?)",
            (workspace_id, int(count - MAX_EVENT_ROWS)),
        )


def _record_conflict(conn: sqlite3.Connection, workspace_id: str, path: str, severity: str, sessions: list[str], reason: str) -> str:
    event_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO conflict_events(event_id, workspace_id, path, severity, status, sessions_json, reason, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (event_id, workspace_id, path, severity, "open", json.dumps(sorted(set(sessions)), ensure_ascii=False), reason, _now()),
    )
    return event_id


def _should_warn_missing_lease(stage: str, require_lease: bool | None) -> bool:
    if require_lease is not None:
        return require_lease
    normalized = (stage or "").strip().lower()
    quiet_prefixes = ("auto_trigger", "background_watch", "watcher", "advisor")
    if normalized.startswith(quiet_prefixes):
        return False
    strict_tokens = ("final", "commit", "panel_review", "prod_readiness_gate", "release", "goal_runner")
    return any(token in normalized for token in strict_tokens)


def session_heartbeat(
    session_id: str | None = None,
    agent_kind: str | None = None,
    task: str | None = None,
    status: str = "active",
    root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = _workspace_root(root)
    if not _coordination_enabled(root_path):
        agent = (agent_kind or _detect_agent_kind() or "unknown").strip()[:60]
        sid = (session_id or _default_session_id(agent)).strip()[:120]
        profile = _profile_snapshot(root_path).get("profile", "off")
        return {"status": "skipped", "reason": "coordination_disabled", "session_id": sid, "agent_kind": agent, "profile": profile}
    workspace_id = _workspace_id(root_path)
    agent = (agent_kind or _detect_agent_kind() or "unknown").strip()[:60]
    sid = (session_id or _default_session_id(agent)).strip()[:120]
    profile = _profile_snapshot(root_path).get("profile", "off")
    now = _now()
    with _connect(root_path) as conn:
        _cleanup_stale(conn, workspace_id, now)
        conn.execute(
            """
            INSERT INTO sessions(session_id, agent_kind, workspace_id, workspace_root, worktree_root, git_branch, profile, task_summary, pid, process_start_id, status, heartbeat_at, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                agent_kind=excluded.agent_kind,
                workspace_id=excluded.workspace_id,
                workspace_root=excluded.workspace_root,
                worktree_root=excluded.worktree_root,
                git_branch=excluded.git_branch,
                profile=excluded.profile,
                task_summary=COALESCE(excluded.task_summary, sessions.task_summary),
                pid=excluded.pid,
                process_start_id=excluded.process_start_id,
                status=excluded.status,
                heartbeat_at=excluded.heartbeat_at
            """,
            (
                sid,
                agent,
                workspace_id,
                str(root_path),
                _git_worktree_root(root_path),
                _git_branch(root_path),
                str(profile),
                (task or "")[:500],
                os.getpid(),
                f"{platform.node()}:{os.getpid()}:{getattr(os, 'getppid', lambda: 0)()}",
                status or "active",
                now,
                now,
            ),
        )
        _record_event(conn, workspace_id, "heartbeat", session_id=sid, payload={"agent_kind": agent, "profile": profile})
        conn.commit()
    return {"status": "completed", "session_id": sid, "agent_kind": agent, "workspace_id": workspace_id, "profile": profile, "db": str(coordination_db_path(root_path))}


def active_sessions(root: str | Path | None = None) -> dict[str, Any]:
    root_path = _workspace_root(root)
    if not _coordination_enabled(root_path):
        return {"status": "skipped", "reason": "coordination_disabled", "sessions": []}
    workspace_id = _workspace_id(root_path)
    now = _now()
    with _connect(root_path) as conn:
        stale = _cleanup_stale(conn, workspace_id, now)
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT session_id, agent_kind, profile, task_summary, status, heartbeat_at, pid FROM sessions WHERE workspace_id=? ORDER BY heartbeat_at DESC",
                (workspace_id,),
            )
        ]
        conn.commit()
    for row in rows:
        row["age_seconds"] = round(now - float(row.get("heartbeat_at") or 0), 2)
    return {"status": "completed", "workspace_id": workspace_id, "stale_cleaned": stale, "sessions": rows}


def claim_files(
    files: list[str] | tuple[str, ...] | set[str] | str | None,
    session_id: str | None = None,
    agent_kind: str | None = None,
    task: str | None = None,
    symbols: list[str] | tuple[str, ...] | set[str] | str | None = None,
    lease_mode: str = "auto",
    ttl_seconds: float = LEASE_TTL_SECONDS,
    allow_shared: bool = False,
    root: str | Path | None = None,
) -> dict[str, Any]:
    hb = session_heartbeat(session_id=session_id, agent_kind=agent_kind, task=task, root=root)
    if hb.get("status") == "skipped":
        return {"status": "skipped", "reason": hb.get("reason"), "session_id": hb.get("session_id"), "claimed": [], "conflicts": [], "warnings": []}
    sid = hb["session_id"]
    agent = hb["agent_kind"]
    root_path = _workspace_root(root)
    workspace_id = _workspace_id(root_path)
    rels = _norm_files(files, root_path)
    now = _now()
    requested_symbols = _symbols(symbols)
    conflicts: list[dict[str, Any]] = []
    blocking_conflicts: list[dict[str, Any]] = []
    claimed: list[str] = []
    warnings: list[str] = []
    with _connect(root_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _cleanup_stale(conn, workspace_id, now)
        snapshots: dict[str, dict[str, Any]] = {}
        risks: dict[str, str] = {}
        for rel in rels:
            snapshots[rel] = _snapshot(root_path, rel)
            risks[rel] = _risk_for_path(rel)
            other_rows = [
                row for row in conn.execute(
                    "SELECT * FROM file_leases WHERE workspace_id=? AND path=? AND session_id<>? AND expires_at>?",
                    (workspace_id, rel, sid, now),
                )
            ]
            hard_block = False
            for row in other_rows:
                other_symbols = _symbols(json.loads(row["symbols_json"] or "[]"))
                severity = _severity_for(rel, requested_symbols, other_symbols)
                item = {
                    "path": rel,
                    "severity": severity,
                    "owner": row["session_id"],
                    "owner_agent": row["agent_kind"],
                    "owner_task": row["task_summary"],
                    "reason": "active file lease overlap",
                }
                conflicts.append(item)
                if severity in {"hard", "exclusive", "soft"} and not allow_shared:
                    hard_block = True
                    blocking_conflicts.append(item)
                elif severity == "warning":
                    warnings.append(f"{rel}: active lease overlap appears non-blocking because symbols differ")
            if hard_block:
                _record_conflict(conn, workspace_id, rel, "hard", [sid] + [str(r["session_id"]) for r in other_rows], "claim blocked by active lease")
            if other_rows and allow_shared:
                warnings.append(f"{rel}: shared despite active lease")

        if blocking_conflicts and not allow_shared:
            conn.commit()
            return {"status": "blocked_conflict", "session_id": sid, "claimed": [], "conflicts": blocking_conflicts, "warnings": warnings}

        for rel in rels:
            snap = snapshots[rel]
            risk = risks[rel]
            base_diff_hash = _file_diff_hash(root_path, rel)
            expires = now + max(30.0, min(float(ttl_seconds or LEASE_TTL_SECONDS), 86400.0))
            conn.execute(
                """
                INSERT INTO file_leases(workspace_id, path, session_id, agent_kind, task_summary, symbols_json, risk, base_hash, base_diff_hash, mtime_ns, size, lease_mode, expires_at, updated_at, claimed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(workspace_id, path, session_id) DO UPDATE SET
                    task_summary=excluded.task_summary,
                    symbols_json=excluded.symbols_json,
                    risk=excluded.risk,
                    base_hash=excluded.base_hash,
                    base_diff_hash=excluded.base_diff_hash,
                    mtime_ns=excluded.mtime_ns,
                    size=excluded.size,
                    lease_mode=excluded.lease_mode,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at,
                    claimed_at=excluded.claimed_at
                """,
                (workspace_id, rel, sid, agent, (task or "")[:500], _symbols_json(symbols), risk, snap["sha256"], base_diff_hash, snap["mtime_ns"], snap["size"], lease_mode or "auto", expires, now, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO file_snapshots(workspace_id, path, session_id, sha256, base_diff_hash, mtime_ns, size, claimed_at, recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (workspace_id, rel, sid, snap["sha256"], base_diff_hash, snap["mtime_ns"], snap["size"], now, now),
            )
            for symbol in sorted(requested_symbols):
                conn.execute(
                    """
                    INSERT INTO symbol_leases(workspace_id, path, symbol, session_id, agent_kind, range_start, range_end, expires_at, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(workspace_id, path, symbol, session_id) DO UPDATE SET
                        agent_kind=excluded.agent_kind,
                        expires_at=excluded.expires_at,
                        updated_at=excluded.updated_at
                    """,
                    (workspace_id, rel, symbol, sid, agent, None, None, expires, now),
                )
            _record_event(conn, workspace_id, "claim", session_id=sid, path=rel, payload={"risk": risk, "symbols": sorted(requested_symbols)})
            claimed.append(rel)
        conn.commit()
    status = "blocked_conflict" if conflicts and not allow_shared and len(claimed) < len(rels) else "completed"
    return {"status": status, "session_id": sid, "claimed": claimed, "conflicts": conflicts, "warnings": warnings}


def release_files(
    files: list[str] | tuple[str, ...] | set[str] | str | None = None,
    session_id: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = _workspace_root(root)
    if not _coordination_enabled(root_path):
        return {"status": "skipped", "reason": "coordination_disabled", "released": []}
    workspace_id = _workspace_id(root_path)
    sid = (session_id or _default_session_id()).strip()[:120]
    rels = _norm_files(files, root_path)
    with _connect(root_path) as conn:
        if rels:
            for rel in rels:
                conn.execute("DELETE FROM file_leases WHERE workspace_id=? AND session_id=? AND path=?", (workspace_id, sid, rel))
                conn.execute("DELETE FROM symbol_leases WHERE workspace_id=? AND session_id=? AND path=?", (workspace_id, sid, rel))
                _record_event(conn, workspace_id, "release", session_id=sid, path=rel)
        else:
            conn.execute("DELETE FROM file_leases WHERE workspace_id=? AND session_id=?", (workspace_id, sid))
            conn.execute("DELETE FROM symbol_leases WHERE workspace_id=? AND session_id=?", (workspace_id, sid))
            _record_event(conn, workspace_id, "release_all", session_id=sid)
        conn.commit()
    return {"status": "completed", "session_id": sid, "released": rels or "all"}


def conflict_check(
    files: list[str] | tuple[str, ...] | set[str] | str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    stage: str = "manual",
    require_lease: bool | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    hb = session_heartbeat(session_id=session_id, task=task, root=root)
    if hb.get("status") == "skipped":
        return {"status": "skipped", "reason": hb.get("reason"), "session_id": hb.get("session_id"), "stage": stage, "files": [], "conflicts": [], "warnings": []}
    sid = hb["session_id"]
    root_path = _workspace_root(root)
    workspace_id = _workspace_id(root_path)
    rels = _norm_files(files, root_path)
    now = _now()
    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = []
    warn_missing_lease = _should_warn_missing_lease(stage, require_lease)
    with _connect(root_path) as conn:
        _cleanup_stale(conn, workspace_id, now)
        if not rels:
            rels = [str(row["path"]) for row in conn.execute("SELECT DISTINCT path FROM file_leases WHERE workspace_id=? AND session_id=?", (workspace_id, sid))]
        for rel in rels:
            snap = _snapshot(root_path, rel)
            own = conn.execute(
                "SELECT * FROM file_leases WHERE workspace_id=? AND path=? AND session_id=?",
                (workspace_id, rel, sid),
            ).fetchone()
            other_rows = [
                row for row in conn.execute(
                    "SELECT * FROM file_leases WHERE workspace_id=? AND path=? AND session_id<>? AND expires_at>?",
                    (workspace_id, rel, sid, now),
                )
            ]
            for row in other_rows:
                severity = _severity_for(rel, _symbols(json.loads(own["symbols_json"] or "[]")) if own else set(), _symbols(json.loads(row["symbols_json"] or "[]")))
                item = {
                    "path": rel,
                    "severity": severity,
                    "owner": row["session_id"],
                    "owner_agent": row["agent_kind"],
                    "owner_task": row["task_summary"],
                    "reason": "active lease by another session",
                }
                conflicts.append(item)
                if severity in {"hard", "exclusive"}:
                    _record_conflict(conn, workspace_id, rel, severity, [sid, str(row["session_id"])], "conflict_check active lease")
            if own and own["base_hash"] and snap["sha256"] and own["base_hash"] != snap["sha256"]:
                warnings.append(f"{rel}: changed since claim snapshot")
            if warn_missing_lease and not own and rel:
                warnings.append(f"{rel}: no lease held by current session; final/commit gate should verify carefully")
            _record_event(conn, workspace_id, "conflict_check", session_id=sid, path=rel, payload={"stage": stage, "conflicts": len(conflicts)})
        conn.commit()
    hard = [c for c in conflicts if c.get("severity") in {"hard", "exclusive"}]
    status = "blocked_conflict" if hard else ("warning" if conflicts or warnings else "completed")
    return {"status": status, "session_id": sid, "stage": stage, "files": rels, "conflicts": conflicts, "warnings": warnings}


def record_file_event(
    files: list[str] | tuple[Any, ...] | set[Any] | str | None,
    event_type: str = "file_changed",
    session_id: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = _workspace_root(root)
    if not _coordination_enabled(root_path):
        return {"status": "skipped", "reason": "coordination_disabled", "events": 0}
    workspace_id = _workspace_id(root_path)
    sid = session_id or _default_session_id("watcher")
    records = _norm_file_records(files, root_path)
    with _connect(root_path) as conn:
        for record in records:
            rel = str(record["path"])
            payload = dict(record)
            payload["snapshot"] = _snapshot(root_path, rel)
            _record_event(conn, workspace_id, event_type, session_id=sid, path=rel, payload=payload)
        conn.commit()
    return {"status": "completed", "session_id": sid, "events": len(records), "records": records}


def takeover_stale_claim(
    files: list[str] | tuple[str, ...] | set[str] | str | None,
    session_id: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    hb = session_heartbeat(session_id=session_id, root=root)
    if hb.get("status") == "skipped":
        return {"status": "skipped", "reason": hb.get("reason"), "session_id": hb.get("session_id"), "taken": [], "blocked": []}
    sid = hb["session_id"]
    root_path = _workspace_root(root)
    workspace_id = _workspace_id(root_path)
    rels = _norm_files(files, root_path)
    now = _now()
    taken: list[str] = []
    blocked: list[dict[str, Any]] = []
    with _connect(root_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _cleanup_stale(conn, workspace_id, now)
        for rel in rels:
            rows = list(conn.execute("SELECT * FROM file_leases WHERE workspace_id=? AND path=? AND session_id<>?", (workspace_id, rel, sid)))
            active = [row for row in rows if float(row["expires_at"]) > now]
            if active:
                blocked.extend({"path": rel, "owner": row["session_id"], "expires_at": row["expires_at"]} for row in active)
                continue
            deleted = conn.execute("DELETE FROM file_leases WHERE workspace_id=? AND path=? AND session_id<>? AND expires_at<=?", (workspace_id, rel, sid, now)).rowcount
            conn.execute("DELETE FROM symbol_leases WHERE workspace_id=? AND path=? AND session_id<>? AND expires_at<=?", (workspace_id, rel, sid, now))
            _record_event(conn, workspace_id, "takeover_stale", session_id=sid, path=rel)
            if deleted or not rows:
                taken.append(rel)
        conn.commit()
    return {"status": "blocked_active_owner" if blocked else "completed", "session_id": sid, "taken": taken, "blocked": blocked}


def coordination_status(root: str | Path | None = None, limit: int = 50) -> dict[str, Any]:
    root_path = _workspace_root(root)
    if not _coordination_enabled(root_path):
        return {"status": "skipped", "reason": "coordination_disabled", "db": str(coordination_db_path(root_path)), "sessions": [], "leases": [], "conflicts": [], "events": []}
    workspace_id = _workspace_id(root_path)
    now = _now()
    with _connect(root_path) as conn:
        stale = _cleanup_stale(conn, workspace_id, now)
        sessions = [dict(row) for row in conn.execute("SELECT session_id, agent_kind, profile, task_summary, status, heartbeat_at, worktree_root FROM sessions WHERE workspace_id=? ORDER BY heartbeat_at DESC", (workspace_id,))]
        leases = [dict(row) for row in conn.execute("SELECT path, session_id, agent_kind, task_summary, risk, base_diff_hash, claimed_at, expires_at FROM file_leases WHERE workspace_id=? AND expires_at>? ORDER BY updated_at DESC", (workspace_id, now))]
        symbol_leases = [dict(row) for row in conn.execute("SELECT path, symbol, session_id, agent_kind, expires_at FROM symbol_leases WHERE workspace_id=? AND expires_at>? ORDER BY updated_at DESC LIMIT ?", (workspace_id, now, max(1, min(int(limit or 50), 200))))]
        conflicts = [dict(row) for row in conn.execute("SELECT event_id, path, severity, status, sessions_json, reason, created_at FROM conflict_events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(int(limit or 50), 200))))]
        events = [dict(row) for row in conn.execute("SELECT event_type, session_id, path, created_at FROM coordination_events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(int(limit or 50), 200))))]
        conn.commit()
    for row in sessions:
        row["age_seconds"] = round(now - float(row.get("heartbeat_at") or 0), 2)
    for row in leases:
        row["ttl_seconds"] = round(float(row.get("expires_at") or 0) - now, 2)
    for row in symbol_leases:
        row["ttl_seconds"] = round(float(row.get("expires_at") or 0) - now, 2)
    return {"status": "completed", "workspace_id": workspace_id, "db": str(coordination_db_path(root_path)), "stale_cleaned": stale, "sessions": sessions, "leases": leases, "symbol_leases": symbol_leases, "conflicts": conflicts, "events": events}


def coordination_policy(profile: str | None = None) -> dict[str, Any]:
    root = _workspace_root()
    prof = (profile or _profile_snapshot(root).get("profile") or "off").lower()
    advisor_allowed = prof in {"review", "5", "heavy", "7", "max"}
    return {
        "status": "completed",
        "profile": prof,
        "static_coordinator": "enabled" if _coordination_enabled(root) else "disabled",
        "advisor_llm_allowed": advisor_allowed,
        "rules": {
            "docs_tests": "warning",
            "ui": "soft_block_on_overlap",
            "core_api": "block_on_overlap",
            "auth_db_config_env": "hard_block",
            "binary_office_images": "exclusive_lock",
            "watcher": "record events and run conflict_check; never claim or merge",
            "takeover": "only stale claims; never active owner without user decision",
        },
    }


def coordination_events(root: str | Path | None = None, limit: int = 100) -> dict[str, Any]:
    return coordination_status(root=root, limit=limit)


def coordination_advisor(
    files: list[str] | tuple[str, ...] | set[str] | str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    check = conflict_check(files=files, session_id=session_id, task=task, stage="advisor", root=root)
    policy = coordination_policy()
    has_conflict = bool(check.get("conflicts") or check.get("warnings"))
    if not has_conflict:
        return {
            "status": "no_conflict",
            "llm": "not_called_no_conflict",
            "conflict_check": check,
            "advice": "No active coordination conflict for the provided scope.",
        }
    if not policy.get("advisor_llm_allowed"):
        return {
            "status": "static_advice",
            "llm": "blocked_by_profile",
            "conflict_check": check,
            "advice": "Refresh changed files, wait for active owner, or takeover only if the owner is stale.",
        }
    return {
        "status": "static_advice",
        "llm": "not_called_static_first",
        "conflict_check": check,
        "advice": "Conflict detected. Prefer owner finishes first, second session refreshes diff, then reapplies non-overlapping changes.",
    }
