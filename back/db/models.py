"""SQLAlchemy models for the CPE OMR system.

The schema mirrors the long-format contract the dashboard already consumes
(one row per student x question), so a single join across these tables
reproduces the columns the charts expect:

    Nome do Aluno   <- Student.name
    Turma           <- Class.name
    Área            <- Subject.name
    Subárea         <- Subtopic.name
    Número da questão <- Question.number
    Resposta do aluno <- Answer.marked_answer
    Resultado       <- Answer.verdict (mapped to Acerto/Erro/Não Respondeu)

Kept portable: no SQLite-only column types or constructs, so the same models
run unchanged against PostgreSQL by swapping the connection string.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# Verdicts as produced by omrchecker/src/evaluation.py and parsed by the grading layer.
# These three values are the single source of truth for the Answer.verdict
# CHECK constraint (ck_answer_verdict_valid), enforced on both SQLite and
# PostgreSQL - see the Answer model and migration 54aeeb1858ea.
VERDICT_CORRECT = "correct"
VERDICT_INCORRECT = "incorrect"
VERDICT_UNMARKED = "unmarked"
VERDICTS = (VERDICT_CORRECT, VERDICT_INCORRECT, VERDICT_UNMARKED)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


class Class(Base):
    """A turma - a group of students sharing a shift (turno)."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # 'vespertino' / 'noturno' - the turno the front-end used to filter on
    turno: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    students: Mapped[List["Student"]] = relationship(
        back_populates="school_class",
        cascade="all, delete-orphan",
    )


class Student(Base):
    """A student belonging to one class."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True
    )

    school_class: Mapped[Optional["Class"]] = relationship(back_populates="students")
    sheets: Mapped[List["Sheet"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("name", "class_id", name="uq_student_name_class"),)


class Subject(Base):
    """An área de conhecimento, e.g. 'Matemática', 'Ciências da Natureza'."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    subtopics: Mapped[List["Subtopic"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    questions: Mapped[List["Question"]] = relationship(back_populates="subject")


class Subtopic(Base):
    """A subárea within a subject, e.g. 'Álgebra' under 'Matemática'."""

    __tablename__ = "subtopics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    subject: Mapped["Subject"] = relationship(back_populates="subtopics")
    questions: Mapped[List["Question"]] = relationship(back_populates="subtopic")

    __table_args__ = (
        UniqueConstraint("name", "subject_id", name="uq_subtopic_name_subject"),
    )


class Exam(Base):
    """A single exam / simulado. Its date and sequence give the time axis."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    # The time dimension behind 'is the class improving over time'
    applied_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sequence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    questions: Mapped[List["Question"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
    )
    sheets: Mapped[List["Sheet"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
    )


class Question(Base):
    """One question on an exam, carrying its answer key and categorisation.

    The answer key (correct_answer) lives here with the question, so the exam
    answer sheet is stored in the database instead of a CSV.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # The gabarito for this question, e.g. 'A'..'E'
    correct_answer: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    subtopic_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subtopics.id", ondelete="SET NULL"), nullable=True
    )

    exam: Mapped["Exam"] = relationship(back_populates="questions")
    subject: Mapped[Optional["Subject"]] = relationship(back_populates="questions")
    subtopic: Mapped[Optional["Subtopic"]] = relationship(back_populates="questions")
    answers: Mapped[List["Answer"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("exam_id", "number", name="uq_question_exam_number"),
    )


class Sheet(Base):
    """One graded answer sheet: a student's submission for an exam."""

    __tablename__ = "sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Original image file name the sheet was read from
    source_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    graded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="sheets")
    exam: Mapped["Exam"] = relationship(back_populates="sheets")
    answers: Mapped[List["Answer"]] = relationship(
        back_populates="sheet",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("student_id", "exam_id", name="uq_sheet_student_exam"),
    )


class Answer(Base):
    """A single question's outcome on one sheet."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(
        ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    # What the student marked, e.g. 'A'..'E' or '-' when blank
    marked_answer: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # One of correct / incorrect / unmarked
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)

    sheet: Mapped["Sheet"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship(back_populates="answers")

    __table_args__ = (
        UniqueConstraint("sheet_id", "question_id", name="uq_answer_sheet_question"),
        # Pin the verdict to the three canonical states at the database level.
        # Enforced on PostgreSQL and on SQLite (with CHECKs enabled, which they
        # are by default). Built from VERDICTS so it can't drift from the code.
        CheckConstraint(
            "verdict IN ('%s')" % "', '".join(VERDICTS),
            name="ck_answer_verdict_valid",
        ),
    )
