"""
Agent Harness - Configuration
12-Agent Support Toolbox cho Claude Code | 9Router Proxy
"""
import os
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

dotenv_disabled = os.getenv("HARNESS_DISABLE_DOTENV", "").lower() in ("1", "true", "yes")
if not dotenv_disabled:
    env_file_raw = os.getenv("HARNESS_ENV_FILE")
    env_name = os.getenv("HARNESS_ENV") or os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or ""
    implicit_dev_env = env_name.lower() not in ("prod", "production")
    env_file = Path(env_file_raw).expanduser() if env_file_raw else Path(__file__).with_name(".env")
    if env_file_raw or implicit_dev_env:
        load_dotenv(dotenv_path=env_file, override=False)

@dataclass
class ModelConfig:
    # Economy defaults: keep 5.6 out of primary paths; reserve it for explicit fallback.
    manager:     str
    synthesizer: str

    analyzer:    str

    code_a:      str
    code_b:      str

    reviewer:    str
    tester:      str
    security:    str
    integrity:   str
    scanner:     str

    debugger:    str

    worker:      str


def get_model_config() -> ModelConfig:
    def model_env(key: str, default: str) -> str:
        return (os.getenv(key, default) or "").strip() or default

    codex_light = "cx/gpt-5.4-mini"
    codex_code = "cx/gpt-5.5"
    codex_alt = "cx/gpt-5.5-review"
    codex_review = "cx/gpt-5.5-review"

    return ModelConfig(
        manager     = model_env("MODEL_MANAGER",     codex_light),
        synthesizer = model_env("MODEL_SYNTHESIZER", codex_light),
        analyzer    = model_env("MODEL_ANALYZER",    codex_review),
        code_a      = model_env("MODEL_CODE_A",      codex_code),
        code_b      = model_env("MODEL_CODE_B",      codex_alt),
        reviewer    = model_env("MODEL_REVIEWER",    codex_review),
        tester      = model_env("MODEL_TESTER",      codex_code),
        security    = model_env("MODEL_SECURITY",    codex_review),
        integrity   = model_env("MODEL_INTEGRITY",   codex_review),
        scanner     = model_env("MODEL_SCANNER",     codex_light),
        debugger    = model_env("MODEL_DEBUGGER",    codex_code),
        worker      = model_env("MODEL_WORKER",      codex_light),
    )


# ── Spare deployments — fallback khi rate-limit dai dẳng ─────────────────────
DEFAULT_SPARE_MODELS = "cx/gpt-5.4-mini,cx/gpt-5.5,cx/gpt-5.5-review,cx/gpt-5.6-sol,cx/gpt-5.6-sol-review"
DEFAULT_EXTRA_DEPLOYMENTS = "cx/gpt-5.6-sol,cx/gpt-5.6-sol-review,cx/gpt-5.6-terra,cx/gpt-5.6-terra-review,cx/gpt-5.6-luna,cx/gpt-5.6-luna-review,cx/gpt-5.5,cx/gpt-5.5-review,cx/gpt-5.4,cx/gpt-5.4-review,cx/gpt-5.4-mini"


