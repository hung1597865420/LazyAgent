"""
tools/quality.py — 12 new quality & analysis tools.

migration_validator, sql_query_analyzer, openapi_spec_sync, breaking_change_detector,
flaky_test_detector, duplicate_code_scanner, container_linter, dependency_graph_visualizer,
ci_pipeline_validator, mutation_tester, data_flow_taint_analyzer, performance_regression_detector
"""
import ast
import json
import logging
import os
import re
import sys
import tempfile
from collections import defaultdict
from typing import Optional

from config import WORKSPACE_ROOT
from agents import AgentRole
from .core import _run_cmd_safe, _llm_analyze, MAX_TOTAL_BYTES

_log = logging.getLogger("harness.quality")

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".harness_worktree", ".harness_cache", ".venv", "venv"}


def _parse_json_result(text: str, fallback: dict) -> dict:
    """Parse JSON từ LLM output một cách an toàn: thử full parse → fenced block → balanced-brace scan."""
    # 1. Full parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2. Fenced ```json block
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3. Balanced-brace scan — tìm object JSON hợp lệ đầu tiên
    start = text.find("{")
    while start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        start = text.find("{", start + 1)
    result = dict(fallback)
    result.setdefault("warnings", [])
    result["warnings"].append("parse_failed: LLM trả về output không phải JSON hợp lệ.")
    return result


def _collect_files(extensions: list[str], root: str = WORKSPACE_ROOT) -> list[str]:
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            if any(f.endswith(ext) for ext in extensions):
                results.append(os.path.join(dirpath, f))
    return results


