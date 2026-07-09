"""
Agent Harness - Configuration
12-Agent Support Toolbox cho Claude Code | Azure AI Foundry
"""
import os
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

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
    # ── Orchestration (2x pro) ────────────────────────────────────────────────
    manager:     str   # gpt-5.4-pro-3   — ask_codebase: Q&A trên codebase lớn (1M context)
    synthesizer: str   # gpt-5.4-pro-2   — merge/dedupe findings từ review panel

    # ── Analysis ─────────────────────────────────────────────────────────────
    analyzer:    str   # grok-4-20-reasoning — consult: design questions, trade-offs

    # ── Code (dual parallel) ─────────────────────────────────────────────────
    code_a:      str   # Kimi-K2.6       — alt_implementation approach 1
    code_b:      str   # gpt-5.4         — alt_implementation approach 2

    # ── Review panel (3x codex parallel + 1x integrity sequential) ──────────────
    reviewer:    str   # gpt-5.3-codex   — code quality, bugs, anti-patterns
    tester:      str   # gpt-5.3-codex-2 — test gaps, edge cases
    security:    str   # gpt-5.3-codex-3 — OWASP, vulns, auth, injection
    integrity:   str   # gpt-5.3-codex-4 — data integrity + synthesis guard (runs after panel)
    scanner:     str   # gpt-5.3-codex-4 — static analysis: dead_code/complexity/duplicate/perf (high TPM)

    # ── Fix ───────────────────────────────────────────────────────────────────
    debugger:    str   # gpt-5.4-2       — suggest_fix: root cause + patch

    # ── Worker ───────────────────────────────────────────────────────────────
    worker:      str   # gpt-5.4-mini    — quick_task: boilerplate, format, docs


def get_model_config() -> ModelConfig:
    return ModelConfig(
        manager     = os.getenv("MODEL_MANAGER",     "gpt-5.4-pro-3"),  # true 1M context
        synthesizer = os.getenv("MODEL_SYNTHESIZER", "gpt-5.4-pro-2"),
        analyzer    = os.getenv("MODEL_ANALYZER",    "grok-4-20-reasoning"),
        code_a      = os.getenv("MODEL_CODE_A",      "Kimi-K2.6"),
        code_b      = os.getenv("MODEL_CODE_B",      "gpt-5.4"),
        reviewer    = os.getenv("MODEL_REVIEWER",    "gpt-5.3-codex"),
        tester      = os.getenv("MODEL_TESTER",      "gpt-5.3-codex-2"),
        security    = os.getenv("MODEL_SECURITY",    "gpt-5.3-codex-3"),
        integrity   = os.getenv("MODEL_INTEGRITY",   "gpt-5.3-codex-4"),
        scanner     = os.getenv("MODEL_SCANNER",     "gpt-5.3-codex-4"),
        debugger    = os.getenv("MODEL_DEBUGGER",    "gpt-5.4-2"),
        worker      = os.getenv("MODEL_WORKER",      "gpt-5.4-mini"),
    )


# ── Spare deployments — fallback khi rate-limit dai dẳng ─────────────────────
SPARE_MODELS: list[str] = [
    m.strip()
    for m in os.getenv("SPARE_MODELS", "gpt-5.3-codex-4,gpt-5.4-3,gpt-5.4-4,gpt-4.1-mini").split(",")
    if m.strip()
]

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
    "analyzer":    _safe_float("ROLE_TIMEOUT_ANALYZER",    300.0, min_val=30.0),  # grok reasoning chậm
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


# True khi dùng endpoint OpenAI-compatible ngoài Azure (9Router, OpenRouter, LiteLLM...)
# → tắt Responses API path, dùng Chat Completions cho tất cả model
IS_OPENAI_COMPAT: bool = "azure.com" not in os.getenv("AZURE_OPENAI_ENDPOINT", "")


def get_azure_client() -> OpenAI:
    """Tự nhận diện loại endpoint:
    - Endpoint không chứa azure.com  → OpenAI-compatible proxy (9Router, OpenRouter…)
    - *.services.ai.azure.com        → Azure AI Foundry model inference (OpenAI SDK + base_url)
    - *.openai.azure.com             → Azure OpenAI cổ điển (AzureOpenAI client)
    """
    endpoint    = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key     = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_API_VERSION", "2024-05-01-preview")

    if not endpoint or not api_key:
        raise ValueError(
            "Thiếu AZURE_OPENAI_ENDPOINT hoặc AZURE_OPENAI_API_KEY trong .env"
        )

    if "azure.com" not in endpoint:
        # OpenAI-compatible proxy: 9Router, OpenRouter, LiteLLM, vLLM...
        # Responses API bị tắt tự động qua IS_OPENAI_COMPAT
        base_url = endpoint.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=REQUEST_TIMEOUT,
            max_retries=0,
        )

    if "services.ai.azure.com" in endpoint:
        # Chấp nhận cả Target URI đầy đủ lẫn base URL — chuẩn hóa về .../models
        base_url = endpoint.split("/chat/completions")[0].rstrip("/")
        if not base_url.endswith("/models"):
            base_url += "/models"
        return OpenAI(
            base_url=base_url,
            api_key=api_key,
            default_query={"api-version": api_version},
            timeout=REQUEST_TIMEOUT,
            max_retries=0,  # retry tự xử lý trong agents._chat_completion
        )

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        timeout=REQUEST_TIMEOUT,
        max_retries=0,  # retry tự xử lý trong agents._chat_completion
    )


def get_responses_client() -> OpenAI:
    """Client cho Responses API — dòng pro/codex CHỈ chạy API này.
    Host: *.cognitiveservices.azure.com (suy ra từ endpoint chính nếu không set riêng).
    """
    api_key  = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_RESPONSES_ENDPOINT")

    if not api_key:
        raise ValueError("Thiếu AZURE_OPENAI_API_KEY trong .env")
    if not endpoint:
        main = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        host = main.split("://")[-1].split("/")[0]
        resource = host.split(".")[0]
        if not resource:
            raise ValueError("Không suy ra được AZURE_RESPONSES_ENDPOINT từ AZURE_OPENAI_ENDPOINT")
        endpoint = f"https://{resource}.cognitiveservices.azure.com"
    # Chấp nhận cả Target URI đầy đủ (.../openai/responses?...) lẫn base URL
    endpoint = endpoint.split("/openai")[0].rstrip("/")

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=os.getenv("AZURE_RESPONSES_API_VERSION", "2025-04-01-preview"),
        timeout=REQUEST_TIMEOUT,
        max_retries=0,
    )


MODELS = get_model_config()
