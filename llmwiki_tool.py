import os
import re
import shutil
import json
import unicodedata
from pathlib import Path
from config import WORKSPACE_ROOT as CONFIG_WORKSPACE_ROOT, get_azure_client
from agents import Agent, AgentRole

# Global wiki — path tĩnh, không đổi theo project
GLOBAL_WIKI_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "llmwiki")
GLOBAL_RAW_DIR = os.path.join(GLOBAL_WIKI_ROOT, "raw")
GLOBAL_WIKI_DIR = os.path.join(GLOBAL_WIKI_ROOT, "wiki")
BOOTSTRAP_MARKER = ".bootstrapped"
SEED_DOC_DIRS = ("docs", "doc", "specs", "spec", "adr", "architecture")
SKIP_SEED_PARTS = {
    ".git", ".hg", ".svn", ".Codex", ".claude", "llmwiki", "node_modules",
    "venv", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
}
MAX_SEED_DOCS = 80
MAX_SEED_DOC_BYTES = 500_000
MAX_SEED_TOTAL_BYTES = 5_000_000
SENSITIVE_DOC_PATTERNS = (
    "-----BEGIN PRIVATE KEY-----",
    "AZURE_OPENAI_API_KEY=",
    "OPENAI_API_KEY=",
    "ANTHROPIC_API_KEY=",
    "GITHUB_TOKEN=",
    "Authorization: Bearer ",
    "password=",
)
SENSITIVE_DOC_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|authorization)\b\s*[:=]\s*[^\s`'\"]{12,}"
)


def _local_wiki_dirs() -> tuple[str, str]:
    """Trả về (raw_dir, wiki_dir) của local wiki theo project đang active.

    Đọc runtime thay vì module-level constant để tránh bị freeze khi MCP
    process reuse qua nhiều project (--scope user).
    """
    # CLAUDE_PROJECT_DIR được Claude Code inject vào env MCP server mỗi session
    workspace = os.getenv("WORKSPACE_ROOT") or os.getenv("CLAUDE_PROJECT_DIR") or CONFIG_WORKSPACE_ROOT
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = json.loads(meta).get("tool", {}).get("workspacePath")
            except Exception:
                workspace = None
    if not workspace:
        raise RuntimeError("Không xác định được workspace active để bootstrap local llmwiki")
    wiki_root = os.path.join(workspace, "llmwiki")
    return os.path.join(wiki_root, "raw"), os.path.join(wiki_root, "wiki")


def _pending_raw_files(raw_dir: str) -> list[str]:
    if not os.path.isdir(raw_dir):
        return []
    pending = []
    for root, dir_names, file_names in os.walk(raw_dir):
        dir_names[:] = [d for d in dir_names if d != "processed" and not d.startswith(".")]
        for file_name in file_names:
            if file_name.endswith(".processing") or not file_name.endswith((".md", ".txt")):
                continue
            pending.append(os.path.relpath(os.path.join(root, file_name), raw_dir))
    return pending


def _wiki_has_pages(wiki_dir: str) -> bool:
    for sub in ("concepts", "entities", "sources"):
        subdir = os.path.join(wiki_dir, sub)
        if os.path.isdir(subdir) and any(name.endswith(".md") for name in os.listdir(subdir)):
            return True
    return False


def _safe_seed_doc(path: Path, workspace: Path) -> bool:
    try:
        rel = path.relative_to(workspace)
        stat = path.stat()
    except OSError:
        return False
    if set(rel.parts) & SKIP_SEED_PARTS:
        return False
    name = path.name.lower()
    if not (
        path.is_file()
        and path.suffix.lower() in {".md", ".txt"}
        and not name.startswith(".env")
        and not name.endswith(".processing")
        and stat.st_size <= MAX_SEED_DOC_BYTES
    ):
        return False
    try:
        sample = path.read_text(encoding="utf-8", errors="ignore")[:MAX_SEED_DOC_BYTES]
    except OSError:
        return False
    normalized = unicodedata.normalize("NFKC", sample)
    normalized = re.sub(r"[\u200b-\u200f\ufeff]", "", normalized)
    return not any(pattern in normalized for pattern in SENSITIVE_DOC_PATTERNS) and not SENSITIVE_DOC_RE.search(normalized)


def _seed_docs(workspace: Path) -> list[Path]:
    docs: list[Path] = []
    for path in sorted(workspace.glob("*.md")):
        if _safe_seed_doc(path, workspace):
            docs.append(path)
    for dirname in SEED_DOC_DIRS:
        base = workspace / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if _safe_seed_doc(path, workspace):
                docs.append(path)
            if len(docs) >= MAX_SEED_DOCS:
                return docs
    return docs[:MAX_SEED_DOCS]


def ensure_local_wiki_bootstrap() -> bool:
    """Create project wiki dirs and seed raw docs once for new projects."""
    raw_dir, wiki_dir = _local_wiki_dirs()
    raw_path = Path(raw_dir)
    wiki_path = Path(wiki_dir)
    marker = raw_path / BOOTSTRAP_MARKER

    raw_path.mkdir(parents=True, exist_ok=True)
    (raw_path / "processed").mkdir(parents=True, exist_ok=True)
    for sub in ("concepts", "entities", "sources"):
        (wiki_path / sub).mkdir(parents=True, exist_ok=True)

    pending = _pending_raw_files(raw_dir)
    if marker.exists() or pending or _wiki_has_pages(wiki_dir):
        marker.touch(exist_ok=True)
        return bool(pending)

    workspace = raw_path.parent.parent
    total_bytes = 0
    for doc in _seed_docs(workspace):
        try:
            total_bytes += doc.stat().st_size
        except OSError:
            continue
        if total_bytes > MAX_SEED_TOTAL_BYTES:
            break
        rel = doc.relative_to(workspace)
        target = raw_path / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(doc, target)

    marker.touch(exist_ok=True)
    return bool(_pending_raw_files(raw_dir))


def wiki_pending_targets() -> list[str]:
    targets = []
    try:
        local_raw, _ = _local_wiki_dirs()
        ensure_local_wiki_bootstrap()
        if _pending_raw_files(local_raw):
            targets.append("local")
    except Exception:
        pass
    if _pending_raw_files(GLOBAL_RAW_DIR):
        targets.append("global")
    return targets


WIKI_INGEST_PROMPT = """Bạn là Wiki Ingestion Agent.
Nhiệm vụ của bạn là đọc nội dung tài liệu thô (raw document) và trích xuất thành các trang khái niệm (concepts) và thực thể (entities) theo định dạng Markdown có Front Matter.

1. **Concepts (Khái niệm/Quy tắc/Quyết định kiến trúc)**:
   - Các mẫu thiết kế (design patterns), quy định code, cách sửa lỗi chuẩn, hoặc quyết định kiến trúc dự án.
   - Mỗi concept viết vào một trang riêng.
   - Định dạng Front Matter:
     ---
     title: Tên Khái Niệm
     type: concept
     related: [[tên-khái-niệm-khác]] hoặc [[tên-thực-thể]]
     ---
     Nội dung chi tiết khái niệm, quy tắc, lý do, và ví dụ minh họa (nếu có).

2. **Entities (Thực thể/Schema/API Contract)**:
   - Các cấu trúc dữ liệu, schema database, hoặc API contracts của dự án.
   - Mỗi thực thể viết vào một trang riêng.
   - Định dạng Front Matter:
     ---
     title: Tên Thực Thể
     type: entity
     related: [[khái-niệm-liên-quan]]
     ---
     Nội dung chi tiết cấu trúc, trường dữ liệu, kiểu dữ liệu, API path, v.v.

Hãy phân tích tài liệu sau và trả về một JSON chứa danh sách các concepts và entities cần tạo:
{
  "concepts": [
    {"filename": "ten_file.md", "title": "Tiêu đề", "content": "Nội dung Markdown nguyên bản (bao gồm cả Front Matter)"}
  ],
  "entities": [
    {"filename": "ten_file.md", "title": "Tiêu đề", "content": "Nội dung Markdown nguyên bản (bao gồm cả Front Matter)"}
  ]
}
Trả về JSON thuần túy, không có markdown fence."""

async def wiki_ingest(target: str = "local") -> dict:
    """Ingest raw docs. target='local' (default) or 'global' (~/.claude/llmwiki/)."""
    if target == "global":
        raw_dir = GLOBAL_RAW_DIR
        wiki_dir = GLOBAL_WIKI_DIR
    else:
        ensure_local_wiki_bootstrap()
        raw_dir, wiki_dir = _local_wiki_dirs()

    processed_dir = os.path.join(raw_dir, "processed")
    concepts_dir = os.path.join(wiki_dir, "concepts")
    entities_dir = os.path.join(wiki_dir, "entities")
    sources_dir = os.path.join(wiki_dir, "sources")

    if not os.path.isdir(raw_dir):
        return {"error": f"Thư mục raw không tồn tại tại {raw_dir}", "processed": []}

    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(concepts_dir, exist_ok=True)
    os.makedirs(entities_dir, exist_ok=True)
    os.makedirs(sources_dir, exist_ok=True)

    raw_files = _pending_raw_files(raw_dir)
    
    if not raw_files:
        return {"message": "Không có tài liệu thô mới nào cần ingest", "processed": []}
        
    processed_count = 0
    details = []
    
    client = get_azure_client()
    agent = Agent(AgentRole.WORKER, client=client, system_prompt=WIKI_INGEST_PROMPT)
    
    for fname in raw_files:
        fpath = os.path.join(raw_dir, fname)
        claim_path = fpath + ".processing"
        def _release_claim() -> None:
            if os.path.exists(claim_path) and not os.path.exists(fpath):
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                os.rename(claim_path, fpath)

        try:
            # Atomic claim: rename → only one worker processes each file
            os.rename(fpath, claim_path)
        except OSError:
            details.append({"file": fname, "status": "skipped", "error": "Already claimed by another worker"})
            continue
        try:
            with open(claim_path, "r", encoding="utf-8") as f:
                content = f.read()

            task = f"Trích xuất các khái niệm và thực thể từ tài liệu này:\n\nTên file: {fname}\nNội dung:\n{content}"
            res = await agent.run_async(task, json_mode=True)

            if res.status != "success":
                details.append({"file": fname, "status": "error", "error": res.error})
                _release_claim()
                continue

            data = {}
            try:
                from support_tools import _parse_json_object
                data = _parse_json_object(res.result)
            except Exception as e:
                details.append({"file": fname, "status": "error", "error": f"Lỗi parse JSON: {e}"})
                _release_claim()
                continue

            concepts_created = []
            entities_created = []

            def _safe_write(base_dir: str, filename: str, content: str) -> str | None:
                """Write file, reject path traversal. Returns basename or None if rejected."""
                if not filename:
                    return None
                if not filename.endswith(".md"):
                    filename += ".md"
                # Resolve and verify stays inside base_dir
                target = os.path.realpath(os.path.join(base_dir, os.path.basename(filename)))
                if not target.startswith(os.path.realpath(base_dir) + os.sep):
                    return None
                with open(target, "w", encoding="utf-8") as f_out:
                    f_out.write(content)
                return os.path.basename(target)

            for c in data.get("concepts", []):
                n = _safe_write(concepts_dir, c.get("filename", ""), c.get("content", ""))
                if n:
                    concepts_created.append(n)

            for e in data.get("entities", []):
                n = _safe_write(entities_dir, e.get("filename", ""), e.get("content", ""))
                if n:
                    entities_created.append(n)

            source_stem = Path(fname).with_suffix("").as_posix().replace("/", "_").replace("\\", "_")
            sname = source_stem + ".md"
            spath = os.path.join(sources_dir, os.path.basename(sname))
            source_content = f"""---
title: Source Page for {fname}
type: source
source: raw/{fname}
---

Tài liệu thô đã được xử lý thành công thành các khái niệm và thực thể.
concepts: {concepts_created}
entities: {entities_created}
"""
            with open(spath, "w", encoding="utf-8") as f_out:
                f_out.write(source_content)

            dest = os.path.join(processed_dir, fname)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(claim_path, dest)
            
            processed_count += 1
            details.append({
                "file": fname,
                "status": "success",
                "concepts": concepts_created,
                "entities": entities_created
            })
            
        except Exception as e:
            details.append({"file": fname, "status": "error", "error": str(e)})
            _release_claim()
            
    return {"message": f"Đã xử lý xong {processed_count}/{len(raw_files)} tài liệu thô", "details": details}


def wiki_query(query: str) -> dict:
    ensure_local_wiki_bootstrap()
    results = []
    seen = set()
    # Search local then global; local takes precedence (skip duplicate filenames)
    _local_raw, _local_wiki = _local_wiki_dirs()
    for wiki_dir, scope in [(_local_wiki, "local"), (GLOBAL_WIKI_DIR, "global")]:
        for sub in ["concepts", "entities"]:
            subdir = os.path.join(wiki_dir, sub)
            if not os.path.isdir(subdir):
                continue
            for fname in os.listdir(subdir):
                if not fname.endswith(".md"):
                    continue
                key = f"{sub}/{fname}"
                if key in seen:
                    continue
                fpath = os.path.join(subdir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    if query.lower() in content.lower() or query.lower() in fname.lower():
                        title = fname[:-3]
                        m_title = re.search(r"title:\s*(.*?)\n", content)
                        if m_title:
                            title = m_title.group(1).strip()
                        results.append({
                            "type": sub.rstrip("s"),
                            "filename": fname,
                            "title": title,
                            "scope": scope,
                            "path": fpath,
                            "content": content,
                        })
                        seen.add(key)
                except Exception:
                    pass
    return {"query": query, "results_count": len(results), "results": results}


def wiki_lint() -> dict:
    ensure_local_wiki_bootstrap()
    errors = []
    all_pages = {}

    _local_raw, _local_wiki = _local_wiki_dirs()
    for wiki_dir, raw_dir, scope in [
        (_local_wiki, _local_raw, "local"),
        (GLOBAL_WIKI_DIR, GLOBAL_RAW_DIR, "global"),
    ]:
        if os.path.isdir(raw_dir):
            for f in os.listdir(raw_dir):
                if os.path.isfile(os.path.join(raw_dir, f)) and f.endswith((".md", ".txt")):
                    errors.append(f"[{scope}] Tài liệu thô chưa được ingest: raw/{f}")

        for sub in ["concepts", "entities", "sources"]:
            subdir = os.path.join(wiki_dir, sub)
            if not os.path.isdir(subdir):
                continue
            for fname in os.listdir(subdir):
                if fname.endswith(".md"):
                    key = fname[:-3]
                    if key not in all_pages:  # local takes precedence
                        all_pages[key] = {"type": sub, "filename": fname, "path": os.path.join(subdir, fname), "scope": scope}

    for p_name, p_info in all_pages.items():
        try:
            with open(p_info["path"], "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                errors.append(f"[{p_info['scope']}] Trang trống: wiki/{p_info['type']}/{p_info['filename']}")
                continue
            for link in re.findall(r"\[\[(.*?)\]\]", content):
                if link.strip().lower() not in {k.lower() for k in all_pages}:
                    errors.append(f"[{p_info['scope']}] Link hỏng: {p_info['type']}/{p_info['filename']} → [[{link}]]")
        except Exception as e:
            errors.append(f"[{p_info['scope']}] Không thể đọc: {p_info['type']}/{p_info['filename']}: {e}")

    return {
        "status": "success" if not errors else "issues_found",
        "errors_count": len(errors),
        "errors": errors,
    }
