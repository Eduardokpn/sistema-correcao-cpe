"""Longitudinal trend tests: a class across two exams over time.

Asserts class_improvement_over_time returns points ordered by the exam's time
axis, with overall accuracy and a per-subject breakdown - the data behind the
'is the class improving?' question.
"""
from datetime import date

from db.repositories import (
    AnswerInput,
    SheetInput,
    class_improvement_over_time,
    persist_graded_sheet,
)
from db.models import VERDICT_CORRECT, VERDICT_INCORRECT


def _sheet(student, exam, seq, applied, v1, v2):
    """Two-question sheet: q1 Matemática, q2 Português."""
    return SheetInput(
        student_name=student,
        exam_name=exam,
        class_name="3A",
        turno="vespertino",
        exam_applied_on=applied,
        exam_sequence=seq,
        answers=[
            AnswerInput(1, "E", v1, correct_answer="E", subject="Matemática", subtopic="Álgebra"),
            AnswerInput(2, "B", v2, correct_answer="B", subject="Português", subtopic="Gramática"),
        ],
    )


def test_trend_ordered_over_two_exams(session):
    # Simulado 1: both wrong.  Simulado 2: both correct -> class improved.
    persist_graded_sheet(
        session, _sheet("Aluno A", "Simulado 1", 1, date(2026, 3, 1), VERDICT_INCORRECT, VERDICT_INCORRECT)
    )
    persist_graded_sheet(
        session, _sheet("Aluno A", "Simulado 2", 2, date(2026, 5, 1), VERDICT_CORRECT, VERDICT_CORRECT)
    )
    session.commit()

    from db.models import Class

    class_id = session.query(Class).filter_by(name="3A").one().id
    points = class_improvement_over_time(session, class_id)

    assert len(points) == 2
    # Ordered by sequence
    assert [p.exam_name for p in points] == ["Simulado 1", "Simulado 2"]
    # Overall accuracy rose from 0% to 100%
    assert points[0].summary.taxa_acerto == 0.0
    assert points[1].summary.taxa_acerto == 100.0


def test_trend_has_per_subject_breakdown(session):
    # Simulado 1: Matemática right, Português wrong (50% overall, per-subject split)
    persist_graded_sheet(
        session, _sheet("Aluno A", "Simulado 1", 1, date(2026, 3, 1), VERDICT_CORRECT, VERDICT_INCORRECT)
    )
    session.commit()

    from db.models import Class

    class_id = session.query(Class).filter_by(name="3A").one().id
    points = class_improvement_over_time(session, class_id)

    assert len(points) == 1
    by_subject = points[0].by_subject
    assert by_subject["Matemática"] == 100.0
    assert by_subject["Português"] == 0.0


def test_trend_skips_exams_class_did_not_sit(session):
    # Class 3A sits Simulado 1 only; Simulado 2 exists but for another class
    persist_graded_sheet(
        session, _sheet("Aluno A", "Simulado 1", 1, date(2026, 3, 1), VERDICT_CORRECT, VERDICT_CORRECT)
    )
    other = _sheet("Aluno Z", "Simulado 2", 2, date(2026, 5, 1), VERDICT_CORRECT, VERDICT_CORRECT)
    other.class_name = "OtherClass"
    persist_graded_sheet(session, other)
    session.commit()

    from db.models import Class

    class_id = session.query(Class).filter_by(name="3A").one().id
    points = class_improvement_over_time(session, class_id)

    # Only the exam 3A actually sat shows up
    assert [p.exam_name for p in points] == ["Simulado 1"]
