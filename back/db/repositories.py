"""Repository layer: persistence and reads for the CPE OMR data.

Two responsibilities:

1. Get-or-create helpers plus `persist_graded_sheet`, which the grading layer
   (Task 3) uses to write a student's graded submission into the database.
2. `long_format_rows` / `long_format_dataframe`, which reproduce the exact
   long-format contract the dashboard charts consume:

       Nome do Aluno, Turma, Área, Subárea, Número da questão, Questão,
       Resposta do aluno, Resultado

   so the API can return that shape and the charts keep working unchanged.

Every function accepts a Session, so callers control the transaction. The
queries use plain SQLAlchemy Core/ORM constructs to stay PostgreSQL-portable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

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
# Reads
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
# Listing helpers (for the API to enumerate/lookup entities)
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


def get_student(session: Session, student_id: int) -> Optional[Student]:
    return session.get(Student, student_id)


# --------------------------------------------------------------------------- #
# Aggregations for the four teacher questions
# --------------------------------------------------------------------------- #
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
