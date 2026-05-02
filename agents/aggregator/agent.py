from __future__ import annotations
from core.audit.models import (
    AgentResultFailed, AgentResultOk, AggregatedResult,
    CodeAgentResultOk, FlatAgentResult, CodeAgentResult
)
from core.config import EvaluationWeights, CodeSubWeights


class AggregatorAgent:
    def __init__(self, weights: EvaluationWeights, code_sub_weights: CodeSubWeights):
        self.weights = weights.model_dump()
        self.code_sub_weights = code_sub_weights

    def aggregate(
        self,
        objective: FlatAgentResult,
        code: CodeAgentResult,
        ui: FlatAgentResult,
    ) -> AggregatedResult:
        named = {"objective": objective, "code": code, "ui": ui}
        scores: dict[str, float | None] = {}
        flags: list[str] = []

        for name, result in named.items():
            if isinstance(result, AgentResultFailed):
                scores[name] = None
                flags.append(f"{name}_agent_failed")
            else:
                scores[name] = result.score
                if result.confidence == "low":
                    flags.append("low_confidence")
                # Security check: any security sub-score < 5 bubbles up
                if isinstance(result, CodeAgentResultOk):
                    sec = result.sub_scores.get("security")
                    if sec and sec.score < 5:
                        flags.append("security_issue_detected")

        # High inter-agent disagreement
        live_scores = [v for v in scores.values() if v is not None]
        if len(live_scores) >= 2 and (max(live_scores) - min(live_scores)) > 4:
            flags.append("high_agent_disagreement")

        # Reweight proportionally over available agents
        available_weight = sum(
            self.weights[k] for k, v in scores.items() if v is not None
        )
        if available_weight == 0:
            overall = None
        else:
            overall = round(
                sum(
                    scores[k] * self.weights[k]
                    for k in scores
                    if scores[k] is not None
                )
                / available_weight,
                2,
            )

        parts = []
        for name in ("objective", "code", "ui"):
            v = scores[name]
            parts.append(f"{name.title()}: {v}/10" if v is not None else f"{name.title()}: N/A (failed)")
        summary = " | ".join(parts)
        if flags:
            summary += " | Flags: " + ", ".join(sorted(set(flags)))

        return AggregatedResult(
            overall_score=overall,
            objective_score=scores["objective"],
            code_score=scores["code"],
            ui_score=scores["ui"],
            weights_used=self.weights,
            summary=summary,
            flags=sorted(set(flags)),
        )
