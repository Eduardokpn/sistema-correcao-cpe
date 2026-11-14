"""Schema smoke tests: insert one row per table and assert relationships resolve."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import (
    Answer,
    Class,
    Exam,
    Question,
    Sheet,
    Student,
    Subject,
    Subtopic,
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_UNMARKED,
)


def _seed(session):
    """Build one connected graph across every table and return the leaf answer."""
    school_class = Class(name="3º Ano A", turno="vespertino")
    student = Student(name="Giovanna Victória", school_class=school_class)

    subject = Subject(name="Matemática")
    subtopic = Subtopic(name="Álgebra", subject=subject)

    exam = Exam(name="Simulado 1", applied_on=date(2026, 3, 1), sequence=1)
    question = Question(
        exam=exam,
        number=1,
        correct_answer="E",
        subject=subject,
        subtopic=subtopic,
    )

    sheet = Sheet(student=student, exam=exam, score=8.0, source_image="giovanna.png")
    answer = Answer(
        sheet=sheet,
        question=question,
        marked_answer="E",
        verdict=VERDICT_CORRECT,
    )

    session.add(answer)
    session.commit()
    return answer


def test_insert_and_read_every_table(session):
    answer = _seed(session)

    # One row landed in each table
    assert session.query(Class).count() == 1
    assert session.query(Student).count() == 1
    assert session.query(Subject).count() == 1
    assert session.query(Subtopic).count() == 1
    assert session.query(Exam).count() == 1
    assert session.query(Question).count() == 1
    assert session.query(Sheet).count() == 1
    assert session.query(Answer).count() == 1


def test_relationships_resolve_end_to_end(session):
    answer = _seed(session)

    # Walk the whole graph from the answer up to the class and subject
    assert answer.verdict == VERDICT_CORRECT
    assert answer.marked_answer == "E"
    assert answer.question.correct_answer == "E"
    assert answer.question.number == 1
    assert answer.question.subject.name == "Matemática"
    assert answer.question.subtopic.name == "Álgebra"
    assert answer.question.subtopic.subject.name == "Matemática"
    assert answer.question.exam.name == "Simulado 1"
    assert answer.question.exam.sequence == 1

    assert answer.sheet.student.name == "Giovanna Victória"
    assert answer.sheet.student.school_class.name == "3º Ano A"
    assert answer.sheet.student.school_class.turno == "vespertino"
    assert answer.sheet.exam.name == "Simulado 1"
    assert answer.sheet.score == 8.0

    # Back-references resolve too
    exam = answer.sheet.exam
    assert question_in(exam.questions, number=1)
    assert exam.sheets[0].student.name == "Giovanna Victória"


def test_graded_at_defaults_on_insert(session):
    answer = _seed(session)
    assert answer.sheet.graded_at is not None


@pytest.mark.parametrize(
    "verdict", [VERDICT_CORRECT, VERDICT_INCORRECT, VERDICT_UNMARKED]
)
def test_verdict_check_accepts_canonical_values(session, verdict):
    answer = _seed(session)
    # A fresh answer on the same sheet/question-less path: reuse the sheet and
    # add a second question to avoid the unique (sheet, question) constraint.
    second_question = Question(exam=answer.question.exam, number=2)
    session.add(
        Answer(
            sheet=answer.sheet,
            question=second_question,
            marked_answer="A",
            verdict=verdict,
        )
    )
    session.commit()  # should not raise


def test_verdict_check_rejects_invalid_value(session):
    answer = _seed(session)
    second_question = Question(exam=answer.question.exam, number=2)
    session.add(
        Answer(
            sheet=answer.sheet,
            question=second_question,
            marked_answer="A",
            verdict="bogus",  # violates ck_answer_verdict_valid
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def question_in(questions, number):
    return any(q.number == number for q in questions)
