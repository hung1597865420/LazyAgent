"""
tools package - lazy re-exports for harness tools.

Optional integrations must not be imported just because a caller needs one core
tool.  This keeps hooks and smoke checks usable on minimal installations.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "run_in_sandbox": ("tools.core", "run_in_sandbox"),
    "lesson_curator": ("tools.core", "lesson_curator"),
    "auto_trigger": ("tools.auto", "auto_trigger"),
    "preflight_trigger": ("tools.lifecycle", "preflight_trigger"),
    "tool_lifecycle": ("tools.lifecycle", "tool_lifecycle"),
    "active_sessions": ("tools.coordination", "active_sessions"),
    "claim_files": ("tools.coordination", "claim_files"),
    "conflict_check": ("tools.coordination", "conflict_check"),
    "coordination_advisor": ("tools.coordination", "coordination_advisor"),
    "coordination_events": ("tools.coordination", "coordination_events"),
    "coordination_policy": ("tools.coordination", "coordination_policy"),
    "coordination_status": ("tools.coordination", "coordination_status"),
    "record_file_event": ("tools.coordination", "record_file_event"),
    "release_files": ("tools.coordination", "release_files"),
    "session_heartbeat": ("tools.coordination", "session_heartbeat"),
    "takeover_stale_claim": ("tools.coordination", "takeover_stale_claim"),
    "goal_autopilot": ("tools.goal", "goal_autopilot"),
    "goal_supervisor": ("tools.goal", "goal_supervisor"),
    "hallmark_bridge": ("tools.integrations", "hallmark_bridge"),
    "integration_router": ("tools.integrations", "integration_router"),
    "ui_skill_router": ("tools.integrations", "ui_skill_router"),
    "speckit_bridge": ("tools.integrations", "speckit_bridge"),
    "workflow_router": ("tools.workflow", "workflow_router"),
    "bug_repro_guard": ("tools.workflow", "bug_repro_guard"),
    "office_bridge": ("tools.office_bridge", "office_bridge"),
    "scope_creep_detector": ("tools.scope_guard", "scope_creep_detector"),
    "goal_runner": ("tools.runner", "goal_runner"),
    "agent_adapters": ("tools.ops", "agent_adapters"),
    "ask_codebase_health": ("tools.ops", "ask_codebase_health"),
    "benchmark_runner": ("tools.ops", "benchmark_runner"),
    "context_auditor": ("tools.ops", "context_auditor"),
    "goal_runner_control": ("tools.ops", "goal_runner_control"),
    "harness_doctor": ("tools.ops", "harness_doctor"),
    "patch_safety_check": ("tools.ops", "patch_safety_check"),
    "policy_profile": ("tools.ops", "policy_profile"),
    "router_quota_status": ("tools.ops", "router_quota_status"),
    "run_ledger": ("tools.ops", "run_ledger"),
    "prod_readiness_gate": ("tools.prod", "prod_readiness_gate"),
    "release_orchestrator": ("tools.gap_tools", "release_orchestrator"),
    "provenance_checker": ("tools.gap_tools", "provenance_checker"),
    "auth_matrix_auditor": ("tools.gap_tools", "auth_matrix_auditor"),
    "harness_trace_viewer": ("tools.gap_tools", "harness_trace_viewer"),
    "incremental_refactor_guard": ("tools.gap_tools", "incremental_refactor_guard"),
    "panel_review": ("tools.review", "panel_review"),
    "consult": ("tools.review", "consult"),
    "alt_implementation": ("tools.review", "alt_implementation"),
    "suggest_fix": ("tools.fix", "suggest_fix"),
    "security_autofix": ("tools.fix", "security_autofix"),
    "wiki_ingest": ("tools.wiki", "wiki_ingest"),
    "wiki_query": ("tools.wiki", "wiki_query"),
    "wiki_lint": ("tools.wiki", "wiki_lint"),
    "doc_sync": ("tools.wiki", "doc_sync"),
    "auto_tester": ("tools.testing", "auto_tester"),
    "benchmarker": ("tools.testing", "benchmarker"),
    "visual_reviewer": ("tools.testing", "visual_reviewer"),
    "coverage_analyzer": ("tools.testing", "coverage_analyzer"),
    "devops_pipeline": ("tools.devops", "devops_pipeline"),
    "dependency_upgrader": ("tools.devops", "dependency_upgrader"),
    "incident_responder": ("tools.devops", "incident_responder"),
    "api_contract_tester": ("tools.devops", "api_contract_tester"),
    "chaos_tester": ("tools.devops", "chaos_tester"),
    "schema_drift": ("tools.analysis", "schema_drift"),
    "telemetry_debugger": ("tools.analysis", "telemetry_debugger"),
    "semantic_search": ("tools.analysis", "semantic_search"),
    "dead_code_scanner": ("tools.analysis", "dead_code_scanner"),
    "profiler": ("tools.analysis", "profiler"),
    "secret_scanner": ("tools.analysis", "secret_scanner"),
    "changelog_generator": ("tools.analysis", "changelog_generator"),
    "env_parity_checker": ("tools.analysis", "env_parity_checker"),
    "load_tester": ("tools.analysis", "load_tester"),
    "complexity_analyzer": ("tools.analysis", "complexity_analyzer"),
    "index_codebase": ("tools.analysis", "index_codebase"),
    "review_context_graph": ("tools.graph_review", "review_context_graph"),
    "graph_health": ("tools.graph_review", "graph_health"),
    "graph_minimal_context": ("tools.graph_review", "graph_minimal_context"),
    "swarm_debug": ("tools.swarm", "swarm_debug"),
    "ask_codebase": ("tools.swarm", "ask_codebase"),
    "quick_task": ("tools.swarm", "quick_task"),
    "config_security_audit": ("tools.security", "config_security_audit"),
    "pr_generator": ("tools.intel", "pr_generator"),
    "license_scanner": ("tools.intel", "license_scanner"),
    "sbom_generator": ("tools.intel", "sbom_generator"),
    "a11y_auditor": ("tools.intel", "a11y_auditor"),
    "i18n_auditor": ("tools.intel", "i18n_auditor"),
    "polyglot_reviewer": ("tools.intel", "polyglot_reviewer"),
    "git_archaeologist": ("tools.intel", "git_archaeologist"),
    "feature_flag_auditor": ("tools.intel", "feature_flag_auditor"),
    "migration_validator": ("tools.quality", "migration_validator"),
    "sql_query_analyzer": ("tools.quality", "sql_query_analyzer"),
    "openapi_spec_sync": ("tools.quality", "openapi_spec_sync"),
    "breaking_change_detector": ("tools.quality", "breaking_change_detector"),
    "flaky_test_detector": ("tools.quality", "flaky_test_detector"),
    "duplicate_code_scanner": ("tools.quality", "duplicate_code_scanner"),
    "container_linter": ("tools.quality", "container_linter"),
    "dependency_graph_visualizer": ("tools.quality", "dependency_graph_visualizer"),
    "ci_pipeline_validator": ("tools.quality", "ci_pipeline_validator"),
    "mutation_tester": ("tools.quality", "mutation_tester"),
    "data_flow_taint_analyzer": ("tools.quality", "data_flow_taint_analyzer"),
    "performance_regression_detector": ("tools.quality", "performance_regression_detector"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
