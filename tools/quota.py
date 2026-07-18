"""
Read-only quota reminder for 9Router + local FinOps usage.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from agents import get_finops_stats


DEFAULT_WARN_PCT = 80.0
DEFAULT_CRITICAL_PCT = 95.0
DEFAULT_PERIOD = "30d"


def _env_float(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def _env_list(name: str) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_base_url(value: str | None) -> str:
    base = (value or os.getenv("ROUTER_BASE_URL") or "http://localhost:20128").strip()
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


def _quota_auth_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw_json = (os.getenv("HARNESS_ROUTER_QUOTA_HEADERS_JSON") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items() if v is not None})
        except Exception:
            pass
    cookie = (os.getenv("HARNESS_ROUTER_QUOTA_COOKIE") or "").strip()
    if cookie and "Cookie" not in headers:
        headers["Cookie"] = cookie
    bearer = (os.getenv("HARNESS_ROUTER_QUOTA_BEARER") or "").strip()
    if bearer:
        headers["Authorization"] = bearer if bearer.lower().startswith("bearer ") else f"Bearer {bearer}"
    elif api_key and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _request_json(url: str, *, timeout: float, api_key: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    headers = {"Accept": "application/json", **_quota_auth_headers(api_key)}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            data = json.loads(raw) if raw.strip() else {}
            return (data if isinstance(data, dict) else {"data": data}), None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return None, f"HTTP {exc.code} from {url}: {detail[:180]}"
    except Exception as exc:
        return None, f"{type(exc).__name__} from {url}: {exc}"


def _num_from_paths(data: Any, paths: list[tuple[str, ...]]) -> float | None:
    for path in paths:
        cur = data
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        if isinstance(cur, (int, float)):
            return float(cur)
        if isinstance(cur, str):
            try:
                return float(cur.replace(",", ""))
            except ValueError:
                pass
    return None


def _token_total(stats: dict[str, Any]) -> int:
    return int(stats.get("total_prompt_tokens") or 0) + int(stats.get("total_completion_tokens") or 0)


def _router_token_total(stats: dict[str, Any]) -> int:
    return int(stats.get("totalPromptTokens") or 0) + int(stats.get("totalCompletionTokens") or 0)


def _usage_level(used: float | None, limit: float | None, warn_pct: float, critical_pct: float) -> tuple[str, float | None, float | None]:
    if used is None or limit is None or limit <= 0:
        return "unknown", None, None
    used_pct = round((used / limit) * 100.0, 2)
    remaining = max(limit - used, 0.0)
    if used_pct >= critical_pct:
        return "critical", used_pct, remaining
    if used_pct >= warn_pct:
        return "warn", used_pct, remaining
    return "ok", used_pct, remaining


def _combine_levels(levels: list[str]) -> str:
    for level in ("critical", "warn", "ok"):
        if level in levels:
            return level
    return "unknown"


def _summarize_map(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, row in value.items():
        if not isinstance(row, dict):
            continue
        prompt = int(row.get("promptTokens") or row.get("prompt_tokens") or 0)
        completion = int(row.get("completionTokens") or row.get("completion_tokens") or 0)
        rows.append({
            "name": name,
            "requests": int(row.get("requests") or row.get("count") or 0),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost_usd": round(float(row.get("cost") or row.get("cost_usd") or 0.0), 6),
            "last_used": row.get("lastUsed"),
            "provider": row.get("provider"),
            "connection_id": row.get("connectionId"),
            "account_name": row.get("accountName"),
        })
    rows.sort(key=lambda item: (item["total_tokens"], item["cost_usd"], item["requests"]), reverse=True)
    return rows[:limit]


def _normalize_provider_quota(data: dict[str, Any], connection_id: str) -> dict[str, Any]:
    token_limit = _num_from_paths(data, [
        ("token_limit",), ("tokens_limit",), ("limit_tokens",), ("limit", "tokens"),
        ("quota", "tokens", "limit"), ("quota", "limit"), ("usage", "limit"),
    ])
    token_used = _num_from_paths(data, [
        ("tokens_used",), ("used_tokens",), ("usage", "tokens"), ("usage", "used"),
        ("quota", "tokens", "used"), ("used",),
    ])
    token_remaining = _num_from_paths(data, [
        ("tokens_remaining",), ("remaining_tokens",), ("remaining", "tokens"),
        ("quota", "tokens", "remaining"), ("remaining",), ("available",),
    ])
    if token_used is None and token_limit is not None and token_remaining is not None:
        token_used = max(token_limit - token_remaining, 0.0)
    if token_limit is None and token_used is not None and token_remaining is not None:
        token_limit = token_used + token_remaining

    usd_limit = _num_from_paths(data, [
        ("usd_limit",), ("cost_limit",), ("credit_limit",), ("credits", "limit"),
        ("quota", "usd", "limit"), ("billing", "limit"),
    ])
    usd_used = _num_from_paths(data, [
        ("usd_used",), ("cost_used",), ("credits_used",), ("credits", "used"),
        ("quota", "usd", "used"), ("billing", "used"),
    ])
    usd_remaining = _num_from_paths(data, [
        ("usd_remaining",), ("cost_remaining",), ("credits_remaining",), ("credits", "remaining"),
        ("quota", "usd", "remaining"), ("billing", "remaining"), ("balance",),
    ])
    if usd_used is None and usd_limit is not None and usd_remaining is not None:
        usd_used = max(usd_limit - usd_remaining, 0.0)
    if usd_limit is None and usd_used is not None and usd_remaining is not None:
        usd_limit = usd_used + usd_remaining

    return {
        "connection_id": connection_id,
        "raw_status": data.get("status") or data.get("message") or data.get("error"),
        "tokens": {
            "used": token_used,
            "limit": token_limit,
            "remaining": token_remaining,
        },
        "usd": {
            "used": usd_used,
            "limit": usd_limit,
            "remaining": usd_remaining,
        },
        "raw_keys": sorted(str(k) for k in data.keys())[:40],
    }


def router_quota_status(
    period: str = DEFAULT_PERIOD,
    router_base_url: str | None = None,
    connection_ids: list[str] | None = None,
    timeout: float = 2.5,
) -> dict[str, Any]:
    """Return read-only quota reminders from 9Router usage APIs plus local FinOps budget fallback."""
    started = time.time()
    period = period if period in {"today", "24h", "7d", "30d", "60d", "all"} else DEFAULT_PERIOD
    warn_pct = _env_float("HARNESS_QUOTA_WARN_PCT") or DEFAULT_WARN_PCT
    critical_pct = _env_float("HARNESS_QUOTA_CRITICAL_PCT") or DEFAULT_CRITICAL_PCT
    if critical_pct < warn_pct:
        critical_pct = warn_pct

    token_limit = _env_float("HARNESS_QUOTA_MONTHLY_TOKENS")
    usd_limit = _env_float("HARNESS_QUOTA_MONTHLY_USD")
    api_key = (os.getenv("HARNESS_ROUTER_QUOTA_API_KEY") or os.getenv("ROUTER_API_KEY") or "").strip() or None
    base = _normalize_base_url(router_base_url)
    configured_connections = connection_ids or _env_list("HARNESS_ROUTER_QUOTA_CONNECTION_IDS")
    custom_endpoints = _env_list("HARNESS_ROUTER_QUOTA_ENDPOINT")

    warnings: list[str] = []
    sources: list[str] = []
    router_stats: dict[str, Any] | None = None
    router_error: str | None = None

    endpoints: list[str] = []
    if custom_endpoints:
        endpoints.extend(custom_endpoints)
    else:
        endpoints.append(f"{base}/api/usage/stats?period={urllib.parse.quote(period)}")

    for endpoint in endpoints:
        data, err = _request_json(endpoint, timeout=timeout, api_key=api_key)
        if data is not None:
            router_stats = data
            sources.append("9router_usage_api")
            break
        router_error = err
    if router_error:
        warnings.append(router_error)

    provider_quotas: list[dict[str, Any]] = []
    for connection_id in configured_connections:
        url = f"{base}/api/usage/{urllib.parse.quote(connection_id, safe='')}"
        data, err = _request_json(url, timeout=timeout, api_key=api_key)
        if data is None:
            warnings.append(err or f"failed to read {url}")
            continue
        sources.append("9router_provider_usage_api")
        provider_quotas.append(_normalize_provider_quota(data, connection_id))

    finops = get_finops_stats()
    if "error" in finops:
        warnings.append(f"finops read failed: {finops['error']}")
    else:
        sources.append("local_finops_db")

    local_used_tokens = _token_total(finops) if "error" not in finops else 0
    local_used_usd = float(finops.get("total_cost_usd") or 0.0) if "error" not in finops else 0.0
    router_used_tokens = _router_token_total(router_stats or {}) if router_stats else None
    router_used_usd = float((router_stats or {}).get("totalCost") or 0.0) if router_stats else None

    budget_used_tokens = router_used_tokens if router_used_tokens is not None else local_used_tokens
    budget_used_usd = router_used_usd if router_used_usd is not None else local_used_usd
    token_level, token_used_pct, token_remaining = _usage_level(
        float(budget_used_tokens), token_limit, warn_pct, critical_pct
    )
    usd_level, usd_used_pct, usd_remaining = _usage_level(
        float(budget_used_usd), usd_limit, warn_pct, critical_pct
    )

    provider_levels: list[str] = []
    for quota in provider_quotas:
        t = quota["tokens"]
        u = quota["usd"]
        t_level, t_pct, t_remaining = _usage_level(t.get("used"), t.get("limit"), warn_pct, critical_pct)
        u_level, u_pct, u_remaining = _usage_level(u.get("used"), u.get("limit"), warn_pct, critical_pct)
        t["used_pct"] = t_pct
        if t.get("remaining") is None:
            t["remaining"] = t_remaining
        u["used_pct"] = u_pct
        if u.get("remaining") is None:
            u["remaining"] = u_remaining
        quota["warning_level"] = _combine_levels([t_level, u_level])
        provider_levels.append(quota["warning_level"])

    level = _combine_levels([token_level, usd_level, *provider_levels])
    if level == "unknown":
        message = (
            "Chưa biết quota còn lại. Set HARNESS_QUOTA_MONTHLY_TOKENS/HARNESS_QUOTA_MONTHLY_USD "
            "hoặc HARNESS_ROUTER_QUOTA_CONNECTION_IDS để nhắc chính xác hơn."
        )
    elif level == "critical":
        message = "Quota gần cạn, nên giảm profile hoặc đổi account/model trước khi chạy batch lớn."
    elif level == "warn":
        message = "Quota đã qua ngưỡng cảnh báo, nên cân nhắc dùng profile nhẹ hoặc model low."
    else:
        message = "Quota đang ổn theo dữ liệu hiện có."

    return {
        "status": "ok",
        "warning_level": level,
        "message": message,
        "period": period,
        "source": sorted(set(sources)) or ["unknown"],
        "confidence": "high" if provider_quotas else ("medium" if (token_limit or usd_limit) else "low"),
        "thresholds": {
            "warn_pct": warn_pct,
            "critical_pct": critical_pct,
        },
        "budget": {
            "tokens": {
                "used": int(budget_used_tokens),
                "limit": int(token_limit) if token_limit is not None else None,
                "remaining": int(token_remaining) if token_remaining is not None else None,
                "used_pct": token_used_pct,
                "source": "9router_usage_api" if router_used_tokens is not None else "local_finops_db",
            },
            "usd": {
                "used": round(float(budget_used_usd), 6),
                "limit": round(float(usd_limit), 6) if usd_limit is not None else None,
                "remaining": round(float(usd_remaining), 6) if usd_remaining is not None else None,
                "used_pct": usd_used_pct,
                "source": "9router_usage_api" if router_used_usd is not None else "local_finops_db",
            },
        },
        "router": {
            "base_url": base,
            "available": router_stats is not None,
            "auth_configured": bool(_quota_auth_headers(api_key)),
            "total_requests": (router_stats or {}).get("totalRequests"),
            "total_prompt_tokens": (router_stats or {}).get("totalPromptTokens"),
            "total_completion_tokens": (router_stats or {}).get("totalCompletionTokens"),
            "total_cached_tokens": (router_stats or {}).get("totalCachedTokens"),
            "total_cost_usd": round(float((router_stats or {}).get("totalCost") or 0.0), 6) if router_stats else None,
            "top_models": _summarize_map((router_stats or {}).get("byModel")),
            "top_accounts": _summarize_map((router_stats or {}).get("byAccount")),
            "provider_quotas": provider_quotas,
        },
        "local_finops": {
            "db_available": "error" not in finops,
            "total_steps": finops.get("total_steps"),
            "total_prompt_tokens": finops.get("total_prompt_tokens"),
            "total_completion_tokens": finops.get("total_completion_tokens"),
            "total_cost_usd": finops.get("total_cost_usd"),
            "model_stats": finops.get("model_stats", [])[:12],
            "role_stats": finops.get("role_stats", [])[:12],
        },
        "warnings": warnings,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