def _read_file_safe(path: str, max_bytes: int = 50_000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except OSError:
        return ""


def _git_diff_main(cwd: str = WORKSPACE_ROOT) -> str:
    """Diff HEAD vs main/master."""
    for base in ("main", "master", "origin/main", "origin/master"):
        rc, out, _ = _run_cmd_safe(["git", "diff", f"{base}...HEAD", "--unified=3"], cwd=cwd)
        if rc == 0 and out.strip():
            return out
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 1. migration_validator
# ─────────────────────────────────────────────────────────────────────────────

async def migration_validator(paths: Optional[list[str]] = None) -> dict:
    """Kiểm tra SQL/Alembic migrations trước khi apply: lock risk, non-reversible, missing index."""
    warnings: list[str] = []

    # Thu thập migration files
    candidates = paths or []
    if not candidates:
        for ext in [".py", ".sql"]:
            for f in _collect_files([ext]):
                rel = os.path.relpath(f, WORKSPACE_ROOT)
                if any(kw in rel.lower() for kw in ("migration", "migrate", "alembic", "versions")):
                    candidates.append(f)

    if not candidates:
        return {"findings": [], "warnings": ["Không tìm thấy migration file nào."], "summary": "No migrations found."}

    ctx_parts = []
    for p in candidates[:20]:
        content = _read_file_safe(p)
        if content:
            ctx_parts.append(f"=== {os.path.relpath(p, WORKSPACE_ROOT)} ===\n{content}")

    ctx = "\n\n".join(ctx_parts)[:MAX_TOTAL_BYTES]

    prompt = """Bạn là database migration expert. Phân tích các migration files sau và tìm:
1. LOCK_RISK: ADD COLUMN NOT NULL mà không có DEFAULT trên bảng lớn, ADD CONSTRAINT, DROP INDEX dùng bởi production query
2. NON_REVERSIBLE: DROP TABLE, DROP COLUMN, thay đổi kiểu dữ liệu không tương thích ngược
3. MISSING_INDEX: Foreign key mới không có index, thêm cột thường dùng trong WHERE mà không index
4. CIRCULAR_DEP: Migration depend vào migration chưa tồn tại hoặc tạo circular dependency
5. DATA_LOSS: Truncate, xóa data mà không có backup step

Trả về JSON:
{
  "findings": [{"file": "...", "line": 0, "category": "LOCK_RISK|NON_REVERSIBLE|MISSING_INDEX|CIRCULAR_DEP|DATA_LOSS", "severity": "critical|high|medium|low", "issue": "...", "fix": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.ANALYZER)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    data.setdefault("files_checked", len(candidates))
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 2. sql_query_analyzer
# ─────────────────────────────────────────────────────────────────────────────

async def sql_query_analyzer(files: Optional[list[str]] = None) -> dict:
    """Phát hiện N+1 query, thiếu index, raw SQL không parameterized trong ORM code."""
    warnings: list[str] = []

    targets = files or _collect_files([".py"])
    ctx_parts = []
    for f in targets[:30]:
        content = _read_file_safe(f, 30_000)
        # Chỉ gửi file có ORM/SQL pattern
        if any(kw in content for kw in ("query(", ".filter(", ".all()", ".objects.", "SELECT", "execute(", "session.")):
            rel = os.path.relpath(f, WORKSPACE_ROOT)
            ctx_parts.append(f"=== {rel} ===\n{content}")

    if not ctx_parts:
        return {"findings": [], "warnings": ["Không tìm thấy ORM/SQL code."], "summary": "No ORM/SQL found."}

    ctx = "\n\n".join(ctx_parts)[:MAX_TOTAL_BYTES]

    prompt = """Bạn là database performance expert. Phân tích code và tìm:
1. N_PLUS_ONE: Loop gọi ORM query bên trong (for x in qs: x.related.all()), thiếu select_related/prefetch_related
2. MISSING_INDEX_HINT: Filter/order_by trên cột không có index (dựa trên model definition nếu thấy)
3. RAW_SQL_INJECTION: execute() với string format/concatenation thay vì parameterized query
4. UNBOUNDED_QUERY: .all() hoặc query không có LIMIT trên bảng lớn
5. INEFFICIENT_AGGREGATE: Python-level count/sum trên queryset thay vì DB aggregation

Trả về JSON:
{
  "findings": [{"file": "...", "line": 0, "category": "N_PLUS_ONE|MISSING_INDEX_HINT|RAW_SQL_INJECTION|UNBOUNDED_QUERY|INEFFICIENT_AGGREGATE", "severity": "critical|high|medium|low", "issue": "...", "fix": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.ANALYZER)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 3. openapi_spec_sync
# ─────────────────────────────────────────────────────────────────────────────

async def openapi_spec_sync(spec_path: Optional[str] = None) -> dict:
    """So sánh OpenAPI spec với actual route handlers — phát hiện drift."""
    warnings: list[str] = []

    # Tìm spec file — resolve relative path against WORKSPACE_ROOT
    spec_file = spec_path
    if spec_file and not os.path.isabs(spec_file):
        spec_file = os.path.join(WORKSPACE_ROOT, spec_file)
    if not spec_file:
        for candidate in ["openapi.yaml", "openapi.yml", "openapi.json", "api/openapi.yaml", "docs/openapi.yaml"]:
            full = os.path.join(WORKSPACE_ROOT, candidate)
            if os.path.isfile(full):
                spec_file = full
                break

    spec_content = _read_file_safe(spec_file) if spec_file else ""
    if not spec_content:
        warnings.append("Không tìm thấy OpenAPI spec file. Sẽ phân tích route handlers độc lập.")

    # Thu thập route handlers (FastAPI/Flask/Django)
    route_files = []
    for f in _collect_files([".py"]):
        content = _read_file_safe(f, 20_000)
        if any(kw in content for kw in ("@app.get", "@app.post", "@router.get", "@router.post",
                                         "@app.route", "path(", "re_path(")):
            route_files.append((os.path.relpath(f, WORKSPACE_ROOT), content))

    if not route_files:
        return {"findings": [], "warnings": warnings + ["Không tìm thấy route handler nào."], "summary": "No routes found."}

    ctx = ""
    if spec_content:
        ctx += f"=== OPENAPI SPEC ===\n{spec_content[:100_000]}\n\n"
    for rel, content in route_files[:15]:
        ctx += f"=== {rel} ===\n{content}\n\n"
    ctx = ctx[:MAX_TOTAL_BYTES]

    prompt = """Bạn là API consistency expert. So sánh OpenAPI spec với route handlers và phát hiện:
1. UNDOCUMENTED_ENDPOINT: Route tồn tại trong code nhưng không có trong spec
2. SPEC_ONLY_ENDPOINT: Endpoint trong spec nhưng không có route handler
3. SCHEMA_MISMATCH: Request body / response fields không khớp giữa spec và Pydantic model
4. TYPE_MISMATCH: Kiểu dữ liệu khác nhau (string trong spec vs int trong model)
5. MISSING_ERROR_RESPONSE: Route có thể raise HTTPException nhưng spec không document error code

Nếu không có spec, chỉ list các endpoint tìm được và cảnh báo thiếu spec.

Trả về JSON:
{
  "findings": [{"endpoint": "...", "category": "...", "severity": "high|medium|low", "issue": "...", "fix": "..."}],
  "endpoints_found": [...],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.ANALYZER)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 4. breaking_change_detector
# ─────────────────────────────────────────────────────────────────────────────

async def breaking_change_detector(base_ref: str = "") -> dict:
    """Phát hiện breaking changes giữa HEAD và base branch: rename param, xóa field, đổi status code."""
    warnings: list[str] = []

    # Validate base_ref để tránh git option injection
    if base_ref and (base_ref.startswith("-") or not re.match(r'^[\w./~^@{}-]+$', base_ref)):
        warnings.append(f"base_ref '{base_ref}' không hợp lệ, bỏ qua.")
        base_ref = ""

    diff = ""
    if base_ref:
        rc_v, _, _ = _run_cmd_safe(["git", "rev-parse", "--verify", base_ref], cwd=WORKSPACE_ROOT)
        if rc_v != 0:
            return {"error": "invalid_base_ref", "base_ref": base_ref,
                    "findings": [], "warnings": [f"base_ref '{base_ref}' không tồn tại hoặc không hợp lệ."],
                    "verdict": "error"}
        _, diff, _ = _run_cmd_safe(["git", "diff", f"{base_ref}...HEAD", "--unified=3"], cwd=WORKSPACE_ROOT)
    if not diff:
        diff = _git_diff_main()
    if not diff:
        return {"findings": [], "warnings": ["Không có diff nào giữa HEAD và main/master."], "verdict": "no_changes"}

    prompt = """Bạn là API compatibility expert. Phân tích git diff và phân loại từng thay đổi:

BREAKING (major bump, cần deprecation notice):
- Xóa/rename public function/method/class
- Xóa/rename field trong request body hoặc response schema
- Thay đổi kiểu dữ liệu của field (string → int)
- Thay đổi HTTP status code của response thành công
- Thêm required parameter mới
- Thay đổi URL path của endpoint

DEPRECATED (cần thông báo trong changelog):
- Đổi tên parameter nhưng vẫn giữ backward-compat alias
- Thay default value của optional parameter

ADDITIVE (an toàn, minor/patch bump):
- Thêm optional field mới trong response
- Thêm optional parameter có default
- Thêm endpoint mới

Trả về JSON:
{
  "verdict": "breaking|deprecated|additive|no_public_api_change",
  "semver_bump": "major|minor|patch",
  "findings": [{"category": "BREAKING|DEPRECATED|ADDITIVE", "description": "...", "location": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, diff[:MAX_TOTAL_BYTES], AgentRole.ANALYZER)
    data = _parse_json_result(result, {"verdict": "unknown", "findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 5. flaky_test_detector
# ─────────────────────────────────────────────────────────────────────────────

async def flaky_test_detector(runs: int = 3, test_path: str = "") -> dict:
    """Chạy test suite N lần, báo cáo non-deterministic failures."""
    warnings: list[str] = []

    if runs < 2:
        runs = 2
    if runs > 5:
        runs = 5

    cmd_base = [sys.executable, "-m", "pytest", "--tb=no", "-q"]
    if test_path:
        cmd_base.append(test_path)

    results_per_run: list[dict] = []
    for i in range(runs):
        rc, out, err = _run_cmd_safe(cmd_base, timeout=120.0)
        # Parse passed/failed từ pytest output
        passed = failed = 0
        failed_tests: list[str] = []
        for line in (out + err).splitlines():
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
            # Collect individual failed test names — capture full nodeid incl. [param] before " - "
            m_fail = re.match(r"^FAILED\s+(.+?)(?:\s+-\s+.*)?$", line.strip(), re.IGNORECASE)
            if m_fail:
                failed_tests.append(m_fail.group(1).strip())
        results_per_run.append({"run": i + 1, "passed": passed, "failed": failed, "failed_tests": failed_tests})

    if not any(r["passed"] + r["failed"] > 0 for r in results_per_run):
        return {"findings": [], "warnings": warnings + ["pytest không chạy được hoặc không có test nào."], "runs": results_per_run}

    # Tìm test nào inconsistent
    all_failed: dict[str, int] = defaultdict(int)
    for r in results_per_run:
        for t in r["failed_tests"]:
            all_failed[t] += 1

    flaky = []
    for test, fail_count in all_failed.items():
        if 0 < fail_count < runs:
            flaky.append({"test": test, "fail_count": fail_count, "runs": runs, "status": "flaky"})
        elif fail_count == runs:
            flaky.append({"test": test, "fail_count": fail_count, "runs": runs, "status": "consistently_failing"})

    # LLM phân tích test code nếu có flaky
    llm_analysis = ""
    if flaky:
        import fnmatch as _fnmatch
        _all_py = _collect_files([".py"])
        test_files = [f for f in _all_py
                      if _fnmatch.fnmatch(os.path.basename(f), "test_*.py")
                      or _fnmatch.fnmatch(os.path.basename(f), "*_test.py")]
        ctx_parts = []
        for f in test_files[:10]:
            ctx_parts.append(f"=== {os.path.relpath(f, WORKSPACE_ROOT)} ===\n{_read_file_safe(f, 20_000)}")
        if ctx_parts:
            ctx = "\n\n".join(ctx_parts)[:150_000]
            llm_analysis = await _llm_analyze(
                f"Các test sau bị flaky: {[f['test'] for f in flaky]}. "
                "Tìm nguyên nhân: time.sleep hardcode, shared global state, random không seed, "
                "external network call, file system state, ordering dependency. "
                "Trả về list nguyên nhân và fix gợi ý dạng text ngắn.",
                ctx, AgentRole.TESTER
            )

    return {
        "flaky_tests": flaky,
        "consistently_failing": [f for f in flaky if f["status"] == "consistently_failing"],
        "runs_detail": results_per_run,
        "analysis": llm_analysis,
        "warnings": warnings,
        "summary": f"Ran {runs}x: {len([f for f in flaky if f['status']=='flaky'])} flaky, "
                   f"{len([f for f in flaky if f['status']=='consistently_failing'])} always-fail"
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. duplicate_code_scanner
# ─────────────────────────────────────────────────────────────────────────────

async def duplicate_code_scanner(min_lines: int = 6, threshold: float = 0.8) -> dict:
    """Tìm structural clone / copy-paste code bằng AST normalization."""
    warnings: list[str] = []

    py_files = _collect_files([".py"])
    if not py_files:
        return {"clones": [], "warnings": ["Không tìm thấy Python file nào."], "summary": "No files."}

    # Extract function bodies as normalized token sequences
    functions: list[dict] = []
    for filepath in py_files[:100]:
        content = _read_file_safe(filepath)
        if not content:
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        lines = content.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = node.end_lineno if hasattr(node, "end_lineno") else start + 10
                body_lines = lines[start:end]
                if len(body_lines) < min_lines:
                    continue
                # Normalize: strip comments, normalize variable names via ast.dump
                try:
                    normalized = ast.dump(node)
                except Exception:
                    normalized = "\n".join(body_lines)
                functions.append({
                    "file": os.path.relpath(filepath, WORKSPACE_ROOT),
                    "name": node.name,
                    "line": node.lineno,
                    "lines": len(body_lines),
                    "normalized": normalized,
                })

    # Simple similarity: compare normalized dumps via character-level Jaccard
    def _jaccard(a: str, b: str) -> float:
        sa, sb = set(a.split()), set(b.split())
        if not sa and not sb:
            return 1.0
        return len(sa & sb) / len(sa | sb)

    clones: list[dict] = []
    seen_pairs: set[tuple] = set()
    for i in range(len(functions)):
        for j in range(i + 1, len(functions)):
            fi, fj = functions[i], functions[j]
            if fi["file"] == fj["file"] and fi["name"] == fj["name"]:
                continue
            pair_key = (fi["file"], fi["line"], fj["file"], fj["line"])
            if pair_key in seen_pairs:
                continue
            sim = _jaccard(fi["normalized"], fj["normalized"])
            if sim >= threshold:
                seen_pairs.add(pair_key)
                clones.append({
                    "similarity": round(sim, 2),
                    "func_a": {"file": fi["file"], "name": fi["name"], "line": fi["line"], "lines": fi["lines"]},
                    "func_b": {"file": fj["file"], "name": fj["name"], "line": fj["line"], "lines": fj["lines"]},
                    "suggestion": f"Xem xét extract thành hàm dùng chung (similarity {sim:.0%})"
                })

    clones.sort(key=lambda x: -x["similarity"])
    clones = clones[:50]

    return {
        "clones": clones,
        "functions_analyzed": len(functions),
        "files_analyzed": len(py_files),
        "warnings": warnings,
        "summary": f"{len(clones)} cặp clone tìm thấy từ {len(functions)} functions trong {len(py_files)} files"
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. container_linter
# ─────────────────────────────────────────────────────────────────────────────

async def container_linter(paths: Optional[list[str]] = None) -> dict:
    """Lint Dockerfile và docker-compose files: security, size, best practices."""
    warnings: list[str] = []

    targets = paths or []
    if not targets:
        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for f in files:
                if f in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml") or \
                   f.startswith("Dockerfile.") or f.endswith(".dockerfile"):
                    targets.append(os.path.join(root, f))

    if not targets:
        return {"findings": [], "warnings": ["Không tìm thấy Dockerfile hoặc docker-compose file."], "summary": "No container files found."}

    ctx_parts = []
    for p in targets[:10]:
        content = _read_file_safe(p)
        if content:
            ctx_parts.append(f"=== {os.path.relpath(p, WORKSPACE_ROOT)} ===\n{content}")

    ctx = "\n\n".join(ctx_parts)[:MAX_TOTAL_BYTES]

    prompt = """Bạn là container security và best practices expert. Phân tích Dockerfile/docker-compose và flag:

SECURITY (critical/high):
- USER root hoặc không có USER instruction → process chạy as root
- Secret/password/token hardcode trong ENV, ARG, hay RUN command
- COPY . . không có .dockerignore → copy .env, credentials, git history vào image
- ADD từ URL (tải không verify checksum)

BEST_PRACTICES (medium):
- Không pin image version (FROM python:latest thay vì python:3.12-slim)
- Nhiều RUN riêng lẻ thay vì chain (tạo nhiều layer)
- Không có HEALTHCHECK instruction
- apt-get install mà không có --no-install-recommends
- Không dọn cache sau apt/pip install

SIZE (low):
- COPY toàn bộ source trước khi install dependencies (phá cache)
- Không dùng multi-stage build cho binary

Trả về JSON:
{
  "findings": [{"file": "...", "line": 0, "category": "SECURITY|BEST_PRACTICES|SIZE", "severity": "critical|high|medium|low", "issue": "...", "fix": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.SECURITY)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    data.setdefault("files_checked", targets)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 8. dependency_graph_visualizer
# ─────────────────────────────────────────────────────────────────────────────

async def dependency_graph_visualizer(paths: Optional[list[str]] = None) -> dict:
    """Phân tích import graph Python: circular import, God module, high coupling."""
    warnings: list[str] = []

    py_files = paths or _collect_files([".py"])
    if not py_files:
        return {"graph": {}, "cycles": [], "warnings": ["Không tìm thấy Python file nào."], "summary": "No files."}

    # Build import graph
    graph: dict[str, list[str]] = {}
    for filepath in py_files[:200]:
        content = _read_file_safe(filepath)
        if not content:
            continue
        rel = os.path.relpath(filepath, WORKSPACE_ROOT).replace(os.sep, ".").removesuffix(".py")
        imports: list[str] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
        except SyntaxError:
            pass
        graph[rel] = imports

    # Detect cycles via DFS
    def _find_cycles(g: dict) -> list[list[str]]:
        visited: set = set()
        rec_stack: set = set()
        cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in g.get(node, []):
                # only track internal modules
                neighbor_key = None
                for key in g:
                    if key.endswith(neighbor) or neighbor.endswith(key.split(".")[-1]):
                        neighbor_key = key
                        break
                if neighbor_key is None:
                    continue
                if neighbor_key not in visited:
                    dfs(neighbor_key, path + [neighbor_key])
                elif neighbor_key in rec_stack:
                    cycle_start = path.index(neighbor_key) if neighbor_key in path else 0
                    cycles.append(path[cycle_start:] + [neighbor_key])

        for node in list(g.keys()):
            if node not in visited:
                dfs(node, [node])
        return cycles[:20]

    cycles = _find_cycles(graph)

    # Fan-in / fan-out metrics
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)
    for mod, imports in graph.items():
        internal = [i for i in imports if any(i.startswith(k.split(".")[0]) for k in graph)]
        fan_out[mod] = len(internal)
        for i in internal:
            for key in graph:
                if key.endswith(i) or i.endswith(key.split(".")[-1]):
                    fan_in[key] += 1

    god_modules = [m for m, fi in fan_in.items() if fi >= 10]
    high_coupling = sorted(fan_out.items(), key=lambda x: -x[1])[:10]

    # Text adjacency summary (không gửi raw graph vì quá lớn)
    summary_lines = [f"Modules analyzed: {len(graph)}"]
    if cycles:
        summary_lines.append(f"Circular imports: {len(cycles)}")
    if god_modules:
        summary_lines.append(f"God modules (fan-in ≥10): {', '.join(god_modules[:5])}")

    return {
        "cycles": cycles,
        "god_modules": god_modules,
        "high_coupling_modules": [{"module": m, "imports": n} for m, n in high_coupling],
        "metrics": {
            "total_modules": len(graph),
            "total_cycles": len(cycles),
            "total_god_modules": len(god_modules),
        },
        "warnings": warnings,
        "summary": " | ".join(summary_lines)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. ci_pipeline_validator
# ─────────────────────────────────────────────────────────────────────────────

async def ci_pipeline_validator(paths: Optional[list[str]] = None) -> dict:
    """Validate GitHub Actions / GitLab CI YAML: secret exposure, wrong triggers, deprecated actions."""
    warnings: list[str] = []

    targets = paths or []
    if not targets:
        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for f in files:
                if f.endswith((".yml", ".yaml")):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, WORKSPACE_ROOT)
                    if ".github/workflows" in rel or ".gitlab-ci" in rel or "ci" in rel.lower():
                        targets.append(full)

    if not targets:
        return {"findings": [], "warnings": ["Không tìm thấy CI workflow file nào (.github/workflows/, .gitlab-ci.yml)."], "summary": "No CI files found."}

    ctx_parts = []
    for p in targets[:10]:
        content = _read_file_safe(p)
        if content:
            ctx_parts.append(f"=== {os.path.relpath(p, WORKSPACE_ROOT)} ===\n{content}")

    ctx = "\n\n".join(ctx_parts)[:MAX_TOTAL_BYTES]

    prompt = """Bạn là CI/CD security và reliability expert. Phân tích workflow YAML và flag:

SECURITY (critical/high):
- Secret hardcode trong env: hoặc value: (thay vì ${{ secrets.X }})
- Untrusted input trong run: command (pull_request title/body → shell injection)
- actions/checkout với persist-credentials: true không cần thiết
- Permissions quá rộng (permissions: write-all)

RELIABILITY (high/medium):
- Job không có timeout-minutes → có thể chạy vô tận
- Hardcode branch name "main"/"master" thay vì ${{ github.event.repository.default_branch }}
- Cache không có restore-keys fallback
- Missing continue-on-error cho non-critical steps

PERFORMANCE (medium/low):
- Job không cache dependencies (pip/npm/go) → reinstall mỗi lần
- Matrix strategy chạy quá nhiều combination không cần thiết
- Không dùng concurrency group để cancel outdated runs

MAINTENANCE (low):
- Deprecated actions (actions/checkout@v1, actions/setup-python@v2 thay vì v4)
- Pinned SHA thay vì version tag (khó update)

Trả về JSON:
{
  "findings": [{"file": "...", "line": 0, "category": "SECURITY|RELIABILITY|PERFORMANCE|MAINTENANCE", "severity": "critical|high|medium|low", "issue": "...", "fix": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.SECURITY)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 10. mutation_tester
# ─────────────────────────────────────────────────────────────────────────────

async def mutation_tester(files: Optional[list[str]] = None, max_mutations: int = 20) -> dict:
    """Inject mutations vào code, chạy tests, báo cáo mutation score."""
    warnings: list[str] = []

    targets = files or _collect_files([".py"])
    # Chỉ lấy non-test files có logic
    def _safe_size(p: str) -> int:
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    src_files = [f for f in targets if "test" not in os.path.basename(f).lower()
                 and _safe_size(f) > 100][:5]

    if not src_files:
        return {"score": None, "warnings": warnings + ["Không tìm thấy source file để mutate."], "summary": "No files."}

    # Tạo mutations đơn giản qua AST
    MUTATIONS = [
        (r"\bTrue\b", "False"), (r"\bFalse\b", "True"),
        (r"\bif\s+not\s+", "if "), (r"\bif\s+(?!not)", "if not "),
        (r"\breturn\s+True\b", "return False"), (r"\breturn\s+False\b", "return True"),
        (r"\band\b", "or"), (r"\bor\b", "and"),
        (r">=", ">"), (r"<=", "<"), (r"==", "!="),
        (r"\+\s*1\b", "- 1"), (r"-\s*1\b", "+ 1"),
    ]

    killed = survived = 0
    survived_details: list[dict] = []

    for src_file in src_files:
        original = _read_file_safe(src_file)
        if not original:
            continue

        mutation_count = 0
        for pattern, replacement in MUTATIONS:
            if mutation_count >= max_mutations:
                break
            if not re.search(pattern, original):
                continue

            mutated = re.sub(pattern, replacement, original, count=1)
            if mutated == original:
                continue

            # Apply mutation to temp file
            tmp_path = None
            backup = src_file + ".orig_mut_bak"
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", dir=os.path.dirname(src_file),
                    prefix=f"_mut_{os.path.basename(src_file)}_", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp_path = tmp.name
                    tmp.write(mutated)

                # Rename: backup original, put mutation in place
                os.rename(src_file, backup)
                os.rename(tmp_path, src_file)
                tmp_path = None  # consumed by rename — no longer needs cleanup

                rc, out, err = _run_cmd_safe(
                    [sys.executable, "-m", "pytest", "--tb=no", "-q", "--timeout=30"],
                    timeout=60.0
                )
                test_failed = rc != 0 or "failed" in out.lower()

                if test_failed:
                    killed += 1
                else:
                    survived += 1
                    survived_details.append({
                        "file": os.path.relpath(src_file, WORKSPACE_ROOT),
                        "mutation": f"{pattern} → {replacement}",
                        "verdict": "survived",
                        "note": "Test không detect được mutation này — có thể thiếu assertion"
                    })
            except Exception as e:
                warnings.append(f"Mutation error on {src_file}: {e}")
            finally:
                # Restore original (independent of tmp cleanup)
                if os.path.isfile(backup):
                    if os.path.isfile(src_file):
                        try:
                            os.remove(src_file)
                        except OSError:
                            pass
                    try:
                        os.rename(backup, src_file)
                    except OSError:
                        pass
                # Clean up temp file only if it wasn't consumed by rename
                if tmp_path and os.path.isfile(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            mutation_count += 1

    total = killed + survived
    score = round(killed / total * 100, 1) if total > 0 else None

    return {
        "mutation_score": score,
        "killed": killed,
        "survived": survived,
        "total_mutations": total,
        "survived_mutations": survived_details[:20],
        "warnings": warnings,
        "summary": f"Mutation score: {score}% ({killed}/{total} killed). "
                   f"{'Tốt.' if score and score >= 70 else 'Cần thêm assertion trong tests.'}"
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. data_flow_taint_analyzer
# ─────────────────────────────────────────────────────────────────────────────

async def data_flow_taint_analyzer(files: Optional[list[str]] = None) -> dict:
    """Track untrusted user input → database/shell/template sinks để phát hiện injection paths."""
    warnings: list[str] = []

    targets = files or _collect_files([".py"])
    ctx_parts = []
    for f in targets[:30]:
        content = _read_file_safe(f, 25_000)
        # Chỉ gửi file có sources hoặc sinks
        sources = ["request.args", "request.json", "request.form", "request.data",
                   "request.get_json", "Body(", "Query(", "Path(", "Form("]
        sinks = ["execute(", "query(", "subprocess", "os.system", "eval(", "exec(",
                 "render_template", "Markup(", "format_map", "cursor.execute"]
        if any(kw in content for kw in sources + sinks):
            rel = os.path.relpath(f, WORKSPACE_ROOT)
            ctx_parts.append(f"=== {rel} ===\n{content}")

    if not ctx_parts:
        return {"findings": [], "warnings": ["Không tìm thấy code có user input sources hoặc dangerous sinks."], "summary": "No taint paths found."}

    ctx = "\n\n".join(ctx_parts)[:MAX_TOTAL_BYTES]

    prompt = """Bạn là application security expert chuyên về taint analysis. Trace data flow từ untrusted sources đến dangerous sinks:

SOURCES (user-controlled input):
- request.args, request.json, request.form, request.data (Flask)
- Body(), Query(), Path(), Form() parameters (FastAPI)
- WebSocket data, uploaded file names

SINKS (dangerous operations):
- SQL: execute(), cursor.execute(), raw SQL string formatting
- Shell: subprocess.run/Popen với shell=True, os.system, eval(), exec()
- Template: render_template với unescaped var, Markup(), jinja2 với autoescape=False
- Path: open() với user-controlled filename, os.path.join với untrusted component

Phân tích từng path và đánh giá:
1. SQL_INJECTION: source → SQL sink mà không qua parameterized query
2. COMMAND_INJECTION: source → shell sink mà không sanitize
3. TEMPLATE_INJECTION: source → template sink mà không escape
4. PATH_TRAVERSAL: source → file path sink mà không validate

Trả về JSON:
{
  "findings": [{"file": "...", "line": 0, "category": "SQL_INJECTION|COMMAND_INJECTION|TEMPLATE_INJECTION|PATH_TRAVERSAL", "severity": "critical|high|medium", "source": "...", "sink": "...", "path": "brief trace", "fix": "..."}],
  "summary": "..."
}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.SECURITY)
    data = _parse_json_result(result, {"findings": [], "summary": ""})

    data.setdefault("warnings", warnings)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 12. performance_regression_detector
# ─────────────────────────────────────────────────────────────────────────────

async def performance_regression_detector(
    functions: Optional[list[str]] = None,
    threshold_pct: float = 20.0,
) -> dict:
    """Benchmark HEAD vs main branch cho critical functions, báo regression nếu >threshold%."""
    warnings: list[str] = []

    # Lấy diff để biết function nào thay đổi
    diff = _git_diff_main()
    if not diff:
        return {"regressions": [], "warnings": ["Không có diff với main — không có gì để so sánh."], "summary": "No diff."}

    # Tìm function names trong diff
    changed_funcs: list[str] = []
    if functions:
        changed_funcs = functions
    else:
        for line in diff.splitlines():
            m = re.search(r"^\+\+\+.*?([a-z_]+\.py)", line)
            if m:
                continue
            m = re.search(r"^[+-]\s*def\s+(\w+)\s*\(", line)
            if m:
                fn = m.group(1)
                if fn not in changed_funcs and not fn.startswith("test_"):
                    changed_funcs.append(fn)

    if not changed_funcs:
        return {"regressions": [], "warnings": ["Không tìm thấy function nào thay đổi trong diff."], "summary": "No changed functions."}

    # Collect current performance by running profiler on test that exercises these functions
    py_files = _collect_files([".py"])
    test_snippets = []
    for f in py_files:
        content = _read_file_safe(f, 20_000)
        for fn in changed_funcs:
            if fn in content:
                rel = os.path.relpath(f, WORKSPACE_ROOT)
                test_snippets.append(f"=== {rel} uses {fn} ===\n{content[:5000]}")
                break

    ctx = f"Git diff HEAD vs main:\n{diff[:50_000]}\n\n"
    ctx += "Files using changed functions:\n" + "\n".join(test_snippets[:5])[:100_000]

    prompt = f"""Bạn là performance engineer. Phân tích git diff và các file liên quan:

Functions thay đổi: {changed_funcs}
Threshold regression: {threshold_pct}%
Tìm:
1. ALGORITHMIC_REGRESSION: Thay đổi O(n) → O(n²), thêm nested loop, thêm DB call trong loop
2. MEMORY_REGRESSION: Thêm unbounded list/dict accumulation, load toàn bộ dataset vào memory
3. IO_REGRESSION: Thêm synchronous IO trong async path, tăng số lượng external calls
4. CACHE_INVALIDATION: Xóa/bypass cache layer mà không có justification

Với mỗi regression, estimate mức độ chậm hơn (ví dụ: "có thể chậm 2-5x với input lớn").

Trả về JSON:
{{
  "regressions": [{{"function": "...", "file": "...", "category": "ALGORITHMIC_REGRESSION|MEMORY_REGRESSION|IO_REGRESSION|CACHE_INVALIDATION", "severity": "critical|high|medium|low", "description": "...", "estimated_slowdown": "...", "fix": "..."}}],
  "functions_analyzed": [...],
  "summary": "..."
}}"""

    result = await _llm_analyze(prompt, ctx, AgentRole.SCANNER)
    data = _parse_json_result(result, {"regressions": [], "summary": ""})

    data.setdefault("warnings", warnings)
    data.setdefault("changed_functions", changed_funcs)
    return data
