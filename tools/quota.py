"""Deprecated quota compatibility module.

The router quota/costguard feature was removed. This module only preserves the
old import path for callers that used ``tools.quota.router_quota_status``.
"""
from __future__ import annotations

from .ops import router_quota_status

__all__ = ["router_quota_status"]
