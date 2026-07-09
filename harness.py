"""
Agent Harness - Orchestrator (10-Agent Coding Pipeline)

Pipeline (Manager quyết định stages):
  Stage 1: Analyzer         — understand & design
  Stage 2: Code A + Code B  — parallel implementation
  Stage 3: Reviewer + Tester + Security  — parallel review
  Stage 4: Debugger         — apply all fixes
  Stage 5: Worker           — cleanup (optional)
  Final:   Synthesizer      — merge into final output
"""
import asyncio
import json
import re
import uuid
import time
from typing import Callable, Awaitable
from pydantic import BaseModel
from agents import Agent, AgentRole, AgentResult
from config import get_azure_client, MODELS


class HarnessRun(BaseModel):
    run_id:            str
    original_task:     str
    manager_plan:      dict
    agent_results:     list[AgentResult]
    final_summary:     str
    total_duration_ms: int
    status:            str
    error:             str = ""


ProgressCallback = Callable[[str, str], Awaitable[None]]

STR_TO_ROLE: dict[str, AgentRole] = {
    "manager":     AgentRole.MANAGER,
    "synthesizer": AgentRole.SYNTHESIZER,
    "analyzer":    AgentRole.ANALYZER,
    "code_a":      AgentRole.CODE_A,
    "code_b":      AgentRole.CODE_B,
    "reviewer":    AgentRole.REVIEWER,
    "tester":      AgentRole.TESTER,
    "security":    AgentRole.SECURITY,
    "debugger":    AgentRole.DEBUGGER,
    "worker":      AgentRole.WORKER,
}

# Prompt riêng cho pipeline mode — prompt mặc định trong agents.py giờ phục vụ
# support toolbox (MCP), Manager/Synthesizer ở đó làm việc khác hẳn.

PIPELINE_MANAGER_PROMPT = """Bạn là Manager Agent — trưởng nhóm 10-agent coding team.
Nhiệm vụ DUY NHẤT: phân tích task và lập execution plan. KHÔNG tự code.

Trả về JSON thuần (không markdown fence):
{
  "analysis": "task là gì, yêu cầu gì",
  "stages": [
    {
      "stage": 1,
      "parallel": true,
      "agents": [
        {"role": "analyzer|code_a|code_b|reviewer|tester|security|debugger|worker",
         "task": "mô tả task cụ thể cho agent này"}
      ]
    }
  ],
  "synthesis_instruction": "hướng dẫn tổng hợp output cuối"
}

Pipeline chuẩn cho coding task:
  Stage 1: [analyzer] — hiểu requirements, design approach
  Stage 2: [code_a, code_b] — parallel implementation
  Stage 3: [reviewer, tester, security] — parallel review
  Stage 4: [debugger] — fix issues
  Stage 5: [worker] — cleanup, docs (nếu cần)

Rút gọn pipeline nếu task đơn giản (ví dụ: chỉ cần [code_a] + [reviewer])."""

PIPELINE_SYNTHESIZER_PROMPT = """Bạn là Synthesizer Agent — viết output CUỐI CÙNG hoàn chỉnh.
Nhận kết quả từ toàn bộ team, merge thành document professional.

Format output:
## 📦 Implementation
[code hoàn chỉnh, đã apply fixes từ debugger]

## 🧪 Tests
[test cases từ tester]

## 🔐 Security Notes
[findings từ security agent]

## 📝 Review Notes
[key insights từ reviewer]

Ưu tiên: Code từ Debugger > Code A > Code B (Debugger đã fix rồi nên dùng cái đó)."""


