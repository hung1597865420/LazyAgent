"""
tools/codebase_index.py — Persistent polyglot code index.

SQLite FTS5 backend + tree-sitter-languages (optional) + Python AST fallback + regex fallback.
Singleton per WORKSPACE_ROOT, lazy-build on first query, incremental update via snapshot hash.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

try:
    from tree_sitter_languages import get_parser as _ts_get_parser  # type: ignore
    _TS_AVAILABLE = True
except Exception:
    _ts_get_parser = None
    _TS_AVAILABLE = False

_log = logging.getLogger("harness.codebase_index")

# ── Skip dirs ──────────────────────────────────────────────────────────────────
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".harness_worktree", ".harness_sandbox",
    ".harness_cache", ".gemini", ".claude", ".next", "dist", "build", "coverage",
    "target", "vendor", ".idea", ".vscode", "out", ".tox", ".eggs", "site-packages",
}

# ── Supported extensions ───────────────────────────────────────────────────────
_TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cs", ".swift", ".kt", ".kts",
    ".scala", ".lua", ".dart", ".m", ".mm", ".sh", ".bash", ".zsh", ".ps1",
    ".sql", ".html", ".css", ".scss", ".less", ".xml", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".md", ".txt",
}

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".java": "java", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".hh": "cpp",
    ".cs": "c_sharp", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".lua": "lua", ".dart": "dart",
    ".m": "objc", ".mm": "objc", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".ps1": "powershell", ".sql": "sql", ".html": "html", ".css": "css",
    ".scss": "scss", ".less": "css", ".xml": "xml",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini", ".md": "markdown", ".txt": "text",
}

_IGNORE_SYMBOL_NAMES = {"__init__", "main", "__new__", "__repr__", "__str__"}
_WORD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_MAX_FILE_BYTES = 500_000  # skip files > 500KB


# ── Singleton registry ─────────────────────────────────────────────────────────
_INSTANCES: dict[str, "CodebaseIndex"] = {}
_GLOBAL_LOCK = threading.Lock()


def get_index(workspace_root: Optional[str] = None) -> "CodebaseIndex":
    """Trả về singleton CodebaseIndex cho workspace_root (mặc định WORKSPACE_ROOT từ config)."""
    if workspace_root is None:
        from config import WORKSPACE_ROOT
        workspace_root = WORKSPACE_ROOT

    key = str(Path(workspace_root).resolve())
    with _GLOBAL_LOCK:
        if key not in _INSTANCES:
            _INSTANCES[key] = CodebaseIndex(key)
    return _INSTANCES[key]


# ── Main class ─────────────────────────────────────────────────────────────────
class CodebaseIndex:
    def __init__(self, workspace_root: str):
        self.workspace_root = str(Path(workspace_root).resolve())
        self.root = Path(self.workspace_root)
        self.cache_dir = self.root / ".harness_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "codebase_index.db"
        self.meta_path = self.cache_dir / "codebase_index_meta.json"
        self._rlock = threading.RLock()   # reentrant — same thread can re-acquire
        self._building = False
        self._conn: Optional[sqlite3.Connection] = None
        self._open_conn()

    # ── Connection ─────────────────────────────────────────────────────────────
    def _open_conn(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # some networked/read-only filesystems don't support WAL
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA cache_size=-16000")
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._open_conn()
        return self._conn  # type: ignore[return-value]

    # ── Public API ─────────────────────────────────────────────────────────────
    def build(self, force: bool = False) -> dict:
        """Index workspace. Reuse cache nếu snapshot chưa thay đổi và force=False."""
        with self._rlock:
            if self._building:
                return {"status": "building", "message": "Index đang được build bởi thread khác"}
            self._building = True

        try:
            return self._build_internal(force)
        finally:
            with self._rlock:
                self._building = False

    def _build_internal(self, force: bool) -> dict:
        started = time.time()
        snapshot = self._compute_snapshot()
        prev = self._load_meta()

        if (not force and prev.get("snapshot_digest") == snapshot["digest"]
                and self._has_index_data()):
            return {
                "status": "reused",
                "files_indexed": self._scalar("SELECT COUNT(*) FROM files"),
                "symbols_indexed": self._scalar("SELECT COUNT(*) FROM symbols"),
                "languages": self._language_counts(),
                "tree_sitter": _TS_AVAILABLE,
                "duration_ms": int((time.time() - started) * 1000),
            }

        files = self._iter_files()
        self._reset_index()
        files_indexed = symbols_indexed = refs_indexed = 0
        warnings: list[str] = []

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for path in files:
                rel = self._rel(path)
                try:
                    raw = path.read_bytes()
                    if len(raw) > _MAX_FILE_BYTES:
                        raw = raw[:_MAX_FILE_BYTES]
                    content = raw.decode("utf-8", errors="replace")
                except Exception as e:
                    warnings.append(f"{rel}: read error — {e}")
                    continue

                language = _LANG_BY_EXT.get(path.suffix.lower(), "text")
                file_id = self._insert_file(rel, language, content, path.stat().st_mtime)
                files_indexed += 1

                syms, refs, w = self._extract(rel, language, content)
                warnings.extend(w)
                for s in syms:
                    self._insert_symbol(file_id, rel, language, content, s)
                    symbols_indexed += 1
                for r in refs:
                    self._insert_ref(file_id, rel, r)
                    refs_indexed += 1

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self._save_meta({"snapshot_digest": snapshot["digest"], "built_at": time.time()})
        _log.info("Index built: %d files, %d symbols (%s)", files_indexed, symbols_indexed,
                  "tree-sitter" if _TS_AVAILABLE else "fallback")

        return {
            "status": "rebuilt",
            "files_indexed": files_indexed,
            "symbols_indexed": symbols_indexed,
            "references_indexed": refs_indexed,
            "languages": self._language_counts(),
            "tree_sitter": _TS_AVAILABLE,
            "warnings": warnings[:100],
            "duration_ms": int((time.time() - started) * 1000),
        }

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Semantic search. Auto-build index nếu chưa có."""
        self._ensure_indexed()
        query = (query or "").strip()
        if not query:
            return []
        try:
            top_k = max(1, min(int(top_k), 100))
        except (TypeError, ValueError):
            top_k = 10
        fts_query = self._to_fts_query(query)

        try:
            rows = self.conn.execute(
                """
                SELECT s.path, s.symbol, s.kind, s.language,
                       bm25(search_index, 1.0, 2.5, 1.0, 0.8) AS rank, s.snippet
                FROM search_index
                JOIN search_source s ON s.rowid = search_index.rowid
                WHERE search_index MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (fts_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query.lower()}%"
            rows = self.conn.execute(
                """SELECT path, symbol, kind, language, 0.0 AS rank, snippet
                   FROM search_source
                   WHERE lower(path) LIKE ? OR lower(COALESCE(symbol,'')) LIKE ?
                      OR lower(snippet) LIKE ?
                   LIMIT ?""",
                (like, like, like, top_k),
            ).fetchall()

        return [
            {
                "path": r["path"], "symbol": r["symbol"], "kind": r["kind"],
                "language": r["language"],
                "score": round(max(0.01, min(1.0, 1.0 / (1.0 + abs(float(r["rank"] or 0))))), 4),
                "snippet": _trim(r["snippet"], 200),
            }
            for r in rows
        ]

    def get_symbols(self, file_path: str) -> list[dict]:
        """Trả về tất cả symbols (hàm, class) trong một file."""
        self._ensure_indexed()
        rel = self._normalize_rel(file_path)
        rows = self.conn.execute(
            "SELECT path,symbol,kind,language,snippet FROM symbols WHERE path=? ORDER BY line",
            (rel,),
        ).fetchall()
        return [
            {"path": r["path"], "symbol": r["symbol"], "kind": r["kind"],
             "language": r["language"], "score": 1.0, "snippet": _trim(r["snippet"], 200)}
            for r in rows
        ]

    def find_dead_code(self) -> list[dict]:
        """Tìm symbols không được reference từ nơi nào khác (polyglot)."""
        self._ensure_indexed()
        rows = self.conn.execute(
            """
            SELECT s.path, s.symbol, s.kind, s.language, s.snippet, s.line,
                   (SELECT COUNT(*) FROM refs r
                    WHERE r.ref_symbol = s.symbol
                      AND NOT (r.path = s.path AND r.line = s.line)) AS inbound
            FROM symbols s
            WHERE s.kind IN ('function','class')
            ORDER BY inbound ASC, s.path, s.line
            """
        ).fetchall()

        return [
            {"path": r["path"], "symbol": r["symbol"], "kind": r["kind"],
             "language": r["language"], "score": 1.0, "snippet": _trim(r["snippet"], 200)}
            for r in rows
            if (r["symbol"] or "") and not (r["symbol"] or "").startswith("_")
            and (r["symbol"] or "") not in _IGNORE_SYMBOL_NAMES
            and r["inbound"] == 0
        ]

    def get_callers(self, symbol: str) -> list[dict]:
        """Tìm những chỗ gọi symbol này trong codebase."""
        self._ensure_indexed()
        symbol = (symbol or "").strip()
        if not symbol:
            return []
        rows = self.conn.execute(
            """
            SELECT s.path, s.symbol, s.kind, s.language, s.snippet, COUNT(*) AS calls
            FROM refs r
            LEFT JOIN symbols s ON s.path=r.path AND s.symbol=r.owner_symbol
            WHERE r.ref_symbol=?
            GROUP BY s.path,s.symbol,s.kind,s.language,s.snippet
            ORDER BY calls DESC, s.path
            """,
            (symbol,),
        ).fetchall()
        return [
            {"path": r["path"] or "?", "symbol": r["symbol"], "kind": r["kind"] or "file",
             "language": r["language"], "score": round(min(1.0, 0.3 + 0.15 * int(r["calls"])), 4),
             "snippet": _trim(r["snippet"], 200)}
            for r in rows if r["path"]
        ]

    # ── Lazy init ──────────────────────────────────────────────────────────────
    def _ensure_indexed(self) -> None:
        if self._has_index_data():
            return
        with self._rlock:  # double-checked: second thread waits, then sees data already built
            if not self._has_index_data():
                _log.info("Index chưa có — auto-building...")
                self.build()

    # ── DB schema ──────────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                language TEXT, file_hash TEXT, mtime REAL, snippet TEXT, content TEXT
            );
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL,
                path TEXT NOT NULL, symbol TEXT, kind TEXT, language TEXT,
                line INTEGER, end_line INTEGER, snippet TEXT, signature TEXT,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS refs (
                id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL,
                path TEXT NOT NULL, owner_symbol TEXT, ref_symbol TEXT NOT NULL,
                line INTEGER, kind TEXT,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS search_source (
                rowid INTEGER PRIMARY KEY, path TEXT NOT NULL, symbol TEXT,
                kind TEXT NOT NULL, language TEXT, snippet TEXT, content TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index
            USING fts5(path, symbol, kind, language, snippet, content,
                       content='search_source', content_rowid='rowid');
            CREATE INDEX IF NOT EXISTS idx_sym_sym ON symbols(symbol);
            CREATE INDEX IF NOT EXISTS idx_sym_path ON symbols(path);
            CREATE INDEX IF NOT EXISTS idx_refs_ref ON refs(ref_symbol);
            CREATE INDEX IF NOT EXISTS idx_refs_own ON refs(owner_symbol);
            CREATE INDEX IF NOT EXISTS idx_refs_path ON refs(path);
        """)
        c.commit()

    def _reset_index(self) -> None:
        self.conn.executescript(
            "DELETE FROM refs; DELETE FROM symbols; DELETE FROM files;"
            "DELETE FROM search_index; DELETE FROM search_source;"
        )
        self.conn.commit()

    def _insert_file(self, rel: str, language: str, content: str, mtime: float) -> int:
        snippet = _trim(" ".join(content.split()), 200)
        fh = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO files(path,language,file_hash,mtime,snippet,content) VALUES(?,?,?,?,?,?)",
            (rel, language, fh, mtime, snippet, content[:10000]),
        )
        file_id = int(cur.lastrowid)
        s_cur = self.conn.execute(
            "INSERT INTO search_source(path,symbol,kind,language,snippet,content) VALUES(?,NULL,'file',?,?,?)",
            (rel, language, snippet, content[:10000]),
        )
        self.conn.execute(
            "INSERT INTO search_index(rowid,path,symbol,kind,language,snippet,content) VALUES(?,?,NULL,'file',?,?,?)",
            (int(s_cur.lastrowid), rel, language, snippet, content[:10000]),
        )
        return file_id

    def _insert_symbol(self, file_id: int, rel: str, language: str, content: str, sym: dict) -> None:
        lines = content.splitlines()
        sl, el = sym.get("line") or 1, sym.get("end_line") or sym.get("line") or 1
        block = "\n".join(lines[max(0, sl - 1):min(el + 1, len(lines))])
        snippet = _trim(block.strip(), 200)
        self.conn.execute(
            "INSERT INTO symbols(file_id,path,symbol,kind,language,line,end_line,snippet,signature)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (file_id, rel, sym.get("symbol"), sym.get("kind"), language,
             sl, el, snippet, sym.get("signature")),
        )
        s_cur = self.conn.execute(
            "INSERT INTO search_source(path,symbol,kind,language,snippet,content) VALUES(?,?,?,?,?,?)",
            (rel, sym.get("symbol"), sym.get("kind"), language, snippet, snippet),
        )
        self.conn.execute(
            "INSERT INTO search_index(rowid,path,symbol,kind,language,snippet,content) VALUES(?,?,?,?,?,?,?)",
            (int(s_cur.lastrowid), rel, sym.get("symbol"), sym.get("kind"), language, snippet, snippet),
        )

    def _insert_ref(self, file_id: int, rel: str, ref: dict) -> None:
        self.conn.execute(
            "INSERT INTO refs(file_id,path,owner_symbol,ref_symbol,line,kind) VALUES(?,?,?,?,?,?)",
            (file_id, rel, ref.get("owner_symbol"), ref.get("ref_symbol"),
             ref.get("line"), ref.get("kind", "call")),
        )

    # ── Symbol extraction ──────────────────────────────────────────────────────
    def _extract(self, rel: str, language: str, content: str) -> tuple[list, list, list[str]]:
        warnings: list[str] = []

        if language == "python":
            try:
                return _py_symbols(content), _py_refs(content), warnings
            except SyntaxError:
                pass  # fall through to tree-sitter / regex
            except Exception as e:
                warnings.append(f"{rel}: ast error — {e}")

        if _TS_AVAILABLE:
            try:
                parser = _ts_get_parser(language)
                syms, refs = _ts_extract(parser, content)
                if syms or refs:
                    return syms, refs, warnings
            except Exception as e:
                warnings.append(f"{rel}: tree-sitter ({language}) — {e}")

        return _regex_symbols(content), _regex_refs(content), warnings

    # ── Filesystem ─────────────────────────────────────────────────────────────
    def _iter_files(self) -> list[Path]:
        out: list[Path] = []
        for p in self.root.rglob("*"):
            try:
                if any(part in _SKIP_DIRS for part in p.parts):
                    continue
                if not p.is_file() or p.suffix.lower() not in _TEXT_EXTS:
                    continue
                out.append(p)
            except Exception:
                continue
        out.sort(key=lambda x: str(x).lower())
        return out

    def _compute_snapshot(self) -> dict:
        h = hashlib.sha256()
        count = 0
        for p in self._iter_files():
            try:
                st = p.stat()
                h.update(f"{self._rel(p)}|{int(st.st_mtime)}|{st.st_size}\n".encode())
                count += 1
            except Exception:
                pass
        return {"digest": h.hexdigest(), "file_count": count}

    def _rel(self, path: Path) -> str:
        return os.path.relpath(str(path), self.workspace_root).replace("\\", "/")

    def _normalize_rel(self, file_path: str) -> str:
        p = Path(file_path)
        if p.is_absolute():
            try:
                return os.path.relpath(str(p.resolve()), self.workspace_root).replace("\\", "/")
            except Exception:
                pass
        return str(p).replace("\\", "/")

    # ── Meta ───────────────────────────────────────────────────────────────────
    def _load_meta(self) -> dict:
        try:
            if self.meta_path.is_file():
                return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_meta(self, data: dict) -> None:
        try:
            self.meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ── SQL helpers ────────────────────────────────────────────────────────────
    def _has_index_data(self) -> bool:
        try:
            return self._scalar("SELECT COUNT(*) FROM files") > 0
        except Exception:
            return False

    def _scalar(self, sql: str) -> int:
        row = self.conn.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _language_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT language, COUNT(*) AS c FROM files GROUP BY language ORDER BY c DESC"
        ).fetchall()
        return {str(r["language"]): int(r["c"]) for r in rows}

    def _to_fts_query(self, query: str) -> str:
        tokens = [t for t in _WORD_RE.findall(query.lower()) if len(t) >= 2]
        if not tokens:
            safe = query.replace('"', " ").strip()
            return f'"{safe}"' if safe else '"__nomatch__"'
        return " OR ".join(f'"{t}"' for t in tokens[:12])

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()


