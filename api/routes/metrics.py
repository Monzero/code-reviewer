from fastapi import APIRouter, Depends, HTTPException, status
from core.audit.writer import AuditWriter, get_writer
from api.middleware.auth import get_current_judge

router = APIRouter(tags=["metrics"])


@router.get("/metrics/summary")
def metrics_summary(
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    return writer.metrics_summary()


@router.get("/metrics/evaluation/{evaluation_id}")
def metrics_for_evaluation(
    evaluation_id: str,
    writer: AuditWriter = Depends(get_writer),
    _: str = Depends(get_current_judge),
):
    result = writer.metrics_for_evaluation(evaluation_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return result
