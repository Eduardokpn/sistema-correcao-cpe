"""Files a grading run leaves behind, kept per exam.

The database holds the answers; these are the two things it does not: the raw
ResultsByQuestion.csv exactly as the pipeline wrote it, and the sheet images
with the detected marks drawn on top, for visual checking.

They live under CPE_ARTIFACTS_DIR (default back/outputs/gradings/<exam_id>/).
A new grading of the same exam replaces the csv and adds/overwrites its sheets.
"""
import csv
import io
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from grading.results import (
    ANSWER_KEY_HINTS,
    NAO_RESPONDEU,
    QUESTION_COLUMN,
    SCORE_ROW,
    parse_verdict,
    question_number,
)

BACK_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR_ENV = "CPE_ARTIFACTS_DIR"
RESULTS_FILENAME = "ResultsByQuestion.csv"
MARKED_DIRNAME = "CheckedOMRs"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def artifacts_root() -> Path:
    configured = os.environ.get(ARTIFACTS_DIR_ENV)
    return Path(configured) if configured else BACK_DIR / "outputs" / "gradings"


def _exam_dir(exam_id: int) -> Path:
    return artifacts_root() / str(int(exam_id))


def save(exam_id: int, raw_csv: str, marked_images: Dict[str, bytes]) -> None:
    exam_dir = _exam_dir(exam_id)
    marked_dir = exam_dir / MARKED_DIRNAME
    marked_dir.mkdir(parents=True, exist_ok=True)
    if raw_csv:
        (exam_dir / RESULTS_FILENAME).write_text(raw_csv, encoding="utf-8")
    for file_name, content in marked_images.items():
        # Path(...).name: a sheet's file name never gets to pick the directory
        (marked_dir / Path(file_name).name).write_bytes(content)


def results_csv_path(exam_id: int) -> Optional[Path]:
    path = _exam_dir(exam_id) / RESULTS_FILENAME
    return path if path.is_file() else None


def marked_sheet_names(exam_id: int) -> List[str]:
    marked_dir = _exam_dir(exam_id) / MARKED_DIRNAME
    if not marked_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in marked_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def marked_sheet_path(exam_id: int, file_name: str) -> Optional[Path]:
    """Path of one marked sheet, only if it is one of the exam's listed files."""
    if file_name not in marked_sheet_names(exam_id):
        return None
    return _exam_dir(exam_id) / MARKED_DIRNAME / file_name


def delete(exam_id: int) -> None:
    """Remove everything stored for an exam. Missing folder is fine."""
    shutil.rmtree(_exam_dir(exam_id), ignore_errors=True)


def _number(text: str):
    """A score cell as int/float so the csv writer leaves it unquoted."""
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def apply_answer_key(exam_id: int, new_answers: Dict[int, str]) -> bool:
    """Bring the stored ResultsByQuestion.csv in line with a changed gabarito.

    Mirrors db.repositories.update_answer_key on the file: for each changed
    question the gabarito cell is replaced and every sheet's cell is re-judged
    from the mark it already holds; the score row moves by one per answer that
    became (or stopped being) correct. Returns False when there is no file.
    """
    path = results_csv_path(exam_id)
    if path is None or not new_answers:
        return False

    raw = path.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return False
    header = [cell.strip() for cell in rows[0]]
    question_index = header.index(QUESTION_COLUMN) if QUESTION_COLUMN in header else 0
    score_row = next(
        (row for row in rows[1:] if row[question_index].strip() == SCORE_ROW), None
    )
    if score_row is None:
        # Without the score row sheets cannot be told from answer-key columns
        return False

    # Same rule as grading.results.guess_meta_columns: the score row is blank
    # under the answer-key columns and numeric under each sheet
    sheet_indexes, meta_indexes = [], []
    for index in range(len(header)):
        if index == question_index:
            continue
        cell = score_row[index] if index < len(score_row) else ""
        (sheet_indexes if isinstance(_number(cell), (int, float)) else meta_indexes).append(index)
    key_index = next(
        (
            index
            for hint in ANSWER_KEY_HINTS
            for index in meta_indexes
            if hint in header[index].lower()
        ),
        None,
    )

    deltas = {index: 0 for index in sheet_indexes}
    for row in rows[1:]:
        if row is score_row:
            continue
        new_answer = new_answers.get(question_number(row[question_index]))
        if new_answer is None:
            continue
        if key_index is not None and key_index < len(row):
            row[key_index] = new_answer
        for index in sheet_indexes:
            if index >= len(row):
                continue
            resultado, marked = parse_verdict(row[index])
            if resultado == NAO_RESPONDEU:
                continue
            was_correct = row[index].strip().lower().startswith("correct")
            is_correct = marked.strip().casefold() == new_answer.casefold()
            row[index] = f"{'correct' if is_correct else 'incorrect'}-{marked}"
            deltas[index] += int(is_correct) - int(was_correct)

    for index, delta in deltas.items():
        if delta:
            score_row[index] = str(_number(score_row[index]) + delta)

    out = io.StringIO()
    writer = csv.writer(
        out,
        quoting=csv.QUOTE_NONNUMERIC,
        lineterminator="\r\n" if "\r\n" in raw else "\n",
    )
    for row in rows:
        if row is score_row:
            row = [
                _number(cell) if index in deltas else cell
                for index, cell in enumerate(row)
            ]
        writer.writerow(row)
    path.write_text(out.getvalue(), encoding="utf-8")
    return True
