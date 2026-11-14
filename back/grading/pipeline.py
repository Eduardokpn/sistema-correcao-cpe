"""Drives the OMRChecker pipeline from uploaded files.

Moved here from the old webapp/pipeline.py so the grading logic no longer lives
under the retired Streamlit app. The CLI expects template.json, evaluation.json
and the answer key to sit next to the sheet images, so every run builds its own
temporary directory out of what was uploaded and then calls the same entry point
that omrchecker/main.py uses.

Parsing of the resulting ResultsByQuestion sheet lives in grading/results.py and
is imported here to avoid duplication.
"""
import json
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# The engine is vendored unmodified in back/omrchecker/ and imports itself as
# the top-level package `src`, so that folder has to be importable. This is the
# only module of the app that imports the engine.
_ENGINE_DIR = str(Path(__file__).resolve().parent.parent / "omrchecker")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from src.constants.common import (  # noqa: E402
    CONFIG_FILENAME,
    EVALUATION_FILENAME,
    TEMPLATE_FILENAME,
)
from src.entry import entry_point  # noqa: E402
from grading.results import (  # noqa: E402
    QUESTION_COLUMN,
    SCORE_ROW,
    load_results_by_question,
    split_scores,
)

ANSWER_KEY_FILENAME = "gabarito.csv"
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

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
    """Collects the pipeline's log lines so callers can show them on failure."""

    def __init__(self):
        from io import StringIO

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
            # A failed run must not leave its temp folder behind either
            shutil.rmtree(work_dir, ignore_errors=True)
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
