from __future__ import annotations
from datetime import datetime
import json
from typing import Optional
from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .models import EvaluationRecord, JudgeOverride


class Base(DeclarativeBase):
    pass


class EvaluationRow(Base):
    __tablename__ = "evaluations"

    evaluation_id = Column(String, primary_key=True)
    created_at = Column(DateTime, nullable=False)
    triggered_by = Column(String, nullable=False, index=True)
    project_name = Column(String, nullable=False, index=True)
    participant = Column(String, nullable=False)
    overall_score = Column(Float, nullable=True)
    flags = Column(Text, nullable=False)     # JSON array
    record_json = Column(Text, nullable=False)  # full immutable record blob


class OverrideRow(Base):
    __tablename__ = "overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(
        String, ForeignKey("evaluations.evaluation_id"), nullable=False, index=True
    )
    agent = Column(String, nullable=False)
    original_score = Column(Float, nullable=False)
    override_score = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    overridden_by = Column(String, nullable=False)
    overridden_at = Column(DateTime, nullable=False)


class AuditWriter:
    def __init__(self, db_url: str):
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        self.engine = create_engine(db_url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)

    def insert(self, record: EvaluationRecord) -> None:
        with self._Session() as session:
            row = EvaluationRow(
                evaluation_id=record.evaluation_id,
                created_at=record.created_at,
                triggered_by=record.triggered_by,
                project_name=record.input_snapshot.project_name,
                participant=record.input_snapshot.participant,
                overall_score=record.aggregated.overall_score,
                flags=json.dumps(record.aggregated.flags),
                record_json=record.model_dump_json(),
            )
            session.add(row)
            session.commit()

    def get(self, evaluation_id: str) -> Optional[EvaluationRecord]:
        with self._Session() as session:
            row = session.get(EvaluationRow, evaluation_id)
            if not row:
                return None
            return EvaluationRecord.model_validate_json(row.record_json)

    def get_with_overrides(
        self, evaluation_id: str
    ) -> Optional[tuple[EvaluationRecord, list[JudgeOverride]]]:
        with self._Session() as session:
            row = session.get(EvaluationRow, evaluation_id)
            if not row:
                return None
            record = EvaluationRecord.model_validate_json(row.record_json)
            override_rows = (
                session.query(OverrideRow)
                .filter_by(evaluation_id=evaluation_id)
                .all()
            )
            overrides = [
                JudgeOverride(
                    agent=o.agent,
                    original_score=o.original_score,
                    override_score=o.override_score,
                    reason=o.reason,
                    overridden_by=o.overridden_by,
                    overridden_at=o.overridden_at,
                )
                for o in override_rows
            ]
            return record, overrides

    def append_override(self, evaluation_id: str, override: JudgeOverride) -> bool:
        with self._Session() as session:
            if not session.get(EvaluationRow, evaluation_id):
                return False
            session.add(
                OverrideRow(
                    evaluation_id=evaluation_id,
                    agent=override.agent,
                    original_score=override.original_score,
                    override_score=override.override_score,
                    reason=override.reason,
                    overridden_by=override.overridden_by,
                    overridden_at=override.overridden_at,
                )
            )
            session.commit()
            return True

    def list_evaluations(
        self, judge: str | None = None, date: str | None = None, limit: int = 50
    ) -> list[dict]:
        with self._Session() as session:
            q = session.query(EvaluationRow)
            if judge:
                q = q.filter(EvaluationRow.triggered_by == judge)
            if date:
                try:
                    d = datetime.strptime(date, "%Y-%m-%d")
                    q = q.filter(EvaluationRow.created_at >= d)
                except ValueError:
                    pass
            rows = q.order_by(EvaluationRow.created_at.desc()).limit(limit).all()
            return [
                {
                    "evaluation_id": r.evaluation_id,
                    "created_at": r.created_at.isoformat(),
                    "triggered_by": r.triggered_by,
                    "project_name": r.project_name,
                    "participant": r.participant,
                    "overall_score": r.overall_score,
                    "flags": json.loads(r.flags),
                }
                for r in rows
            ]

    def metrics_summary(self) -> dict:
        with self._Session() as session:
            total = session.query(EvaluationRow).count()
            override_total = session.query(OverrideRow).count()
            scores = [
                r.overall_score
                for r in session.query(EvaluationRow).all()
                if r.overall_score is not None
            ]
            return {
                "total_evaluations": total,
                "total_overrides": override_total,
                "override_rate": round(override_total / total, 3) if total else 0,
                "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
                "min_score": min(scores) if scores else None,
                "max_score": max(scores) if scores else None,
            }

    def metrics_for_evaluation(self, evaluation_id: str) -> Optional[dict]:
        record = self.get(evaluation_id)
        if not record:
            return None
        agents = record.agents.model_dump()
        breakdown = {}
        for name, result in agents.items():
            if result.get("status") == "ok":
                breakdown[name] = {
                    "latency_ms": result.get("latency_ms"),
                    "tokens": result.get("tokens"),
                    "model_version": result.get("llm", {}).get("model_version"),
                    "prompt_version": result.get("prompt_version"),
                }
        return {"evaluation_id": evaluation_id, "agents": breakdown}


_writer: AuditWriter | None = None


def get_writer() -> AuditWriter:
    global _writer
    if _writer is None:
        from core.config import config
        _writer = AuditWriter(config.database.get_url())
    return _writer
