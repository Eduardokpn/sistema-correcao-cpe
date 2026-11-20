"""The long-format rows the dashboard charts consume."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api import schemas
from api.deps import get_db
from db import repositories as repo
from db.repositories import LONG_FORMAT_COLUMNS

router = APIRouter()


@router.get("/results", response_model=schemas.ResultsOut)
def get_results(
    exam_id: Optional[int] = Query(default=None),
    class_id: Optional[int] = Query(default=None),
    student_id: Optional[int] = Query(default=None),
    subject_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    rows = repo.long_format_rows(
        db,
        exam_id=exam_id,
        class_id=class_id,
        student_id=student_id,
        subject_id=subject_id,
    )
    return schemas.ResultsOut(columns=LONG_FORMAT_COLUMNS, rows=rows)
