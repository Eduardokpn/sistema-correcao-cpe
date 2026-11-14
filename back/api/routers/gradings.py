"""Grading: read sheet images or ingest a results sheet, and serve the files.

The route that reads images imports the OMR pipeline lazily so the app (and its
tests) load without the OpenCV stack present.
"""
from __future__ import annotations

import io
import json
from datetime import date
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api import schemas
from api.deps import get_db
from db import repositories as repo
from grading import artifacts
from grading.ingest import SheetMetadata, ingest_results_by_question
from grading.results import blank_sheets, load_results_by_question

router = APIRouter()


@router.post("/gradings/results-csv", response_model=schemas.GradingResultOut)
async def ingest_results_csv_endpoint(
    results_csv: UploadFile = File(...),
    exam_name: str = Form(...),
    applied_on: Optional[date] = Form(default=None),
    sequence: Optional[int] = Form(default=None),
    student_names: Optional[str] = Form(default=None),
    student_classes: Optional[str] = Form(default=None),
    class_turnos: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    """Ingest an already-graded ResultsByQuestion.csv plus metadata.

    The *_json form fields are JSON objects mapping sheet file name -> value.
    """
    raw = await results_csv.read()
    try:
        results = load_results_by_question(io.BytesIO(raw))
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"CSV inválido: {error}")

    metadata = SheetMetadata(
        exam_name=exam_name,
        exam_applied_on=applied_on,
        exam_sequence=sequence,
        student_names=_parse_json_map(student_names),
        student_classes=_parse_json_map(student_classes),
        class_turnos=_parse_json_map(class_turnos),
    )
    sheets = ingest_results_by_question(db, results, metadata)
    db.commit()

    exam = repo.get_or_create_exam(db, exam_name)
    db.commit()
    warnings = _blank_sheet_warnings(results)
    return schemas.GradingResultOut(
        exam_id=exam.id,
        exam_name=exam.name,
        sheets_ingested=len(sheets),
        students=[s.student.name for s in sheets],
        warnings=warnings,
    )

@router.post("/gradings", response_model=schemas.GradingResultOut)
async def grade_images_endpoint(
    images: List[UploadFile] = File(...),
    answer_key: UploadFile = File(...),
    exam_name: str = Form(...),
    applied_on: Optional[date] = Form(default=None),
    sequence: Optional[int] = Form(default=None),
    student_names: Optional[str] = Form(default=None),
    student_classes: Optional[str] = Form(default=None),
    class_turnos: Optional[str] = Form(default=None),
    question_count: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
):
    """Grade uploaded sheet images with the OMR pipeline, then ingest.

    `question_count` (72, 80 or 90) selects the CPE sheet template; omitted,
    the default sheet (80) is used.

    Imports the OMR pipeline lazily so the API loads without the OpenCV
    stack; a missing dependency surfaces as a clear 503 instead of an
    import-time crash.
    """
    try:
        from grading.bridge import grade
    except Exception as error:  # pragma: no cover - env-dependent
        raise HTTPException(
            status_code=503,
            detail=f"Pipeline de correção indisponível: {error}",
        )

    image_payload = [(f.filename, await f.read()) for f in images]
    try:
        answer_key_frame = _read_answer_key(
            await answer_key.read(), answer_key.filename
        )
    except ImportError as error:
        # Missing Excel engine (openpyxl/xlrd). Surface a clear, actionable
        # message instead of an opaque 500.
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível ler a planilha Excel: dependência ausente "
                f"no servidor ({error}). Instale 'openpyxl' ou envie a "
                "planilha em CSV."
            ),
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Planilha do gabarito inválida: {error}",
        )
    try:
        # In a worker thread: grading a class takes minutes, and running it
        # here would freeze every other request, the health check included
        graded = await run_in_threadpool(
            grade, image_payload, answer_key_frame, question_count=question_count
        )
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error))

    metadata = SheetMetadata(
        exam_name=exam_name,
        exam_applied_on=applied_on,
        exam_sequence=sequence,
        student_names=_parse_json_map(student_names),
        student_classes=_parse_json_map(student_classes),
        class_turnos=_parse_json_map(class_turnos),
    )
    sheets = ingest_results_by_question(db, graded.results, metadata)
    db.commit()
    exam = repo.get_or_create_exam(db, exam_name)
    db.commit()
    # Best effort: the answers are already saved, so a full disk must not
    # turn a finished correction into an error
    try:
        artifacts.save(exam.id, graded.raw_csv, graded.marked_images)
    except OSError as error:
        graded.log += f"\nWARNING could not store the grading files: {error}"
    return schemas.GradingResultOut(
        exam_id=exam.id,
        exam_name=exam.name,
        sheets_ingested=len(sheets),
        students=[s.student.name for s in sheets],
        log=graded.log,
        warnings=_blank_sheet_warnings(graded.results),
    )


# ------------------------------------------------------- grading files
@router.get("/exams/{exam_id}/results-by-question.csv")
def results_by_question_csv(exam_id: int):
    """The raw ResultsByQuestion.csv of the exam's latest image grading."""
    path = artifacts.results_csv_path(exam_id)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Este simulado não tem planilha ResultsByQuestion guardada.",
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)

@router.get("/exams/{exam_id}/marked-sheets", response_model=List[str])
def marked_sheets(exam_id: int):
    """File names of the exam's sheets with the detected marks drawn on."""
    return artifacts.marked_sheet_names(exam_id)

@router.get("/exams/{exam_id}/marked-sheets/{file_name}")
def marked_sheet(exam_id: int, file_name: str):
    path = artifacts.marked_sheet_path(exam_id, file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Folha não encontrada.")
    return FileResponse(path)


def _blank_sheet_warnings(results: pd.DataFrame) -> List[str]:
    """One message per sheet read without a single mark (saved all the same)."""
    return [
        f"{sheet}: nenhuma marcação lida. A folha foi salva como em branco; "
        "confira o scan e corrija de novo se o aluno respondeu."
        for sheet in blank_sheets(results)
    ]


def _parse_json_map(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"JSON inválido: {value!r}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Esperado um objeto JSON.")
    return parsed


def _read_answer_key(raw: bytes, file_name: Optional[str]) -> pd.DataFrame:
    suffix = (file_name or "").lower()
    if suffix.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw), dtype=str)
    return pd.read_csv(
        io.BytesIO(raw),
        sep=None,
        engine="python",
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
    )
