"""Exams and their gabarito."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api import schemas
from api.deps import get_db
from db import repositories as repo
from grading import artifacts

router = APIRouter()


@router.post("/exams", response_model=schemas.ExamOut)
def create_exam(payload: schemas.ExamIn, db: Session = Depends(get_db)):
    exam = repo.get_or_create_exam(
        db,
        name=payload.name,
        applied_on=payload.applied_on,
        sequence=payload.sequence,
    )
    db.commit()
    return schemas.ExamOut(
        id=exam.id,
        name=exam.name,
        applied_on=exam.applied_on,
        sequence=exam.sequence,
    )

@router.get("/exams", response_model=List[schemas.ExamOut])
def list_exams(db: Session = Depends(get_db)):
    return [
        schemas.ExamOut(
            id=e.id, name=e.name, applied_on=e.applied_on, sequence=e.sequence
        )
        for e in repo.list_exams(db)
    ]

@router.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: int, db: Session = Depends(get_db)):
    """Delete an exam: its questions, sheets, answers and grading files.

    Students and classes are kept.
    """
    if not repo.delete_exam(db, exam_id):
        raise HTTPException(status_code=404, detail="Simulado não encontrado.")
    db.commit()
    # The database is the source of truth; leftover files are harmless
    artifacts.delete(exam_id)

@router.get(
    "/exams/{exam_id}/answer-key",
    response_model=List[schemas.AnswerKeyItemOut],
)
def exam_answer_key(exam_id: int, db: Session = Depends(get_db)):
    """The exam's stored gabarito, one item per question in sheet order."""
    if repo.get_exam(db, exam_id) is None:
        raise HTTPException(status_code=404, detail="Simulado não encontrado.")
    return [
        schemas.AnswerKeyItemOut(
            number=q.number,
            correct_answer=q.correct_answer,
            area=q.subject.name if q.subject else None,
            subarea=q.subtopic.name if q.subtopic else None,
        )
        for q in repo.list_questions(db, exam_id)
    ]

@router.put(
    "/exams/{exam_id}/answer-key",
    response_model=schemas.AnswerKeyUpdateOut,
)
def update_exam_answer_key(
    exam_id: int,
    changes: List[schemas.AnswerKeyChangeIn],
    db: Session = Depends(get_db),
):
    """Change the gabarito of the listed questions and regrade the exam.

    Verdicts and scores are recomputed from the marks already stored, so no
    sheet has to be uploaded again. Questions left out keep their gabarito.
    """
    if repo.get_exam(db, exam_id) is None:
        raise HTTPException(status_code=404, detail="Simulado não encontrado.")
    new_answers = {c.number: c.correct_answer.strip() for c in changes}
    try:
        summary = repo.update_answer_key(db, exam_id, new_answers)
    except repo.AnswerKeyError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error))
    db.commit()
    # Best effort, like saving them: the database already has the change
    try:
        artifacts.apply_answer_key(exam_id, new_answers)
    except (OSError, ValueError, IndexError):
        pass
    return schemas.AnswerKeyUpdateOut(
        questions_changed=summary.questions_changed,
        answers_regraded=summary.answers_regraded,
        sheets_rescored=summary.sheets_rescored,
    )
