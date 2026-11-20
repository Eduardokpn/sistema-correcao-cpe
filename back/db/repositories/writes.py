"""Writes: everything that changes the database.

Get-or-create helpers, `persist_graded_sheet` (what the grading layer calls to
store a student's graded submission), changing an exam's gabarito and deleting
an exam. Every function takes a Session and flushes; the caller commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

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
    Subtopic,
)


# --------------------------------------------------------------------------- #
# Get-or-create helpers
# --------------------------------------------------------------------------- #
def get_or_create_class(
    session: Session, name: str, turno: Optional[str] = None
) -> Class:
    school_class = session.scalar(select(Class).where(Class.name == name))
    if school_class is None:
        school_class = Class(name=name, turno=turno)
        session.add(school_class)
        session.flush()
    elif turno and not school_class.turno:
        school_class.turno = turno
    return school_class


def get_or_create_student(
    session: Session, name: str, school_class: Optional[Class] = None
) -> Student:
    class_id = school_class.id if school_class else None
    student = session.scalar(
        select(Student).where(Student.name == name, Student.class_id == class_id)
    )
    if student is not None:
        return student

    # The turma is optional on upload, so the same student can arrive once with
    # it and once without. When the name points at exactly one candidate, reuse
    # that student instead of splitting their history in two.
    if school_class is not None:
        without_class = session.scalars(
            select(Student).where(Student.name == name, Student.class_id.is_(None))
        ).all()
        if len(without_class) == 1:
            without_class[0].school_class = school_class
            session.flush()
            return without_class[0]
    else:
        same_name = session.scalars(select(Student).where(Student.name == name)).all()
        if len(same_name) == 1:
            return same_name[0]

    student = Student(name=name, school_class=school_class)
    session.add(student)
    session.flush()
    return student


def get_or_create_subject(session: Session, name: str) -> Optional[Subject]:
    if not name:
        return None
    subject = session.scalar(select(Subject).where(Subject.name == name))
    if subject is None:
        subject = Subject(name=name)
        session.add(subject)
        session.flush()
    return subject


def get_or_create_subtopic(
    session: Session, name: str, subject: Optional[Subject]
) -> Optional[Subtopic]:
    if not name or subject is None:
        return None
    subtopic = session.scalar(
        select(Subtopic).where(
            Subtopic.name == name, Subtopic.subject_id == subject.id
        )
    )
    if subtopic is None:
        subtopic = Subtopic(name=name, subject=subject)
        session.add(subtopic)
        session.flush()
    return subtopic


def get_or_create_exam(
    session: Session,
    name: str,
    applied_on: Optional[date] = None,
    sequence: Optional[int] = None,
) -> Exam:
    exam = session.scalar(select(Exam).where(Exam.name == name))
    if exam is None:
        exam = Exam(name=name, applied_on=applied_on, sequence=sequence)
        session.add(exam)
        session.flush()
    else:
        if applied_on and not exam.applied_on:
            exam.applied_on = applied_on
        if sequence is not None and exam.sequence is None:
            exam.sequence = sequence
    return exam


def get_or_create_question(
    session: Session,
    exam: Exam,
    number: int,
    correct_answer: Optional[str] = None,
    subject: Optional[Subject] = None,
    subtopic: Optional[Subtopic] = None,
) -> Question:
    question = session.scalar(
        select(Question).where(
            Question.exam_id == exam.id, Question.number == number
        )
    )
    if question is None:
        question = Question(
            exam=exam,
            number=number,
            correct_answer=correct_answer,
            subject=subject,
            subtopic=subtopic,
        )
        session.add(question)
        session.flush()
    else:
        # A newer answer key wins, so re-grading with a corrected gabarito
        # replaces the stored one; a run without a key keeps what is there
        if correct_answer and question.correct_answer != correct_answer:
            question.correct_answer = correct_answer
        if subject and question.subject_id is None:
            question.subject = subject
        if subtopic and question.subtopic_id is None:
            question.subtopic = subtopic
    return question


# --------------------------------------------------------------------------- #
# Persisting a graded sheet
# --------------------------------------------------------------------------- #
@dataclass
class AnswerInput:
    """One graded question as handed to the repository."""

    number: int
    marked_answer: Optional[str]
    verdict: str
    correct_answer: Optional[str] = None
    subject: Optional[str] = None
    subtopic: Optional[str] = None


@dataclass
class SheetInput:
    """A full graded submission ready to persist."""

    student_name: str
    exam_name: str
    answers: List[AnswerInput]
    class_name: Optional[str] = None
    turno: Optional[str] = None
    score: Optional[float] = None
    source_image: Optional[str] = None
    exam_applied_on: Optional[date] = None
    exam_sequence: Optional[int] = None


def persist_graded_sheet(session: Session, sheet_input: SheetInput) -> Sheet:
    """Write one graded sheet (student, exam, questions, answers) to the DB.

    Re-grading the same student for the same exam replaces the previous sheet's
    answers rather than duplicating them, so a correction can be re-run safely.
    """
    school_class = (
        get_or_create_class(session, sheet_input.class_name, sheet_input.turno)
        if sheet_input.class_name
        else None
    )
    student = get_or_create_student(session, sheet_input.student_name, school_class)
    exam = get_or_create_exam(
        session,
        sheet_input.exam_name,
        applied_on=sheet_input.exam_applied_on,
        sequence=sheet_input.exam_sequence,
    )

    sheet = session.scalar(
        select(Sheet).where(
            Sheet.student_id == student.id, Sheet.exam_id == exam.id
        )
    )
    if sheet is None:
        sheet = Sheet(student=student, exam=exam)
        session.add(sheet)
        session.flush()
    else:
        # Replace prior answers so a re-run is idempotent
        for existing in list(sheet.answers):
            session.delete(existing)
        session.flush()

    sheet.score = sheet_input.score
    sheet.source_image = sheet_input.source_image

    for answer_input in sheet_input.answers:
        subject = get_or_create_subject(session, answer_input.subject)
        subtopic = get_or_create_subtopic(session, answer_input.subtopic, subject)
        question = get_or_create_question(
            session,
            exam,
            number=answer_input.number,
            correct_answer=answer_input.correct_answer,
            subject=subject,
            subtopic=subtopic,
        )
        session.add(
            Answer(
                sheet=sheet,
                question=question,
                marked_answer=answer_input.marked_answer,
                verdict=answer_input.verdict,
            )
        )

    session.flush()
    return sheet


# --------------------------------------------------------------------------- #
# Changing an exam's answer key
# --------------------------------------------------------------------------- #
class AnswerKeyError(ValueError):
    """The requested answer-key change cannot be applied."""


@dataclass
class AnswerKeyUpdate:
    """What changing an exam's gabarito touched."""

    questions_changed: int = 0
    answers_regraded: int = 0
    sheets_rescored: int = 0