class AgentHarness:
    """
    10-Agent Coding Pipeline Orchestrator.
    Manager creates a stage-based plan, stages run sequentially,
    agents within each stage run in parallel.
    """

    def __init__(self, progress_callback: ProgressCallback | None = None):
        self.client      = get_azure_client()
        self.progress_cb = progress_callback

    async def _emit(self, event: str, message: str):
        if self.progress_cb:
            await self.progress_cb(event, message)

    # ── Main entry ────────────────────────────────────────────────────────────

    async def run(self, user_task: str) -> HarnessRun:
        run_id     = str(uuid.uuid4())[:12]
        start_time = time.time()

        await self._emit("start", f"🚀 {user_task[:100]}...")

        # ── Manager: lập kế hoạch ─────────────────────────────────────────────
        await self._emit("planning", f"🧠 Manager ({MODELS.manager}) đang lập kế hoạch...")
        manager    = Agent(AgentRole.MANAGER, self.client,
                           system_prompt=PIPELINE_MANAGER_PROMPT)
        mgr_result = await manager.run_async(user_task)

        if mgr_result.status == "error":
            return self._error_run(run_id, user_task, mgr_result, start_time)

        plan   = self._parse_plan(mgr_result.result)
        stages = plan.get("stages", self._default_stages(user_task))

        await self._emit("plan_ready",
            f"📋 {len(stages)} stage(s) | "
            f"{sum(len(s.get('agents', [])) for s in stages)} agent tasks"
        )

        # ── Execute stages ────────────────────────────────────────────────────
        all_results: list[AgentResult] = [mgr_result]
        accumulated_context             = f"Original task: {user_task}"

        for stage_data in stages:
            stage_num  = stage_data.get("stage", "?")
            agents_def = stage_data.get("agents", [])
            is_parallel = stage_data.get("parallel", True)

            if not agents_def:
                continue

            names = [a.get("role", "?") for a in agents_def]
            await self._emit("stage",
                f"▶ Stage {stage_num}: [{', '.join(names)}] "
                f"({'parallel' if is_parallel else 'sequential'})"
            )

            if is_parallel:
                coroutines = [
                    Agent(STR_TO_ROLE.get(a["role"], AgentRole.WORKER), self.client)
                    .run_async(a.get("task", user_task), accumulated_context)
                    for a in agents_def
                    if a.get("role") in STR_TO_ROLE
                ]
                results: list[AgentResult] = list(await asyncio.gather(*coroutines))
            else:
                results = []
                for a in agents_def:
                    role   = STR_TO_ROLE.get(a.get("role", ""), AgentRole.WORKER)
                    agent  = Agent(role, self.client)
                    result = await agent.run_async(a.get("task", user_task), accumulated_context)
                    results.append(result)

            for r in results:
                icon = "✅" if r.status == "success" else "❌"
                await self._emit("agent_done",
                    f"{icon} [{r.agent_role}] {r.model_used} — {r.duration_ms}ms"
                )
                all_results.append(r)

            # Cộng dồn context cho stage tiếp theo
            accumulated_context += "\n\n" + self._format_results(results)

        # ── Synthesizer tổng hợp ──────────────────────────────────────────────
        await self._emit("synthesizing", f"🔗 Synthesizer ({MODELS.synthesizer})...")

        synth_instruction = plan.get(
            "synthesis_instruction",
            "Tổng hợp tất cả output thành kết quả cuối hoàn chỉnh, professional."
        )
        synthesizer  = Agent(AgentRole.SYNTHESIZER, self.client,
                             system_prompt=PIPELINE_SYNTHESIZER_PROMPT)
        synth_result = await synthesizer.run_async(
            synth_instruction,
            extra_context=self._build_synthesis_context(all_results, user_task)
        )
        all_results.append(synth_result)

        final     = synth_result.result if synth_result.status == "success" \
                    else accumulated_context
        total_ms  = int((time.time() - start_time) * 1000)
        n_agents  = len(all_results)

        await self._emit("done",
            f"✅ Done! {n_agents} agent calls | {total_ms}ms total"
        )

        return HarnessRun(
            run_id=run_id,             original_task=user_task,
            manager_plan=plan,         agent_results=all_results,
            final_summary=final,       total_duration_ms=total_ms,
            status="success",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _default_stages(self, task: str) -> list[dict]:
        """Fallback pipeline khi Manager không trả JSON hợp lệ"""
        return [
            {"stage": 1, "parallel": False, "agents": [
                {"role": "analyzer", "task": f"Phân tích và design approach cho: {task}"}
            ]},
            {"stage": 2, "parallel": True, "agents": [
                {"role": "code_a", "task": task},
                {"role": "code_b", "task": task},
            ]},
            {"stage": 3, "parallel": True, "agents": [
                {"role": "reviewer", "task": "Review code từ Code A và Code B"},
                {"role": "tester",   "task": "Viết tests cho code"},
                {"role": "security", "task": "Security audit code"},
            ]},
            {"stage": 4, "parallel": False, "agents": [
                {"role": "debugger", "task": "Apply tất cả fixes từ reviewer, tester, security"}
            ]},
        ]

    def _parse_plan(self, raw: str) -> dict:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            s, e = raw.find("{"), raw.rfind("}") + 1
            if s != -1 and e > s:
                return json.loads(raw[s:e])
        except Exception:
            pass
        return {"stages": self._default_stages(""), "synthesis_instruction": "Tổng hợp kết quả."}

    def _format_results(self, results: list[AgentResult]) -> str:
        parts = []
        for r in results:
            if r.status == "success" and r.result:
                parts.append(f"[{r.agent_role.upper()} — {r.model_used}]\n{r.result}")
        return "\n\n---\n\n".join(parts)

    def _build_synthesis_context(self, results: list[AgentResult], task: str) -> str:
        parts = [f"# Original Task\n{task}"]
        for r in results:
            if r.status == "success" and r.result and r.agent_role != AgentRole.MANAGER:
                parts.append(
                    f"## {r.agent_role.upper()} [{r.model_used}] — {r.duration_ms}ms\n{r.result}"
                )
        return "\n\n---\n\n".join(parts)

    def _error_run(self, run_id, task, result, start_time) -> HarnessRun:
        return HarnessRun(
            run_id=run_id,             original_task=task,
            manager_plan={},           agent_results=[result],
            final_summary=f"❌ {result.error}",
            total_duration_ms=int((time.time() - start_time) * 1000),
            status="error",            error=result.error,
        )
