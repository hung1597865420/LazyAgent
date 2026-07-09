"""Live test — ping tất cả deployment qua endpoint thật để verify tên + auth."""
# ruff: noqa: E402
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from agents import Agent, AgentRole, chat_completion
from config import SPARE_MODELS, get_azure_client

PING = "Trả lời đúng một từ: pong"


async def ping_role(role: AgentRole) -> tuple[str, str, str, str]:
    r = await Agent(role).run_async(PING, max_output_tokens=512)
    detail = (r.result or "").strip()[:60] if r.status == "success" else r.error[:200]
    return role.value, r.model_used, r.status, detail


async def ping_spare(model: str) -> tuple[str, str, str, str]:
    def call():
        client = get_azure_client()
        text, used, _, _ = chat_completion(
            client, model,
            [{"role": "user", "content": PING}],
            max_output_tokens=512,
        )
        return text
    try:
        text = await asyncio.to_thread(call)
        return "spare", model, "success", (text or "").strip()[:60]
    except Exception as e:
        return "spare", model, "error", f"{type(e).__name__}: {e}"[:200]


async def main():
    tasks = [ping_role(r) for r in AgentRole] + [ping_spare(m) for m in SPARE_MODELS]
    results = await asyncio.gather(*tasks)

    ok = sum(1 for _, _, s, _ in results if s == "success")
    print(f"{'ROLE':<13} {'DEPLOYMENT':<22} {'STATUS':<8} DETAIL")
    print("-" * 90)
    for role, model, status, detail in results:
        icon = "✅" if status == "success" else "❌"
        print(f"{role:<13} {model:<22} {icon} {status:<6} {detail}")
    print("-" * 90)
    print(f"{ok}/{len(results)} deployments hoạt động")


if __name__ == "__main__":
    asyncio.run(main())
