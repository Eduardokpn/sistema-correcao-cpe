"""Ingest a parsed ResultsByQuestion sheet into the database.

Bridges the grading output to db.repositories: for each student column in the
ResultsByQuestion sheet it builds a SheetInput (student, exam, per-question
answers with verdict + answer key + área/subárea) and persists it.

Verdict mapping goes the other way from the dashboard's: the parsed Resultado
label (Acerto/Erro/Não Respondeu) maps back to the stored verdict
(correct/incorrect/unmarked) so the database keeps the canonical states.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from db.models import VERDICT_CORRECT, VERDICT_INCORRECT, VERDICT_UNMARKED
from db.repositories import AnswerInput, SheetInput, persist_graded_sheet
from grading.results import (
    ACERTO,
    ANSWER_KEY_HINTS,
    ERRO,
    NAO_RESPONDEU,
    QUESTION_COLUMN,
    guess_meta_columns,
    load_results_by_question,
    parse_verdict,
    question_number,
    split_scores,
    student_columns,
    student_name_from_file,
)

RESULTADO_TO_VERDICT = {
    ACERTO: VERDICT_CORRECT,
    ERRO: VERDICT_INCORRECT,
    NAO_RESPONDEU: VERDICT_UNMARKED,
}

# Meta-column name hints, matched case-insensitively by substring
AREA_HINTS = ("área", "area")
SUBAREA_HINTS = ("subárea", "subarea", "sub-área", "sub-area", "sub área", "assunto")


@dataclass
class SheetMetadata:
    """Metadata not present in the results sheet, supplied per correction run."""

    exam_name: str
    exam_applied_on: Optional[date] = None
    exam_sequence: Optional[int] = None
    # Map each sheet column (file name) to a student name; missing -> derived
    student_names: Optional[Dict[str, str]] = None
    # Map each sheet column (file name) to a turma; missing -> None
    student_classes: Optional[Dict[str, str]] = None
    # Map each turma to a turno (vespertino/noturno); optional
    class_turnos: Optional[Dict[str, str]] = None


def _pick_meta_column(meta_columns, hints, exclude=()):
    for hint in hints:
        for column in meta_columns:
            if column in exclude:
                continue
            if hint in str(column).strip().lower():
                return column
    return None


def ingest_results_by_question(
    session: Session,
    results_by_question: pd.DataFrame,
    metadata: SheetMetadata,
) -> List:
    """Persist every student column of a parsed results sheet. Returns the Sheets."""
    scores, results = split_scores(results_by_question)
    meta_columns = guess_meta_columns(results, scores)
    sheet_cols = student_columns(results, meta_columns)

    area_column = _pick_meta_column(meta_columns, AREA_HINTS)
    subarea_column = _pick_meta_column(
        meta_columns, SUBAREA_HINTS, exclude={area_column} if area_column else ()
    )
    # 'Área' also matches subárea hints, so keep the more specific one distinct
    if area_column and subarea_column and area_column == subarea_column:
        subarea_column = None
    answer_key_column = _pick_meta_column(
        meta_columns,
        ANSWER_KEY_HINTS,
        exclude={c for c in (area_column, subarea_column) if c},
    )

    names = metadata.student_names or {}
    classes = metadata.student_classes or {}
    turnos = metadata.class_turnos or {}

    persisted = []
    for column in sheet_cols:
        student_name = names.get(column) or student_name_from_file(column)
        class_name = classes.get(column)
        turno = turnos.get(class_name) if class_name else None

        answers = _build_answers(
            results, column, area_column, subarea_column, answer_key_column
        )
        sheet_input = SheetInput(
            student_name=student_name,
            exam_name=metadata.exam_name,
            class_name=class_name,
            turno=turno,
            score=scores.get(column),
            source_image=column,
            exam_applied_on=metadata.exam_applied_on,
            exam_sequence=metadata.exam_sequence,
            answers=answers,
        )
        persisted.append(persist_graded_sheet(session, sheet_input))

    return persisted


def _build_answers(
    results, column, area_column, subarea_column, answer_key_column
) -> List[AnswerInput]:
    answers = []
    for position, row in results.iterrows():
        label = row[QUESTION_COLUMN]
        number = question_number(label)
        if number is None:
            # Keep a stable ordering for non-numeric labels
            number = position + 1
        resultado, marked = parse_verdict(row[column])
        verdict = RESULTADO_TO_VERDICT.get(resultado, VERDICT_UNMARKED)
        answers.append(
            AnswerInput(
                number=number,
                marked_answer=marked,
                verdict=verdict,
                correct_answer=_clean(row.get(answer_key_column)) if answer_key_column else None,
                subject=_clean(row.get(area_column)) if area_column else None,
                subtopic=_clean(row.get(subarea_column)) if subarea_column else None,
            )
        )
    return answers


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ingest_results_csv(
    session: Session, path_or_buffer, metadata: SheetMetadata
) -> List:
    """Load a ResultsByQuestion csv from disk/buffer and persist it."""
    results = load_results_by_question(path_or_buffer)
    return ingest_results_by_question(session, results, metadata)
