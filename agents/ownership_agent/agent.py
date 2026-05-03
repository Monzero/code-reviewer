from __future__ import annotations
import json
from pathlib import Path
from core.llm.base import LLMClient
from core.audit.models import (
    AgentResultFailed, LLMMeta, OwnershipAgentResultOk, KeyDecision, TokenUsage
)
from core.observability.logger import get_logger

PROMPT_VERSION = "ownership_v1.0"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"


class OwnershipAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._prompt_template = _PROMPT_PATH.read_text()

    async def run(
        self,
        project_name: str,
        objective: str,
        file_contents: list[str],
    ) -> OwnershipAgentResultOk | AgentResultFailed:
        log = get_logger().bind(agent="ownership", prompt_version=PROMPT_VERSION)
        prompt = self._prompt_template.format(
            project_name=project_name,
            objective=objective,
            code_files="\n\n".join(file_contents),
        )
        log.info("llm_call_start")
        try:
            llm_resp = await self.llm.generate(prompt)
        except Exception as exc:
            log.error("llm_call_failed", error=str(exc))
            return AgentResultFailed(error=str(exc))

        log.info("llm_call_end", latency_ms=llm_resp.latency_ms,
                 tokens_output=llm_resp.tokens_output)
        try:
            parsed = json.loads(llm_resp.text)
            key_decisions = [
                KeyDecision(
                    decision=d["decision"],
                    ownership_signal=d["ownership_signal"],
                    question=d["question"],
                )
                for d in parsed.get("key_decisions", [])
            ]
            return OwnershipAgentResultOk(
                score=float(parsed["score"]),
                reasoning=parsed["reasoning"],
                confidence=parsed["confidence"],
                key_decisions=key_decisions,
                llm=LLMMeta(
                    provider=self.llm.provider,
                    model=self.llm.model,
                    model_version=llm_resp.model_version,
                ),
                prompt_version=PROMPT_VERSION,
                tokens=TokenUsage(
                    input=llm_resp.tokens_input, output=llm_resp.tokens_output
                ),
                latency_ms=llm_resp.latency_ms,
                raw_llm_response=llm_resp.text,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.error("parse_failed", error=str(exc))
            return AgentResultFailed(error=f"Failed to parse LLM response: {exc}")
