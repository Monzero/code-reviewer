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

        async def run_with_timeout(coro, name: str):
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                log.warning("agent_timeout", agent=name, timeout=timeout)
                return AgentResultFailed(error=f"timeout after {timeout}s")
            except Exception as exc:
                log.error("agent_error", agent=name, error=str(exc))
                return AgentResultFailed(error=str(exc))

        objective_result, code_result, ui_result = await asyncio.gather(
            run_with_timeout(
                objective_agent.run(
                    request.project_name, request.participant,
                    request.objective, file_contents, commit_sha
                ),
                "objective",
            ),
            run_with_timeout(
                code_agent.run(request.project_name, file_contents, commit_sha),
                "code",
            ),
            run_with_timeout(
                ui_agent.run(request.project_name, request.ui_url, file_contents),
                "ui",
            ),
        )

        aggregator = AggregatorAgent(
            self.config.evaluation.weights,
            self.config.evaluation.code_sub_weights,
        )
        aggregated = aggregator.aggregate(objective_result, code_result, ui_result)
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
            ),
            aggregated=aggregated,
        )

        await asyncio.to_thread(self.writer.insert, record)
        log.info("evaluation_complete",
                 overall_score=aggregated.overall_score, flags=aggregated.flags)
        return record
