"""Grading layer for the CPE OMR system.

Wraps the OMR pipeline (omrchecker/src/entry.py) and translates its ResultsByQuestion.csv
output into the long-format contract and into database rows. Split into:

- results.py: parse ResultsByQuestion.csv (verdicts, scores, meta columns) - the
  logic ported out of the old webapp/pipeline.py so it is reusable off the UI.
- ingest.py: turn a parsed results sheet + student/exam metadata into
  db.repositories writes.
- sheets.py: the CPE answer-sheet templates (folha-cpe/) per exam size.
- pipeline.py: runs the engine on uploaded files in a temporary folder.
- bridge.py: what the API calls - picks the template, runs the pipeline and
  returns the results frame, log and marked images.
- artifacts.py: the files a grading leaves behind, stored per exam.
"""
from grading.results import (
    ACERTO,
    ERRO,
    NAO_RESPONDEU,
    QUESTION_COLUMN,
    SCORE_ROW,
    guess_meta_columns,
    load_results_by_question,
    parse_verdict,
    question_number,
    split_scores,
    student_columns,
    student_name_from_file,
)
from grading.ingest import (
    SheetMetadata,
    ingest_results_by_question,
    ingest_results_csv,
)

# NOTE: grading.pipeline (run_correction, CorrectionResult, ...) is intentionally
# NOT imported here. It pulls in the OMR/OpenCV stack via src.entry, so importing
# the grading package for ingest/parsing must not require those heavy deps.
# Import it directly where needed: `from grading.pipeline import run_correction`.

__all__ = [
    "ACERTO",
    "ERRO",
    "NAO_RESPONDEU",
    "QUESTION_COLUMN",
    "SCORE_ROW",
    "guess_meta_columns",
    "load_results_by_question",
    "parse_verdict",
    "question_number",
    "split_scores",
    "student_columns",
    "student_name_from_file",
    "SheetMetadata",
    "ingest_results_by_question",
    "ingest_results_csv",
]
