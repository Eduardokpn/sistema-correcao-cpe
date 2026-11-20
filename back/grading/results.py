"""Parsing of the ResultsByQuestion.csv the OMR pipeline produces.

This is the logic previously embedded in webapp/pipeline.py, lifted out so it can
be reused without importing any Streamlit or web concern. The pipeline writes a
transposed sheet: a `question` column, an optional leading `score` row, some
answer-key meta columns carried over (Área, Subárea, Gabarito, ...), then one
column per graded sheet holding a verdict like 'correct-E' / 'incorrect-B' /
'unmarked'.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

QUESTION_COLUMN = "question"
SCORE_ROW = "score"

# Dashboard-facing Resultado labels, kept identical to db.repositories
ACERTO, ERRO, NAO_RESPONDEU = "Acerto", "Erro", "Não Respondeu"
RESULT_ORDER = [ACERTO, ERRO, NAO_RESPONDEU]

# Name hints for the answer-key column, matched case-insensitively by substring
ANSWER_KEY_HINTS = ("gabarito", "answer", "resposta", "correta")


def load_results_by_question(path_or_buffer):
    """Read a ResultsByQuestion csv into a DataFrame of strings."""
    results = pd.read_csv(path_or_buffer, dtype=str, keep_default_na=False)
    results.columns = [str(column).strip() for column in results.columns]
    if QUESTION_COLUMN not in results.columns:
        # Written with the question labels as the first (index) column
        results = results.rename(columns={results.columns[0]: QUESTION_COLUMN})
    return results


def split_scores(results_by_question):
    """Pull the leading 'score' row out into a {column: score} mapping."""
    is_score_row = results_by_question[QUESTION_COLUMN].str.strip() == SCORE_ROW
    scores = {}
    if is_score_row.any():
        score_row = results_by_question[is_score_row].iloc[0]
        for column, value in score_row.items():
            if column == QUESTION_COLUMN:
                continue
            try:
                scores[column] = float(value)
            except (TypeError, ValueError):
                continue
    return scores, results_by_question[~is_score_row].reset_index(drop=True)


def student_columns(results_by_question, meta_columns):
    """Columns that hold a student's verdicts (everything but question + meta)."""
    known = {QUESTION_COLUMN, *meta_columns}
    return [column for column in results_by_question.columns if column not in known]


def guess_meta_columns(results_by_question, scores):
    """Answer-key columns carried over sit between 'question' and the sheets.

    They are the only non-question columns without a numeric score, since the
    score row is blank for them.
    """
    return [
        column
        for column in results_by_question.columns
        if column != QUESTION_COLUMN and column not in scores
    ]


# Portuguese name connectors kept lowercase when deriving a name from a file.
_NAME_CONNECTORS = {"da", "de", "do", "das", "dos", "e"}


def student_name_from_file(file_name):
    """Turn a sheet file name into a readable student name.

    `Ana_Carolina_Matias_de_Melo.jpg` -> `Ana Carolina Matias de Melo`.
    Underscores/hyphens become spaces, each word is title-cased, and Portuguese
    connectors (da, de, do...) stay lowercase. Mirrors the frontend's editor
    default so the derived name matches what the user previews.
    """
    stem = Path(str(file_name)).stem
    words = re.sub(r"[_\-]+", " ", stem).strip().split()
    return " ".join(
        word.title() if index == 0 or word.lower() not in _NAME_CONNECTORS else word.lower()
        for index, word in enumerate(words)
    )


def parse_verdict(verdict):
    """Turn 'correct-E' / 'incorrect-B' / 'unmarked' into (resultado, resposta)."""
    value = str(verdict).strip()
    if value in ("", "nan"):
        return NAO_RESPONDEU, "-"
    head, _, marked = value.partition("-")
    head = head.lower()
    if head == "correct":
        return ACERTO, marked or "-"
    if head == "incorrect":
        return ERRO, marked or "-"
    if head == "unmarked":
        return NAO_RESPONDEU, "-"
    # No evaluation config was used - the cell holds the raw marked answer
    return NAO_RESPONDEU if value == "-" else ERRO, value


def question_number(question_label):
    """Extract the trailing integer from a question label like 'q12' -> 12."""
    digits = re.findall(r"\d+", str(question_label))
    return int(digits[-1]) if digits else None


def blank_sheets(results_by_question):
    """Sheet columns where not a single mark was read.

    A whole exam left blank is rare; a scan the pipeline could not read looks
    exactly like one, so callers warn about these instead of trusting them.
    """
    scores, results = split_scores(results_by_question)
    if results.empty:
        return []
    columns = student_columns(results, guess_meta_columns(results, scores))
    return [
        column
        for column in columns
        if all(parse_verdict(cell)[0] == NAO_RESPONDEU for cell in results[column])
    ]
