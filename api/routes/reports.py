from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.audit.models import JudgeOverride
from core.audit.writer import AuditWriter, get_writer
from api.middleware.auth import get_current_judge

router = APIRouter(tags=["reports"])


@router.get("/report/{evaluation_id}")
def get_report(
    evaluation_id: str,
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    result = writer.get_with_overrides(evaluation_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    record, overrides = result
    agents_out = {}
    for name, result in record.agents.model_dump().items():
        if result.get("status") == "ok":
            agents_out[name] = {k: v for k, v in result.items() if k != "raw_llm_response"}
        else:
            agents_out[name] = result
    return {
        "evaluation_id": record.evaluation_id,
        "created_at": record.created_at,
        "triggered_by": record.triggered_by,
        "input_snapshot": record.input_snapshot,
        "aggregated": record.aggregated,
        "agents": agents_out,
        "judge_overrides": overrides,
        "judge_notes": record.judge_notes,
    }


@router.get("/report/{evaluation_id}/provenance")
def get_provenance(
    evaluation_id: str,
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    record = writer.get(evaluation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    agents_provenance = {}
    for name, result in record.agents.model_dump().items():
        if result.get("status") == "ok":
            agents_provenance[name] = {
                "llm": result["llm"],
                "prompt_version": result["prompt_version"],
                "tokens": result["tokens"],
                "latency_ms": result["latency_ms"],
                "confidence": result["confidence"],
            }
        else:
            agents_provenance[name] = {"status": "failed", "error": result.get("error")}
    return {
        "evaluation_id": record.evaluation_id,
        "system_version": record.system_version,
        "created_at": record.created_at,
        "triggered_by": record.triggered_by,
        "re_evaluated_from": record.re_evaluated_from,
        "input_snapshot": record.input_snapshot,
        "config_snapshot": record.config_snapshot,
        "agents": agents_provenance,
    }


@router.get("/report/{evaluation_id}/raw")
def get_raw(
    evaluation_id: str,
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    record = writer.get(evaluation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    raw = {}
    for name, result in record.agents.model_dump().items():
        raw[name] = result.get("raw_llm_response") if result.get("status") == "ok" else None
    return {"evaluation_id": evaluation_id, "raw_responses": raw}


@router.get("/evaluations")
def list_evaluations(
    judge: str | None = None,
    date: str | None = None,
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    return writer.list_evaluations(judge=judge, date=date)


class OverrideRequest(BaseModel):
    agent: str
    original_score: float
    override_score: float
    reason: str


@router.post("/report/{evaluation_id}/override", status_code=status.HTTP_201_CREATED)
def submit_override(
    evaluation_id: str,
    body: OverrideRequest,
    judge_id: str = Depends(get_current_judge),
    writer: AuditWriter = Depends(get_writer),
):
    override = JudgeOverride(
        agent=body.agent,
        original_score=body.original_score,
        override_score=body.override_score,
        reason=body.reason,
        overridden_by=judge_id,
    )
    if not writer.append_override(evaluation_id, override):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return {"status": "override recorded"}
