from __future__ import annotations
import json
from pathlib import Path
from core.llm.base import LLMClient
from core.audit.models import (
    AgentResultFailed, CodeAgentResultOk, LLMMeta, SubScore, TokenUsage
)
from core.config import CodeSubWeights
from core.observability.logger import get_logger

PROMPT_VERSION = "code_v1.0"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"


class CodeAgent:
    def __init__(self, llm: LLMClient, sub_weights: CodeSubWeights):
        self.llm = llm
        self.sub_weights = sub_weights
        self._prompt_template = _PROMPT_PATH.read_text()

    async def run(
        self,
        project_name: str,
        file_contents: list[str],
        commit_sha: str,
    ) -> CodeAgentResultOk | AgentResultFailed:
        log = get_logger().bind(agent="code", prompt_version=PROMPT_VERSION)
        prompt = self._prompt_template.format(
            project_name=project_name,
            code_files="\n\n".join(file_contents),
            commit_sha=commit_sha,
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
            sub_scores = {
                k: SubScore(score=float(v["score"]), reasoning=v["reasoning"])
                for k, v in parsed["sub_scores"].items()
            }
            weighted_score = self._weighted_score(sub_scores)
            return CodeAgentResultOk(
                score=weighted_score,
                sub_scores=sub_scores,
                reasoning=parsed["reasoning"],
                confidence=parsed["confidence"],
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

    def _weighted_score(self, sub_scores: dict[str, SubScore]) -> float:
        weights = self.sub_weights.model_dump()
        total_weight = sum(weights.get(k, 0) for k in sub_scores)
        if total_weight == 0:
            return 0.0
        score = sum(
            sub_scores[k].score * weights.get(k, 0) for k in sub_scores
        ) / total_weight
        return round(score, 2)
