"""
tools/wiki.py — Wiki and documentation sync tools.
Ported from support_tools.py.
"""
# ruff: noqa: F401
import os
import ast
import json
from config import WORKSPACE_ROOT, get_llm_client
from agents import Agent, AgentRole

# Re-export tools from llmwiki_tool for unified tools packaging
from llmwiki_tool import wiki_ingest, wiki_query, wiki_lint

async def doc_sync() -> dict:
    """Tự động đồng bộ hóa tài liệu dự án (README/swagger/Wiki) khi code thay đổi."""
    warnings = []
    
    py_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                py_files.append(os.path.join(r_dir, f))
                
    public_functions = []
    
    for py_file in py_files:
        rel_path = os.path.relpath(py_file, WORKSPACE_ROOT)
        try:
            with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
            
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                doc = ast.get_docstring(node) or "No docstring"
                public_functions.append({
                    "file": rel_path,
                    "name": node.name,
                    "doc": doc
                })
                
    readme_file = os.path.join(WORKSPACE_ROOT, "README.md")
    readme_content = ""
    if os.path.isfile(readme_file):
        try:
            with open(readme_file, "r", encoding="utf-8") as f:
                readme_content = f.read()
        except Exception:
            pass
            
    undocumented = []
    for fn in public_functions:
        if fn["name"] not in readme_content:
            undocumented.append(fn)
            
    if not undocumented:
        return {
            "success": True,
            "message": "Tất cả các hàm public đều đã được mô tả đầy đủ trong tài liệu!",
            "warnings": warnings
        }
        
    prompt = (
        "Bạn là Technical Writer Agent.\n"
        "Hãy viết phần bổ sung mô tả tài liệu (Markdown format) cho các hàm public sau chưa được nhắc tới trong README.md:\n"
        f"{json.dumps(undocumented, ensure_ascii=False, indent=2)}\n\n"
        "Yêu cầu:\n"
        "- Trả về duy nhất nội dung tài liệu Markdown bổ sung.\n"
        "- Trình bày mạch lạc, rõ ràng các tham số và kiểu trả về."
    )
    
    client = get_llm_client()
    agent = Agent(AgentRole.WORKER, client)
    res = await agent.run_async(prompt)
    
    if res.status != "success" or not res.result:
        return {"error": f"Agent doc writer thất bại: {res.error}", "warnings": warnings}
        
    doc_addition = res.result.strip()
    
    if os.path.isfile(readme_file):
        try:
            with open(readme_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n## API Reference (Auto-Generated Additions)\n\n{doc_addition}\n")
            return {
                "success": True,
                "message": f"Đã tự động cập nhật tài liệu cho {len(undocumented)} hàm public mới vào README.md",
                "additions": doc_addition,
                "warnings": warnings
            }
        except Exception as e:
            return {"error": f"Không thể ghi đè README.md: {e}", "warnings": warnings}
    else:
        return {
            "success": True,
            "message": "Không tìm thấy README.md để cập nhật, đây là nội dung tài liệu đề xuất",
            "suggested_markdown": doc_addition,
            "warnings": warnings
        }
