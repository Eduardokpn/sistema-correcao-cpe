"""Bridge between the OMR pipeline and the ingest layer.

Kept in its own module (imported lazily by the /gradings endpoint) so importing
the API never pulls in OpenCV. It runs the pipeline in grading/pipeline.py and hands
back the ResultsByQuestion frame the ingest layer consumes.
"""
from __future__ import annotations

import io
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from grading.results import load_results_by_question
from grading.sheets import check_answer_key, template_and_config_paths


@dataclass
class Graded:
    """What one grading run produced, with nothing left on disk."""

    results: pd.DataFrame
    log: str = ""
    # The ResultsByQuestion csv exactly as the pipeline wrote it
    raw_csv: str = ""
    # Sheet file name -> the image with the detected marks drawn on top
    marked_images: Dict[str, bytes] = field(default_factory=dict)
    work_dir: Path = None


def grade_and_frame(images, answer_key, **options) -> Tuple[pd.DataFrame, str]:
    """`grade`, for callers that only want (results_frame, log)."""
    graded = grade(images, answer_key, **options)
    return graded.results, graded.log


# One grading at a time: the pipeline captures its log through the root logger
# and was written to run alone, and the API calls `grade` from worker threads.
_GRADING_LOCK = threading.Lock()


def grade(
    images: List[Tuple[str, bytes]],
    answer_key: pd.DataFrame,
    question_column: str = None,
    answer_column: str = None,
    question_count: int = None,
) -> Graded:
    """Grade `images` against `answer_key`, one run at a time. See `_grade`."""
    with _GRADING_LOCK:
        return _grade(
            images,
            answer_key,
            question_column=question_column,
            answer_column=answer_column,
            question_count=question_count,
        )


def _grade(
    images: List[Tuple[str, bytes]],
    answer_key: pd.DataFrame,
    question_column: str = None,
    answer_column: str = None,
    question_count: int = None,
) -> Graded:
    """Grade `images` against `answer_key`.

    `question_count` (72, 80 or 90) picks the CPE sheet template from
    folha-cpe/; without it the default sheet is used.
    Imports grading.pipeline lazily, since it needs the OpenCV stack. Column
    detection mirrors the old Streamlit app: first column that looks like a
    question / answer header.
    """
    # Raises SheetError (a ValueError) before any heavy import or grading work
    template_path, config_path = template_and_config_paths(question_count)

    question_column = question_column or _pick(
        answer_key.columns, ("questão", "questao", "question", "nº", "numero", "número")
    )
    answer_column = answer_column or _pick(
        answer_key.columns,
        ("gabarito", "answer", "resposta", "correta"),
        exclude={question_column},
    )
    if question_column is None or answer_column is None:
        raise ValueError(
            "Não encontrei as colunas de questão e gabarito no arquivo enviado."
        )

    extra_columns = [c for c in answer_key.columns if c != question_column]

    # Same tidy-up the old app did on upload, so ' q1 ' still matches the sheet
    answer_key = answer_key.fillna("").apply(
        lambda column: column.astype(str).str.strip()
    )
    if question_count is not None:
        check_answer_key(answer_key[question_column].tolist(), question_count)

    from grading.pipeline import DEFAULT_MARKING, run_correction

    correction = run_correction(
        images=images,
        template_bytes=template_path.read_bytes(),
        answer_key=answer_key,
        question_column=question_column,
        answer_column=answer_column,
        extra_columns=extra_columns,
        marking=DEFAULT_MARKING,
        config_bytes=config_path.read_bytes() if config_path else None,
    )

    try:
        # run_correction already parsed the sheet; re-load from its raw csv so
        # the ingest layer sees the exact on-disk ResultsByQuestion shape (score
        # row + meta columns intact).
        return Graded(
            results=load_results_by_question(io.StringIO(correction.raw_csv)),
            log=correction.log,
            raw_csv=correction.raw_csv,
            marked_images={
                name: Path(path).read_bytes()
                for name, path in correction.marked_images.items()
            },
            work_dir=correction.work_dir,
        )
    finally:
        # Each run works in its own temp folder; nothing else cleans it up
        if correction.work_dir:
            shutil.rmtree(correction.work_dir, ignore_errors=True)


def _pick(columns, hints, exclude=()):
    for hint in hints:
        for column in columns:
            if column in exclude:
                continue
            if hint in str(column).strip().lower():
                return column
    return None
