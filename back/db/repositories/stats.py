"""Aggregations behind the four teacher questions.

Built on the long-format rows from db.repositories.queries, so the numbers
always match what the dashboard charts show.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from db.repositories.queries import (
    ACERTO,
    ERRO,
    NAO_RESPONDEU,
    list_exams,
    list_subjects,
    long_format_rows,
)


@dataclass
class PerformanceSummary:
    """Verdict tally + accuracy for a slice of answers."""

    total: int
    acertos: int
    erros: int
    em_branco: int
    taxa_acerto: float  # percentage 0..100

    @classmethod
    def from_rows(cls, rows: Iterable[Dict[str, object]]) -> "PerformanceSummary":
        rows = list(rows)
        total = len(rows)
        acertos = sum(1 for row in rows if row["Resultado"] == ACERTO)
        erros = sum(1 for row in rows if row["Resultado"] == ERRO)
        em_branco = sum(1 for row in rows if row["Resultado"] == NAO_RESPONDEU)
        taxa = round(acertos / total * 100, 1) if total else 0.0
        return cls(total, acertos, erros, em_branco, taxa)


def student_performance_in_subject(
    session: Session, student_id: int, subject_id: int
) -> PerformanceSummary:
    """Q1: how a student did in a given subject (área), across all their sheets."""
    rows = long_format_rows(session, student_id=student_id, subject_id=subject_id)
    return PerformanceSummary.from_rows(rows)


def student_performance_in_exam(
    session: Session, student_id: int, exam_id: int
) -> PerformanceSummary:
    """Q2: how a student did in a given exam."""
    rows = long_format_rows(session, student_id=student_id, exam_id=exam_id)
    return PerformanceSummary.from_rows(rows)


def class_performance_in_exam(
    session: Session, class_id: int, exam_id: int
) -> PerformanceSummary:
    """Q3: how the whole class did in a given exam."""
    rows = long_format_rows(session, class_id=class_id, exam_id=exam_id)
    return PerformanceSummary.from_rows(rows)


@dataclass
class TrendPoint:
    """One exam's accuracy for a class, with the time axis attached."""

    exam_id: int
    exam_name: str
    applied_on: Optional[date]
    sequence: Optional[int]
    summary: PerformanceSummary
    # Per-subject accuracy for this exam: {subject_name: taxa_acerto}
    by_subject: Dict[str, float] = field(default_factory=dict)


def class_improvement_over_time(
    session: Session, class_id: int
) -> List[TrendPoint]:
    """Q4: is the class improving over time - overall and per subject.

    One point per exam the class sat, ordered by the exam's time axis
    (sequence then applied_on). Each point carries the overall accuracy and a
    per-subject breakdown so the front-end can draw both.
    """
    exams = list_exams(session)
    subjects = list_subjects(session)

    points: List[TrendPoint] = []
    for exam in exams:
        rows = long_format_rows(session, class_id=class_id, exam_id=exam.id)
        if not rows:
            # The class did not sit this exam - skip it from the trend
            continue
        summary = PerformanceSummary.from_rows(rows)
        by_subject: Dict[str, float] = {}
        for subject in subjects:
            subject_rows = [row for row in rows if row["Área"] == subject.name]
            if subject_rows:
                by_subject[subject.name] = PerformanceSummary.from_rows(
                    subject_rows
                ).taxa_acerto
        points.append(
            TrendPoint(
                exam_id=exam.id,
                exam_name=exam.name,
                applied_on=exam.applied_on,
                sequence=exam.sequence,
                summary=summary,
                by_subject=by_subject,
            )
        )
    return points
