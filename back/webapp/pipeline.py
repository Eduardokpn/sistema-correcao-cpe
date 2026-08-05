"""Drives the OMRChecker pipeline from uploaded files.

The CLI expects template.json, evaluation.json and the answer key to sit next to
the sheet images, so every run builds its own temporary directory out of what was
uploaded and then calls the same entry point that main.py uses.
"""
import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

import pandas as pd

from src.constants.common import (
    CONFIG_FILENAME,
    EVALUATION_FILENAME,
    TEMPLATE_FILENAME,
)
from src.entry import entry_point

ANSWER_KEY_FILENAME = "gabarito.csv"
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

QUESTION_COLUMN = "question"
SCORE_ROW = "score"

# Verdicts written by src/evaluation.py, e.g. 'correct-E', 'incorrect-B', 'unmarked'
ACERTO, ERRO, NAO_RESPONDEU = "Acerto", "Erro", "Não Respondeu"
RESULT_ORDER = [ACERTO, ERRO, NAO_RESPONDEU]

DEFAULT_MARKING = {"correct": "1", "incorrect": "0", "unmarked": "0"}


@dataclass
class CorrectionResult:
    """Everything a single correction run produced."""

    results_by_question: pd.DataFrame
    scores: dict
    marked_images: dict = field(default_factory=dict)
    work_dir: Path = None
    log: str = ""
    # The ResultsByQuestion csv exactly as the pipeline wrote it, for download
    raw_csv: str = ""


class CorrectionError(Exception):
    """Raised when the pipeline could not grade the uploaded sheets."""


def is_supported_image(file_name):
    return Path(file_name).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def unique_file_name(file_name, taken):
    """Two uploads with the same name would collapse into one result column."""
    candidate = Path(file_name).name
    stem, suffix = Path(candidate).stem, Path(candidate).suffix
    counter = 2
    while candidate in taken:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    taken.add(candidate)
    return candidate


def build_evaluation_json(question_column, answer_column, extra_columns, marking):
    # The answer key is always written as a csv with a header row by this module
    return {
        "source_type": "csv",
        "options": {
            "answer_key_csv_path": ANSWER_KEY_FILENAME,
            "answer_key_csv_question_column": question_column,
            "answer_key_csv_answer_column": answer_column,
            "answer_key_csv_extra_columns": list(extra_columns),
        },
        "marking_schemes": {
            "DEFAULT": {
                "correct": str(marking.get("correct", DEFAULT_MARKING["correct"])),
                "incorrect": str(
                    marking.get("incorrect", DEFAULT_MARKING["incorrect"])
                ),
                "unmarked": str(marking.get("unmarked", DEFAULT_MARKING["unmarked"])),
            }
        },
    }


class _LogCapture:
    """Collects the pipeline's log lines so the UI can show them on failure."""

    def __init__(self):
        self.buffer = StringIO()
        self.handler = logging.StreamHandler(self.buffer)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    def __enter__(self):
        logging.getLogger().addHandler(self.handler)
        return self

    def __exit__(self, *_exc):
        logging.getLogger().removeHandler(self.handler)
        self.handler.flush()
        return False

    def text(self):
        return self.buffer.getvalue()


