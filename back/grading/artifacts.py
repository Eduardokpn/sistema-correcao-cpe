"""Files a grading run leaves behind, kept per exam.

The database holds the answers; these are the two things it does not: the raw
ResultsByQuestion.csv exactly as the pipeline wrote it, and the sheet images
with the detected marks drawn on top, for visual checking.

They live under CPE_ARTIFACTS_DIR (default back/outputs/gradings/<exam_id>/).
A new grading of the same exam replaces the csv and adds/overwrites its sheets.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

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
