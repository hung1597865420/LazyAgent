"""Smoke-test the local 9Router OpenAI-compatible connection."""
from __future__ import annotations

from dotenv import load_dotenv

from config import get_llm_client


def main() -> None:
    load_dotenv()
    client = get_llm_client()
    response = client.chat.completions.create(
        model="ag/gemini-3.5-flash-extra-low",
        messages=[{"role": "user", "content": "Reply with only: OK"}],
        max_completion_tokens=8,
        temperature=0,
    )
    print(response.choices[0].message.content or "")


if __name__ == "__main__":
    main()
