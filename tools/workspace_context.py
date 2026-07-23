"""Context-local workspace override for in-process hook/tool calls."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from pathlib import Path


_ACTIVE_WORKSPACE: ContextVar[str] = ContextVar("harness_active_workspace", default="")


def get_active_workspace_override() -> str:
    return _ACTIVE_WORKSPACE.get()


def capture_workspace_context():
    """Return a runner that propagates the current workspace into plain threads."""
    ctx = copy_context()

    def run(func, /, *args, **kwargs):
        return ctx.copy().run(func, *args, **kwargs)

    return run


@contextmanager
def workspace_scope(root: str | Path):
    path = Path(str(root)).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"workspace root does not exist or is not a directory: {path}")
    value = str(path)
    token = _ACTIVE_WORKSPACE.set(value)
    try:
        yield
    finally:
        _ACTIVE_WORKSPACE.reset(token)