def run_correction(
    images,
    template_bytes,
    answer_key,
    question_column,
    answer_column,
    extra_columns=(),
    marking=None,
    config_bytes=None,
):
    """Grades `images` and returns the transposed (per question) results sheet.

    `images` is a list of (file_name, bytes) pairs and `answer_key` a DataFrame
    holding at least the question and answer columns.
    """
    if not images:
        raise CorrectionError("Nenhuma prova foi enviada.")
    if template_bytes is None:
        raise CorrectionError("Nenhum template.json foi informado.")

    work_dir = Path(tempfile.mkdtemp(prefix="omrchecker_"))
    input_dir, output_dir = work_dir.joinpath("inputs"), work_dir.joinpath("outputs")
    input_dir.mkdir(parents=True)

    input_dir.joinpath(TEMPLATE_FILENAME).write_bytes(template_bytes)
    if config_bytes:
        input_dir.joinpath(CONFIG_FILENAME).write_bytes(config_bytes)

    answer_key.to_csv(input_dir.joinpath(ANSWER_KEY_FILENAME), index=False)
    evaluation_json = build_evaluation_json(
        question_column, answer_column, extra_columns, marking or DEFAULT_MARKING
    )
    input_dir.joinpath(EVALUATION_FILENAME).write_text(
        json.dumps(evaluation_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    taken = set()
    for file_name, content in images:
        if not is_supported_image(file_name):
            continue
        input_dir.joinpath(unique_file_name(file_name, taken)).write_bytes(content)
    if not taken:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise CorrectionError(
            f"Nenhuma imagem válida enviada. Formatos aceitos: {', '.join(SUPPORTED_IMAGE_EXTENSIONS)}"
        )

    args = {
        "input_paths": [str(input_dir)],
        "output_dir": str(output_dir),
        "setLayout": False,
        "autoAlign": False,
        "debug": False,
    }

    with _LogCapture() as captured:
        try:
            entry_point(input_dir, args)
        except Exception as error:
            raise CorrectionError(f"{error}\n\n{captured.text()}") from error
        log_text = captured.text()

    results_path = find_latest_results_by_question(output_dir)
    if results_path is None:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise CorrectionError(
            f"A correção não gerou a planilha ResultsByQuestion.\n\n{log_text}"
        )

    results_by_question = load_results_by_question(results_path)
    scores, results_by_question = split_scores(results_by_question)

    return CorrectionResult(
        results_by_question=results_by_question,
        scores=scores,
        marked_images=collect_marked_images(output_dir),
        work_dir=work_dir,
        log=log_text,
        raw_csv=results_path.read_text(encoding="utf-8"),
    )


def find_latest_results_by_question(output_dir):
    matches = sorted(Path(output_dir).rglob("ResultsByQuestion_*.csv"))
    return matches[-1] if matches else None


def collect_marked_images(output_dir):
    marked_dir = Path(output_dir).joinpath("CheckedOMRs")
    if not marked_dir.exists():
        return {}
    return {
        path.name: path
        for path in sorted(marked_dir.iterdir())
        if path.is_file() and is_supported_image(path.name)
    }


def load_results_by_question(path_or_buffer):
    results = pd.read_csv(path_or_buffer, dtype=str, keep_default_na=False)
    results.columns = [str(column).strip() for column in results.columns]
    if QUESTION_COLUMN not in results.columns:
        # Written with the question labels as the index column
        results = results.rename(columns={results.columns[0]: QUESTION_COLUMN})
    return results


def split_scores(results_by_question):
    """Pulls the leading 'score' row out into a {column: score} mapping."""
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
    known = {QUESTION_COLUMN, *meta_columns}
    return [column for column in results_by_question.columns if column not in known]


def guess_meta_columns(results_by_question, scores):
    """Answer key columns carried over sit between 'question' and the sheets.

    They are the only non-question columns without a numeric score, since the
    score row is blank for them.
    """
    return [
        column
        for column in results_by_question.columns
        if column != QUESTION_COLUMN and column not in scores
    ]


def student_name_from_file(file_name):
    stem = Path(str(file_name)).stem
    return re.sub(r"[_\-]+", " ", stem).strip().title()


def parse_verdict(verdict):
    """Turns 'correct-E' / 'incorrect-B' / 'unmarked' into (resultado, resposta)."""
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
    digits = re.findall(r"\d+", str(question_label))
    return int(digits[-1]) if digits else None


def to_long_format(results_by_question, meta_columns, names=None, groups=None):
    """Reshapes the transposed sheet into one row per (aluno, questão).

    This is the shape the dashboard reads: it mirrors the columns of the
    Planilha.csv used by dashboards-automatizados.
    """
    names, groups = names or {}, groups or {}
    columns = student_columns(results_by_question, meta_columns)
    if not columns:
        return pd.DataFrame()

    long = results_by_question.melt(
        id_vars=[QUESTION_COLUMN, *meta_columns],
        value_vars=columns,
        var_name="Arquivo",
        value_name="Veredito",
    )

    parsed = long["Veredito"].map(parse_verdict)
    long["Resultado"] = [result for result, _answer in parsed]
    long["Resposta do aluno"] = [answer for _result, answer in parsed]
    long["Nome do Aluno"] = long["Arquivo"].map(
        lambda file_name: names.get(file_name) or student_name_from_file(file_name)
    )
    long["Turma"] = long["Arquivo"].map(lambda f: groups.get(f) or "Não informado")

    numbers = long[QUESTION_COLUMN].map(question_number)
    order = {label: index for index, label in enumerate(results_by_question[QUESTION_COLUMN])}
    long["Número da questão"] = [
        number if number is not None else order[label]
        for number, label in zip(numbers, long[QUESTION_COLUMN])
    ]
    long["Questão"] = long[QUESTION_COLUMN]

    return long.sort_values(["Nome do Aluno", "Número da questão"]).reset_index(
        drop=True
    )


def summarize_students(long_results, scores=None):
    """One row per student: acertos, erros, em branco and the graded score."""
    if long_results.empty:
        return pd.DataFrame()

    counts = (
        long_results.pivot_table(
            index=["Nome do Aluno", "Arquivo", "Turma"],
            columns="Resultado",
            values="Questão",
            aggfunc="count",
            fill_value=0,
        )
        .reindex(columns=RESULT_ORDER, fill_value=0)
        .reset_index()
    )
    counts["Questões"] = counts[RESULT_ORDER].sum(axis=1)
    counts["% de acerto"] = (
        counts[ACERTO] / counts["Questões"].replace(0, pd.NA) * 100
    ).round(1)
    if scores:
        counts["Nota"] = counts["Arquivo"].map(scores)
    return counts.sort_values(ACERTO, ascending=False).reset_index(drop=True)