def _csv_values(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


def _parse_spare_models(raw: str, known: set[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for model in _csv_values(raw):
        key = model.lower()
        if key in seen or key not in known:
            continue
        seen.add(key)
        result.append(model)
    return result


def _known_deployments() -> set[str]:
    models = get_model_config()
    return {
        m.lower()
        for m in [
            *models.__dict__.values(),
            *_csv_values(os.getenv("HARNESS_KNOWN_DEPLOYMENTS", DEFAULT_EXTRA_DEPLOYMENTS)),
        ]
    }


def get_spare_models() -> list[str]:
    known = _known_deployments()
    parsed = _parse_spare_models(os.getenv("SPARE_MODELS", DEFAULT_SPARE_MODELS), known)
    if parsed:
        return parsed
    fallback = _parse_spare_models(DEFAULT_SPARE_MODELS, known)
    if fallback:
        return fallback
    return [get_model_config().worker]


def configured_model_aliases(models: ModelConfig | None = None) -> dict[str, str]:
    models = models or get_model_config()
    return dict(models.__dict__)


def validate_model_aliases(available_model_ids: list[str] | set[str] | tuple[str, ...]) -> dict:
    """Validate configured aliases against a provider model list without calling the provider."""
    available = {str(item).strip().lower() for item in available_model_ids if str(item).strip()}
    configured = configured_model_aliases()
    missing = {
        role: model
        for role, model in configured.items()
        if str(model).strip().lower() not in available
    }
    spares = get_spare_models()
    missing_spares = [
        model for model in spares
        if str(model).strip().lower() not in available
    ]
    ok = not missing
    return {
        "ok": ok,
        "configured": configured,
        "available_count": len(available),
        "missing": missing,
        "spares": spares,
        "missing_spares": missing_spares,
        "message": (
            "All configured MODEL_* aliases are available."
            if ok else
            "Configured MODEL_* aliases are missing from this router. Update .env MODEL_* / SPARE_MODELS / "
            "HARNESS_KNOWN_DEPLOYMENTS to match `get_llm_client().models.list()`."
        ),
    }

# ── Workspace root — support tools đọc file theo path tương đối từ đây ───────
# Ưu tiên: WORKSPACE_ROOT (.env) → CLAUDE_PROJECT_DIR (Claude Code tự set cho
# MCP server = project đang mở) → cwd. Đăng ký scope user thì cứ để trống,
# harness sẽ tự bám theo project mà Claude Code đang làm việc.
def _get_workspace_root() -> str:
    import json
    w = os.getenv("WORKSPACE_ROOT") or os.getenv("CLAUDE_PROJECT_DIR")
    if w:
        return os.path.abspath(w)
    meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
    if meta:
        try:
            data = json.loads(meta)
            w = data.get("tool", {}).get("workspacePath")
            if w:
                return os.path.abspath(w)
        except Exception:
            pass
    return os.path.abspath(".")

WORKSPACE_ROOT: str = _get_workspace_root()

# ── Limits ────────────────────────────────────────────────────────────────────
def _safe_int(key: str, default: int, min_val: int = 0, max_val: int = 2**31) -> int:
    try:
        return max(min_val, min(max_val, int(os.getenv(key, str(default)))))
    except (ValueError, TypeError):
        return max(min_val, default)

def _safe_float(key: str, default: float, min_val: float = 1.0, max_val: float = 600.0) -> float:
    try:
        v = float(os.getenv(key, str(default)))
        return max(min_val, min(max_val, v)) if math.isfinite(v) else max(min_val, default)
    except (ValueError, TypeError):
        return max(min_val, default)

MAX_OUTPUT_TOKENS: int   = _safe_int("MAX_OUTPUT_TOKENS", 16384, min_val=1)
MAX_RETRIES:       int   = _safe_int("MAX_RETRIES",        1,     min_val=0, max_val=1)
REQUEST_TIMEOUT:   float = _safe_float("REQUEST_TIMEOUT",  90.0,  min_val=1.0)

# ── Per-role timeout (giây) ───────────────────────────────────────────────────
ROLE_TIMEOUTS: dict[str, float] = {
    "manager":     _safe_float("ROLE_TIMEOUT_MANAGER",     300.0, min_val=30.0),  # codebase lớn cần thời gian
    "synthesizer": _safe_float("ROLE_TIMEOUT_SYNTHESIZER", 120.0, min_val=30.0),
    "analyzer":    _safe_float("ROLE_TIMEOUT_ANALYZER",    300.0, min_val=30.0),
    "code_a":      _safe_float("ROLE_TIMEOUT_CODE_A",       90.0, min_val=30.0),
    "code_b":      _safe_float("ROLE_TIMEOUT_CODE_B",       90.0, min_val=30.0),
    "reviewer":    _safe_float("ROLE_TIMEOUT_REVIEWER",    180.0, min_val=10.0),
    "tester":      _safe_float("ROLE_TIMEOUT_TESTER",      180.0, min_val=10.0),
    "security":    _safe_float("ROLE_TIMEOUT_SECURITY",    180.0, min_val=10.0),
    "integrity":   _safe_float("ROLE_TIMEOUT_INTEGRITY",   240.0, min_val=10.0),  # synthesis sau 3 reviewer nên cần thêm thời gian
    "scanner":     _safe_float("ROLE_TIMEOUT_SCANNER",     120.0, min_val=10.0),
    "debugger":    _safe_float("ROLE_TIMEOUT_DEBUGGER",     90.0, min_val=30.0),
    "worker":      _safe_float("ROLE_TIMEOUT_WORKER",       30.0, min_val=10.0),
}


# 9Router local proxy is OpenAI-compatible; use Chat Completions for all configured models.
IS_OPENAI_COMPAT: bool = True


def get_llm_client() -> OpenAI:
    """Return the OpenAI-compatible 9Router client."""
    endpoint = os.getenv("ROUTER_BASE_URL", "http://localhost:20128")
    api_key = os.getenv("ROUTER_API_KEY", "dummy")

    if not endpoint or not api_key:
        raise ValueError(
            "Thiếu ROUTER_BASE_URL hoặc ROUTER_API_KEY trong .env"
        )

    base_url = endpoint.split("/chat/completions")[0].rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    user_agent = os.getenv("ROUTER_USER_AGENT", "python-httpx/0.28.1").strip() or "python-httpx/0.28.1"
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=REQUEST_TIMEOUT,
        max_retries=0,
        default_headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )


def get_router_responses_client() -> OpenAI:
    """Compatibility hook for old Responses path; 9Router uses the same OpenAI-compatible client."""
    return get_llm_client()


MODELS = get_model_config()
