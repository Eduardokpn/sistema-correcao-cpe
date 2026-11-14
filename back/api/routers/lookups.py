"""Lists the dashboard uses to fill its filters."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api import schemas
from api.deps import get_db
from db import repositories as repo

router = APIRouter()


@router.get("/classes", response_model=List[schemas.ClassOut])
def list_classes(db: Session = Depends(get_db)):
    return [
        schemas.ClassOut(id=c.id, name=c.name, turno=c.turno)
        for c in repo.list_classes(db)
    ]

@router.get("/students", response_model=List[schemas.StudentOut])
def list_students(
    class_id: Optional[int] = Query(default=None), db: Session = Depends(get_db)
):
    return [
        schemas.StudentOut(id=s.id, name=s.name, class_id=s.class_id)
        for s in repo.list_students(db, class_id=class_id)
    ]

@router.get("/subjects", response_model=List[schemas.SubjectOut])
def list_subjects(db: Session = Depends(get_db)):
    return [
        schemas.SubjectOut(id=s.id, name=s.name)
        for s in repo.list_subjects(db)
    ]
