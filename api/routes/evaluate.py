from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from core.audit.writer import AuditWriter, get_writer
from core.config import config
from api.middleware.auth import get_current_judge
from services.evaluation_service import EvaluationRequest, EvaluationService

router = APIRouter(tags=["evaluation"])
limiter = Limiter(key_func=get_remote_address)

_ALLOWED_SCHEMES = ("https://", "http://")


def _validate_url(url: str, field: str) -> None:
    if not any(url.startswith(s) for s in _ALLOWED_SCHEMES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be a valid http/https URL",
        )


@router.post("/evaluate")
@limiter.limit(f"{config.security.rate_limit_per_minute}/minute")
async def evaluate(
    request: Request,
    body: EvaluationRequest,
    judge_id: str = Depends(get_current_judge),
    writer: AuditWriter = Depends(get_writer),
):
    _validate_url(body.repo_url, "repo_url")
    if body.ui_url:
        _validate_url(body.ui_url, "ui_url")

    service = EvaluationService(config, writer)
    record = await service.evaluate(body, judge_id)
    agents_out = {}
    for name, result in record.agents.model_dump().items():
        if result.get("status") == "ok":
            agents_out[name] = {k: v for k, v in result.items() if k != "raw_llm_response"}
        else:
            agents_out[name] = result
    return {
        "evaluation_id": record.evaluation_id,
        "report": record.aggregated,
        "agents": agents_out,
    }
