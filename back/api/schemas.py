"""Pydantic response/request schemas for the API.

These describe the JSON contract only; the long-format rows deliberately keep
their Portuguese column names so the front-end can build a DataFrame with the
exact columns the charts expect (Nome do Aluno, Área, ...).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ClassOut(BaseModel):
    id: int
    name: str
    turno: Optional[str] = None


class StudentOut(BaseModel):
    id: int
    name: str
    class_id: Optional[int] = None


class SubjectOut(BaseModel):
    id: int
    name: str


class ExamIn(BaseModel):
    name: str
    applied_on: Optional[date] = None
    sequence: Optional[int] = None


class ExamOut(BaseModel):
    id: int
    name: str
    applied_on: Optional[date] = None
    sequence: Optional[int] = None


class AnswerKeyItemOut(BaseModel):
    """One question of an exam's gabarito."""

    number: int
    correct_answer: Optional[str] = None
    area: Optional[str] = None
    subarea: Optional[str] = None


class AnswerKeyChangeIn(BaseModel):
    """A new gabarito for one question."""

    number: int
    correct_answer: str


class AnswerKeyUpdateOut(BaseModel):
    questions_changed: int
    answers_regraded: int
    sheets_rescored: int


class LongFormatRow(BaseModel):
    """One row of the dashboard long format. Aliased to the Portuguese columns."""

    nome_do_aluno: str = Field(alias="Nome do Aluno")
    turma: Optional[str] = Field(default=None, alias="Turma")
    area: Optional[str] = Field(default=None, alias="Área")
    subarea: Optional[str] = Field(default=None, alias="Subárea")
    numero_da_questao: int = Field(alias="Número da questão")
    questao: str = Field(alias="Questão")
    resposta_do_aluno: Optional[str] = Field(default=None, alias="Resposta do aluno")
    resultado: str = Field(alias="Resultado")
    turno: Optional[str] = Field(default=None, alias="Turno")
    simulado: Optional[str] = Field(default=None, alias="Simulado")

    model_config = {"populate_by_name": True}


class ResultsOut(BaseModel):
    """The long-format result set plus the column order for rebuilding a frame."""

    columns: List[str]
    rows: List[Dict[str, object]]


class PerformanceOut(BaseModel):
    total: int
    acertos: int
    erros: int
    em_branco: int
    taxa_acerto: float


class SubjectTrendPoint(BaseModel):
    exam_id: int
    exam_name: str
    applied_on: Optional[date] = None
    sequence: Optional[int] = None
    overall: PerformanceOut
    by_subject: Dict[str, float] = {}


class TrendOut(BaseModel):
    class_id: int
    points: List[SubjectTrendPoint]


class GradingResultOut(BaseModel):
    """Summary of a grading/ingest run."""

    exam_id: int
    exam_name: str
    sheets_ingested: int
    students: List[str]
    log: Optional[str] = None
    # Things the teacher should check, e.g. a sheet read with no marks at all
    warnings: List[str] = []
