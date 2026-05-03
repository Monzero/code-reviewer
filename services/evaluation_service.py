from __future__ import annotations
import asyncio
import uuid
from pydantic import BaseModel
from core.audit.models import (
    AgentResultFailed, AgentResults, EvaluationRecord, InputSnapshot
)
from core.audit.writer import AuditWriter
from core.config import AppConfig
from core.llm.openai_client import OpenAIClient
from core.llm.local_client import LocalModelClient
from core.observability.logger import get_logger
from agents.objective_agent.agent import ObjectiveAgent
from agents.code_agent.agent import CodeAgent
from agents.ui_agent.agent import UIAgent
from agents.ownership_agent.agent import OwnershipAgent
from agents.aggregator.agent import AggregatorAgent
from services.repo_service import RepoService


class EvaluationRequest(BaseModel):
    project_name: str
    participant: str
    objective: str
    repo_url: str
    ui_url: str = ""


class EvaluationService:
    def __init__(self, config: AppConfig, writer: AuditWriter):
        self.config = config
        self.writer = writer
        self.repo_service = RepoService(
            max_files=config.repo.max_files,
            recent_commits=config.repo.recent_commits,
        )
        llm_cfg = config.model
        if llm_cfg.provider == "openai":
            self.llm = OpenAIClient(llm_cfg.name)
        else:
            self.llm = LocalModelClient(llm_cfg.name)

    async def evaluate(
        self, request: EvaluationRequest, judge_id: str
    ) -> EvaluationRecord:
        eval_id = str(uuid.uuid4())
        log = get_logger().bind(evaluation_id=eval_id, judge=judge_id)

        # Clone repo and pin SHA
        log.info("repo_clone_start", repo_url=request.repo_url)
        commit_sha = "unknown"
        file_contents: list[str] = []
        extra_flags: list[str] = []
        try:
            commit_sha, file_contents = await asyncio.to_thread(
                self.repo_service.clone_and_select, request.repo_url
            )
            log.info("repo_clone_end", commit_sha=commit_sha,
                     files_selected=len(file_contents))
        except Exception as exc:
            log.error("repo_clone_failed", error=str(exc))
            extra_flags.append("repo_not_accessible")

        # Run all three agents in parallel with timeout
        timeout = self.config.evaluation.agent_timeout_seconds
        objective_agent = ObjectiveAgent(self.llm)
        code_agent = CodeAgent(self.llm, self.config.evaluation.code_sub_weights)
        ui_agent = UIAgent(self.llm)
        ownership_agent = OwnershipAgent(self.llm)

        async def run_with_timeout(coro_factory, name: str):
            last_error = ""
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(coro_factory(), timeout=timeout)
                except asyncio.TimeoutError:
                    last_error = f"timeout after {timeout}s"
                    log.warning("agent_timeout", agent=name, timeout=timeout,
                                attempt=attempt + 1)
                    result = AgentResultFailed(error=last_error)
                except Exception as exc:
                    last_error = str(exc)
                    log.error("agent_error", agent=name, error=last_error,
                              attempt=attempt + 1)
                    result = AgentResultFailed(error=last_error)

                if result.status == "ok":
                    return result

                last_error = result.error
                if attempt == 0:
                    log.warning("agent_failed_retrying", agent=name, error=last_error)

            # Both attempts failed — add a user-friendly hint
            if "timeout" in last_error.lower():
                friendly = (
                    f"Timed out after {timeout}s on both attempts. "
                    "The model may be under load — you can re-run the evaluation."
                )
            else:
                friendly = f"{last_error} (failed on both attempts). You can re-run the evaluation."
            return AgentResultFailed(error=friendly)

        objective_result, code_result, ui_result, ownership_result = await asyncio.gather(
            run_with_timeout(
                lambda: objective_agent.run(
                    request.project_name, request.participant,
                    request.objective, file_contents, commit_sha
                ),
                "objective",
            ),
            run_with_timeout(
                lambda: code_agent.run(request.project_name, file_contents, commit_sha),
                "code",
            ),
            run_with_timeout(
                lambda: ui_agent.run(request.project_name, request.ui_url, file_contents),
                "ui",
            ),
            run_with_timeout(
                lambda: ownership_agent.run(
                    request.project_name, request.objective, file_contents
                ),
                "ownership",
            ),
        )

        aggregator = AggregatorAgent(
            self.config.evaluation.weights,
            self.config.evaluation.code_sub_weights,
        )
        aggregated = aggregator.aggregate(
            objective_result, code_result, ui_result, ownership_result
        )
        aggregated.flags = sorted(set(aggregated.flags + extra_flags))

        record = EvaluationRecord(
            evaluation_id=eval_id,
            triggered_by=judge_id,
            input_snapshot=InputSnapshot(
                project_name=request.project_name,
                participant=request.participant,
                objective=request.objective,
                repo_url=request.repo_url,
                repo_commit_sha=commit_sha,
                ui_url=request.ui_url,
            ),
            config_snapshot=self.config.model_dump(),
            agents=AgentResults(
                objective=objective_result,
                code=code_result,
                ui=ui_result,
                ownership=ownership_result,
            ),
            aggregated=aggregated,
        )

        await asyncio.to_thread(self.writer.insert, record)
        log.info("evaluation_complete",
                 overall_score=aggregated.overall_score, flags=aggregated.flags)
        return record
