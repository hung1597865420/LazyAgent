"""
Agent Harness - Support Toolbox (Backward Compatibility Shim)
All implementations have been refactored into the `tools/` package.
"""
# ruff: noqa: F401
from tools.core import (
    WORKSPACE_ROOT,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    MAX_TOTAL_BYTES_BIG,
    _git_diff,
    read_workspace_files,
    _load_wiki_context_all,
    _load_relevant_wiki_context,
    _assemble_context,
    _parse_json_findings,
    _parse_json_object,
    _result_meta,
    _calculate_review_hash,
    _export_review_report,
    _extract_and_apply_patch,
    _is_git_repo,
    _run_tests,
    _run_tests_in_dir,
    _apply_patch_in_dir,
    _apply_and_test_isolated,
    _restore_session_backups,
    _cleanup_session_backups,
    _extract_and_save_lesson,
    run_in_sandbox,
    SimpleTFIDFSearch,
    build_ast_call_graph,
    _run_cmd_safe,
    _llm_analyze
)
from tools.auto import (
    auto_trigger
)
from tools.goal import (
    goal_autopilot,
    goal_supervisor
)
from tools.prod import (
    prod_readiness_gate
)
from tools.review import (
    _SEVERITY_ORDER,
    _FAST_CTX_BYTES,
    _dedup_findings_local,
    panel_review,
    consult,
    alt_implementation
)
from tools.fix import (
    suggest_fix,
    security_autofix
)
from tools.wiki import (
    wiki_ingest,
    wiki_query,
    wiki_lint,
    doc_sync
)
from tools.testing import (
    auto_tester,
    visual_reviewer,
    benchmarker,
    coverage_analyzer
)
from tools.devops import (
    dependency_upgrader,
    devops_pipeline,
    incident_responder,
    api_contract_tester,
    chaos_tester
)
from tools.analysis import (
    schema_drift,
    telemetry_debugger,
    semantic_search,
    dead_code_scanner,
    profiler,
    secret_scanner,
    changelog_generator,
    env_parity_checker,
    load_tester,
    complexity_analyzer,
)
from tools.quality import (
    migration_validator,
    sql_query_analyzer,
    openapi_spec_sync,
    breaking_change_detector,
    flaky_test_detector,
    duplicate_code_scanner,
    container_linter,
    dependency_graph_visualizer,
    ci_pipeline_validator,
    mutation_tester,
    data_flow_taint_analyzer,
    performance_regression_detector,
)
from tools.swarm import (
    ask_codebase,
    quick_task,
    swarm_step_architect,
    swarm_step_tester,
    swarm_step_coder,
    swarm_step_apply_and_test,
    swarm_step_reviewer,
    swarm_debug
)
from tools.security import (
    config_security_audit
)
from tools.intel import (
    pr_generator,
    license_scanner,
    sbom_generator,
    a11y_auditor,
    i18n_auditor,
    polyglot_reviewer,
    git_archaeologist,
    feature_flag_auditor
)
