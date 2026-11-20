"""Reads: the long-format rows the dashboard consumes, and simple lookups.

`long_format_rows` / `long_format_dataframe` reproduce the exact contract the
charts expect:

    Nome do Aluno, Turma, Área, Subárea, Número da questão, Questão,
    Resposta do aluno, Resultado

The queries use plain SQLAlchemy constructs to stay PostgreSQL-portable.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from db.models import (
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_UNMARKED,
    Answer,
    Class,
    Exam,
    Question,
    Sheet,
    Student,
    Subject,
)

# Dashboard-facing Resultado labels (Portuguese), mapped from the stored verdict.
ACERTO = "Acerto"
ERRO = "Erro"
NAO_RESPONDEU = "Não Respondeu"

VERDICT_TO_RESULTADO = {
    VERDICT_CORRECT: ACERTO,
    VERDICT_INCORRECT: ERRO,
    VERDICT_UNMARKED: NAO_RESPONDEU,
}

# The canonical long-format column order the charts expect
LONG_FORMAT_COLUMNS = [
    "Nome do Aluno",
    "Turma",
    "Área",
    "Subárea",
    "Número da questão",
    "Questão",
    "Resposta do aluno",
    "Resultado",
]

NOT_INFORMED = "Não informado"


# --------------------------------------------------------------------------- #
# Long format
# --------------------------------------------------------------------------- #
def _answers_query(
    exam_id: Optional[int] = None,
    class_id: Optional[int] = None,
    student_id: Optional[int] = None,
    subject_id: Optional[int] = None,
):
    """Answer query eager-loading every relationship the long format needs."""
    stmt = (
        select(Answer)
        .join(Answer.sheet)
        .join(Sheet.student)
        .join(Answer.question)
        .options(
            joinedload(Answer.sheet).joinedload(Sheet.student).joinedload(
                Student.school_class
            ),
            joinedload(Answer.sheet).joinedload(Sheet.exam),
            joinedload(Answer.question).joinedload(Question.subject),
            joinedload(Answer.question).joinedload(Question.subtopic),
        )
    )
    if exam_id is not None:
        stmt = stmt.where(Sheet.exam_id == exam_id)
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    if student_id is not None:
        stmt = stmt.where(Sheet.student_id == student_id)
    if subject_id is not None:
        stmt = stmt.where(Question.subject_id == subject_id)
    return stmt


def long_format_rows(
    session: Session,
    exam_id: Optional[int] = None,
    class_id: Optional[int] = None,
    student_id: Optional[int] = None,
    subject_id: Optional[int] = None,
) -> List[Dict[str, object]]:
    """Return the long-format rows (one dict per answer) matching the chart contract."""
    answers = session.scalars(
        _answers_query(exam_id, class_id, student_id, subject_id)
    ).unique().all()

    rows: List[Dict[str, object]] = []
    for answer in answers:
        question = answer.question
        student = answer.sheet.student
        school_class = student.school_class
        subject = question.subject
        subtopic = question.subtopic
        rows.append(
            {
                "Nome do Aluno": student.name,
                "Turma": school_class.name if school_class else NOT_INFORMED,
                "Área": subject.name if subject else None,
                "Subárea": subtopic.name if subtopic else None,
                "Número da questão": question.number,
                "Questão": f"Q{question.number}",
                "Resposta do aluno": answer.marked_answer or "-",
                "Resultado": VERDICT_TO_RESULTADO.get(answer.verdict, NAO_RESPONDEU),
                # Extra context columns, handy for the API but ignored by charts
                "Turno": school_class.turno if school_class else None,
                "Simulado": answer.sheet.exam.name,
            }
        )

    rows.sort(key=lambda row: (row["Nome do Aluno"], row["Número da questão"]))
    return rows


def long_format_dataframe(session: Session, **filters) -> pd.DataFrame:
    """Same rows as `long_format_rows`, as a DataFrame with the canonical columns."""
    rows = long_format_rows(session, **filters)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=LONG_FORMAT_COLUMNS)
    # Guarantee the canonical columns exist and lead, keeping any extras after
    ordered = LONG_FORMAT_COLUMNS + [
        column for column in frame.columns if column not in LONG_FORMAT_COLUMNS
    ]
    return frame[ordered]


# --------------------------------------------------------------------------- #
# Listing and lookup helpers
# --------------------------------------------------------------------------- #
def list_exams(session: Session) -> List[Exam]:
    return list(
        session.scalars(
            select(Exam).order_by(Exam.sequence.is_(None), Exam.sequence, Exam.applied_on)
        )
    )


def list_classes(session: Session) -> List[Class]:
    return list(session.scalars(select(Class).order_by(Class.name)))


def list_students(session: Session, class_id: Optional[int] = None) -> List[Student]:
    stmt = select(Student).order_by(Student.name)
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    return list(session.scalars(stmt))


def list_subjects(session: Session) -> List[Subject]:
    return list(session.scalars(select(Subject).order_by(Subject.name)))


def get_exam(session: Session, exam_id: int) -> Optional[Exam]:
    return session.get(Exam, exam_id)


def get_student(session: Session, student_id: int) -> Optional[Student]:
    return session.get(Student, student_id)


def list_questions(session: Session, exam_id: int) -> List[Question]:
    """The exam's questions in sheet order, with área/subárea loaded."""
    return list(
        session.scalars(
            select(Question)
            .where(Question.exam_id == exam_id)
            .options(joinedload(Question.subject), joinedload(Question.subtopic))
            .order_by(Question.number)
        )
    )