# ── Module-level helpers ───────────────────────────────────────────────────────
def _trim(text: Any, limit: int) -> str:
    if not text:
        return ""
    return str(text).replace("\x00", " ").strip()[:limit]


# ── Python AST extraction ──────────────────────────────────────────────────────
def _py_symbols(content: str) -> list[dict]:
    tree = ast.parse(content)
    symbols: list[dict] = []
    stack: list[str] = []

    class V(ast.NodeVisitor):
        def _visit_def(self, node: Any, kind: str) -> None:
            qual = ".".join(stack + [node.name]) if stack else node.name
            args = getattr(node.args, "args", [])
            sig = f"{'async ' if kind == 'async_function' else ''}def {qual}({', '.join(a.arg for a in args)})"
            symbols.append({"symbol": qual, "kind": "function", "line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno), "signature": sig})
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            qual = ".".join(stack + [node.name]) if stack else node.name
            symbols.append({"symbol": qual, "kind": "class", "line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                            "signature": f"class {qual}"})
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_def(node, "function")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_def(node, "async_function")

    V().visit(tree)
    return symbols


def _py_refs(content: str) -> list[dict]:
    tree = ast.parse(content)
    refs: list[dict] = []
    stack: list[str] = []

    class V(ast.NodeVisitor):
        def _enter(self, node: Any) -> str:
            qual = ".".join(stack + [node.name]) if stack else node.name
            stack.append(node.name)
            return qual

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def _visit_func(self, node: Any) -> None:
            owner = self._enter(node)
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = None
                    if isinstance(child.func, ast.Name):
                        name = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        name = child.func.attr
                    if name:
                        refs.append({"owner_symbol": owner, "ref_symbol": name,
                                     "line": getattr(child, "lineno", node.lineno), "kind": "call"})
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_func(node)

    V().visit(tree)
    return refs


# ── Tree-sitter extraction ─────────────────────────────────────────────────────
_TS_SYMBOL_NODE_TYPES = {
    "function_definition", "function_declaration", "method_definition", "method_declaration",
    "class_definition", "class_declaration", "interface_declaration", "struct_item",
    "enum_declaration",
}
_TS_IDENT_TYPES = {"identifier", "property_identifier", "type_identifier"}


def _ts_extract(parser: Any, content: str) -> tuple[list[dict], list[dict]]:
    tree = parser.parse(content.encode("utf-8", errors="replace"))
    symbols: list[dict] = []
    refs: list[dict] = []
    encoded = content.encode("utf-8", errors="replace")

    def text(node: Any) -> str:
        return encoded[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def first_ident(node: Any) -> Any:
        for child in node.children:
            if child.type in _TS_IDENT_TYPES:
                return child
            found = first_ident(child)
            if found:
                return found
        return None

    def kind_for(nt: str) -> str:
        if any(k in nt for k in ("class", "interface", "struct", "enum")):
            return "class"
        if any(k in nt for k in ("function", "method")):
            return "function"
        return "variable"

    def walk(node: Any, owner: Optional[str] = None) -> None:
        cur_owner = owner
        if node.type in _TS_SYMBOL_NODE_TYPES:
            ident = first_ident(node)
            if ident:
                name = text(ident).strip()
                if name:
                    cur_owner = name
                    sig_line = text(node).splitlines()
                    symbols.append({
                        "symbol": name, "kind": kind_for(node.type),
                        "line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1,
                        "signature": _trim(sig_line[0] if sig_line else name, 200),
                    })
        if node.type == "call_expression":
            ident = first_ident(node)
            if ident:
                name = text(ident).strip()
                if name:
                    refs.append({"owner_symbol": cur_owner, "ref_symbol": name,
                                 "line": node.start_point[0] + 1, "kind": "call"})
        for child in node.children:
            walk(child, cur_owner)

    walk(tree.root_node)
    return symbols, refs


# ── Regex fallback ─────────────────────────────────────────────────────────────
_REGEX_SYM_PATTERNS = [
    ("function", re.compile(r"^\s*(?:async\s+)?(?:export\s+)?function\s+([A-Za-z_]\w*)\s*\(")),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\(")),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)\b")),
    ("variable", re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\b")),
]


def _regex_symbols(content: str) -> list[dict]:
    out: list[dict] = []
    for idx, line in enumerate(content.splitlines(), 1):
        for kind, pat in _REGEX_SYM_PATTERNS:
            m = pat.match(line)
            if m:
                out.append({"symbol": m.group(1), "kind": kind, "line": idx, "end_line": idx,
                            "signature": line.strip()[:200]})
                break
    return out


def _regex_refs(content: str) -> list[dict]:
    refs: list[dict] = []
    for idx, line in enumerate(content.splitlines(), 1):
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", line):
            refs.append({"owner_symbol": None, "ref_symbol": m.group(1), "line": idx, "kind": "call"})
    return refs