def _is_blank(marked_answer: Optional[str]) -> bool:
    return (marked_answer or "").strip() in ("", "-")


def update_answer_key(
    session: Session, exam_id: int, new_answers: Dict[int, str]
) -> AnswerKeyUpdate:
    """Change the gabarito of some questions and regrade from the stored marks.

    `new_answers` maps question number -> new correct answer; questions left
    out keep their key. Each stored answer to a changed question gets its
    verdict recomputed by comparing the mark the student made with the new key,
    so no image is read again. Sheet scores move by the number of answers that
    became (or stopped being) correct, matching the 1/0/0 marking the pipeline
    grades with.

    Only single-answer keys are supported: the comparison does not reproduce
    the engine's multiple-correct / weighted matching.
    """
    cleaned = {}
    for number, answer in new_answers.items():
        answer = (answer or "").strip()
        if not answer:
            raise AnswerKeyError(f"A questão {number} está sem gabarito.")
        if answer[0] in "[(" or "," in answer:
            raise AnswerKeyError(
                f"Questão {number}: gabaritos com mais de uma resposta ou com "
                "pesos precisam de uma nova correção das folhas."
            )
        cleaned[int(number)] = answer

    questions = {
        question.number: question
        for question in session.scalars(
            select(Question)
            .where(Question.exam_id == exam_id, Question.number.in_(cleaned))
            .options(joinedload(Question.answers).joinedload(Answer.sheet))
        ).unique()
    }
    missing = sorted(set(cleaned) - set(questions))
    if missing:
        raise AnswerKeyError(
            "O simulado não tem as questões: "
            + ", ".join(str(number) for number in missing)
        )

    summary = AnswerKeyUpdate()
    rescored = set()
    for number, new_answer in cleaned.items():
        question = questions[number]
        if question.correct_answer == new_answer:
            continue
        question.correct_answer = new_answer
        summary.questions_changed += 1

        for answer in question.answers:
            if _is_blank(answer.marked_answer):
                verdict = VERDICT_UNMARKED
            elif answer.marked_answer.strip().casefold() == new_answer.casefold():
                verdict = VERDICT_CORRECT
            else:
                verdict = VERDICT_INCORRECT
            if verdict == answer.verdict:
                continue
            delta = (verdict == VERDICT_CORRECT) - (answer.verdict == VERDICT_CORRECT)
            answer.verdict = verdict
            summary.answers_regraded += 1
            if delta and answer.sheet.score is not None:
                answer.sheet.score += delta
                rescored.add(answer.sheet_id)

    summary.sheets_rescored = len(rescored)
    session.flush()
    return summary


# --------------------------------------------------------------------------- #
# Deleting
# --------------------------------------------------------------------------- #
def delete_exam(session: Session, exam_id: int) -> bool:
    """Delete an exam with its questions, sheets and answers.

    Students and classes stay: they belong to the school, not to the exam.
    Returns False when the exam does not exist.
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return False
    session.delete(exam)
    session.flush()
    return True
