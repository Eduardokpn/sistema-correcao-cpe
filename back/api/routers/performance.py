"""The four teacher questions: performance summaries and the class trend."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api import schemas
from api.deps import get_db
from db import repositories as repo

router = APIRouter()


@router.get("/performance/student-subject", response_model=schemas.PerformanceOut)
def student_subject(
    student_id: int, subject_id: int, db: Session = Depends(get_db)
):
    summary = repo.student_performance_in_subject(db, student_id, subject_id)
    return _performance_out(summary)

@router.get("/performance/student-exam", response_model=schemas.PerformanceOut)
def student_exam(student_id: int, exam_id: int, db: Session = Depends(get_db)):
    summary = repo.student_performance_in_exam(db, student_id, exam_id)
    return _performance_out(summary)

@router.get("/performance/class-exam", response_model=schemas.PerformanceOut)
def class_exam(class_id: int, exam_id: int, db: Session = Depends(get_db)):
    summary = repo.class_performance_in_exam(db, class_id, exam_id)
    return _performance_out(summary)

@router.get("/trends/class/{class_id}", response_model=schemas.TrendOut)
def class_trend(class_id: int, db: Session = Depends(get_db)):
    points = repo.class_improvement_over_time(db, class_id)
    return schemas.TrendOut(
        class_id=class_id,
        points=[
            schemas.SubjectTrendPoint(
                exam_id=p.exam_id,
                exam_name=p.exam_name,
                applied_on=p.applied_on,
                sequence=p.sequence,
                overall=_performance_out(p.summary),
                by_subject=p.by_subject,
            )
            for p in points
        ],
    )


def _performance_out(summary: repo.PerformanceSummary) -> schemas.PerformanceOut:
    return schemas.PerformanceOut(
        total=summary.total,
        acertos=summary.acertos,
        erros=summary.erros,
        em_branco=summary.em_branco,
        taxa_acerto=summary.taxa_acerto,
    )
