"""FastAPI application wiring the data package to HTTP endpoints.

Endpoints:
  GET  /health                         - liveness
  POST /exams                          - create/get an exam
  GET  /exams                          - list exams
  DELETE /exams/{id}                   - delete an exam and its grading files
  GET  /exams/{id}/answer-key          - the exam's stored gabarito
  PUT  /exams/{id}/answer-key          - change the gabarito and regrade from stored marks
  GET  /classes                        - list classes
  GET  /students                       - list students (optional class filter)
  GET  /subjects                       - list subjects
  GET  /results                        - long-format rows (filters: exam/class/student/subject)
  POST /gradings/results-csv           - ingest a ResultsByQuestion.csv + metadata
  POST /gradings                       - grade uploaded images then ingest (needs OMR stack)
  GET  /exams/{id}/results-by-question.csv - raw sheet of the latest image grading
  GET  /exams/{id}/marked-sheets[/{file}]  - sheets with the detected marks drawn on
  GET  /performance/student-subject    - Q1
  GET  /performance/student-exam       - Q2
  GET  /performance/class-exam         - Q3
  GET  /trends/class/{class_id}        - Q4 (overall + per subject over time)

The grading endpoint that reads images imports the OMR pipeline lazily so the
app (and its tests) load without the OpenCV stack present.
"""
from __future__ import annotations

import io
import json
import os
from datetime import date
from typing import List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api import schemas
from data import repositories as repo
from data.database import get_session_factory, init_db
from data.repositories import LONG_FORMAT_COLUMNS
from grading import artifacts
from grading.ingest import SheetMetadata, ingest_results_by_question
from grading.results import blank_sheets, load_results_by_question


def get_db() -> Session:
    """Request-scoped session dependency."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def create_app(initialize_schema: bool = False) -> FastAPI:
    """Build the FastAPI app.

    The schema is owned by Alembic (`alembic upgrade head`), NOT by the app.
    Creating tables here would bypass Alembic and leave the alembic_version
    table empty, which then makes `alembic upgrade head` fail trying to recreate
    tables that already exist. So initialize_schema defaults to False and should
    only ever be set True by tests that run against a throwaway database.
    """
    app = FastAPI(
        title="CPE OMR API",
        version="1.0.0",
        description="Correção de provas OMR e desempenho das turmas.",
    )

    if initialize_schema:
        init_db()

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ----------------------------------------------------------------- exams
    @app.post("/exams", response_model=schemas.ExamOut)
    def create_exam(payload: schemas.ExamIn, db: Session = Depends(get_db)):
        exam = repo.get_or_create_exam(
            db,
            name=payload.name,
            applied_on=payload.applied_on,
            sequence=payload.sequence,
        )
        db.commit()
        return schemas.ExamOut(
            id=exam.id,
            name=exam.name,
            applied_on=exam.applied_on,
            sequence=exam.sequence,
        )

    @app.get("/exams", response_model=List[schemas.ExamOut])
    def list_exams(db: Session = Depends(get_db)):
        return [
            schemas.ExamOut(
                id=e.id, name=e.name, applied_on=e.applied_on, sequence=e.sequence
            )
            for e in repo.list_exams(db)
        ]

    @app.delete("/exams/{exam_id}", status_code=204)
    def delete_exam(exam_id: int, db: Session = Depends(get_db)):
        """Delete an exam: its questions, sheets, answers and grading files.

        Students and classes are kept.
        """
        if not repo.delete_exam(db, exam_id):
            raise HTTPException(status_code=404, detail="Simulado não encontrado.")
        db.commit()
        # The database is the source of truth; leftover files are harmless
        artifacts.delete(exam_id)

    @app.get(
        "/exams/{exam_id}/answer-key",
        response_model=List[schemas.AnswerKeyItemOut],
    )
    def exam_answer_key(exam_id: int, db: Session = Depends(get_db)):
        """The exam's stored gabarito, one item per question in sheet order."""
        if repo.get_exam(db, exam_id) is None:
            raise HTTPException(status_code=404, detail="Simulado não encontrado.")
        return [
            schemas.AnswerKeyItemOut(
                number=q.number,
                correct_answer=q.correct_answer,
                area=q.subject.name if q.subject else None,
                subarea=q.subtopic.name if q.subtopic else None,
            )
            for q in repo.list_questions(db, exam_id)
        ]

    @app.put(
        "/exams/{exam_id}/answer-key",
        response_model=schemas.AnswerKeyUpdateOut,
    )
    def update_exam_answer_key(
        exam_id: int,
        changes: List[schemas.AnswerKeyChangeIn],
        db: Session = Depends(get_db),
    ):
        """Change the gabarito of the listed questions and regrade the exam.

        Verdicts and scores are recomputed from the marks already stored, so no
        sheet has to be uploaded again. Questions left out keep their gabarito.
        """
        if repo.get_exam(db, exam_id) is None:
            raise HTTPException(status_code=404, detail="Simulado não encontrado.")
        new_answers = {c.number: c.correct_answer.strip() for c in changes}
        try:
            summary = repo.update_answer_key(db, exam_id, new_answers)
        except repo.AnswerKeyError as error:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(error))
        db.commit()
        # Best effort, like saving them: the database already has the change
        try:
            artifacts.apply_answer_key(exam_id, new_answers)
        except (OSError, ValueError, IndexError):
            pass
        return schemas.AnswerKeyUpdateOut(
            questions_changed=summary.questions_changed,
            answers_regraded=summary.answers_regraded,
            sheets_rescored=summary.sheets_rescored,
        )

    # --------------------------------------------------------------- lookups
    @app.get("/classes", response_model=List[schemas.ClassOut])
    def list_classes(db: Session = Depends(get_db)):
        return [
            schemas.ClassOut(id=c.id, name=c.name, turno=c.turno)
            for c in repo.list_classes(db)
        ]

    @app.get("/students", response_model=List[schemas.StudentOut])
    def list_students(
        class_id: Optional[int] = Query(default=None), db: Session = Depends(get_db)
    ):
        return [
            schemas.StudentOut(id=s.id, name=s.name, class_id=s.class_id)
            for s in repo.list_students(db, class_id=class_id)
        ]

    @app.get("/subjects", response_model=List[schemas.SubjectOut])
    def list_subjects(db: Session = Depends(get_db)):
        return [
            schemas.SubjectOut(id=s.id, name=s.name)
            for s in repo.list_subjects(db)
        ]

    # --------------------------------------------------------------- results
    @app.get("/results", response_model=schemas.ResultsOut)
    def get_results(
        exam_id: Optional[int] = Query(default=None),
        class_id: Optional[int] = Query(default=None),
        student_id: Optional[int] = Query(default=None),
        subject_id: Optional[int] = Query(default=None),
        db: Session = Depends(get_db),
    ):
        rows = repo.long_format_rows(
            db,
            exam_id=exam_id,
            class_id=class_id,
            student_id=student_id,
            subject_id=subject_id,
        )
        return schemas.ResultsOut(columns=LONG_FORMAT_COLUMNS, rows=rows)

    # -------------------------------------------------------------- gradings
    @app.post("/gradings/results-csv", response_model=schemas.GradingResultOut)
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

    @app.post("/gradings", response_model=schemas.GradingResultOut)
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
            from api.grading_bridge import grade
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
    @app.get("/exams/{exam_id}/results-by-question.csv")
    def results_by_question_csv(exam_id: int):
        """The raw ResultsByQuestion.csv of the exam's latest image grading."""
        path = artifacts.results_csv_path(exam_id)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail="Este simulado não tem planilha ResultsByQuestion guardada.",
            )
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @app.get("/exams/{exam_id}/marked-sheets", response_model=List[str])
    def marked_sheets(exam_id: int):
        """File names of the exam's sheets with the detected marks drawn on."""
        return artifacts.marked_sheet_names(exam_id)

    @app.get("/exams/{exam_id}/marked-sheets/{file_name}")
    def marked_sheet(exam_id: int, file_name: str):
        path = artifacts.marked_sheet_path(exam_id, file_name)
        if path is None:
            raise HTTPException(status_code=404, detail="Folha não encontrada.")
        return FileResponse(path)

    # ---------------------------------------------------- teacher questions
    @app.get("/performance/student-subject", response_model=schemas.PerformanceOut)
    def student_subject(
        student_id: int, subject_id: int, db: Session = Depends(get_db)
    ):
        summary = repo.student_performance_in_subject(db, student_id, subject_id)
        return _performance_out(summary)

    @app.get("/performance/student-exam", response_model=schemas.PerformanceOut)
    def student_exam(student_id: int, exam_id: int, db: Session = Depends(get_db)):
        summary = repo.student_performance_in_exam(db, student_id, exam_id)
        return _performance_out(summary)

    @app.get("/performance/class-exam", response_model=schemas.PerformanceOut)
    def class_exam(class_id: int, exam_id: int, db: Session = Depends(get_db)):
        summary = repo.class_performance_in_exam(db, class_id, exam_id)
        return _performance_out(summary)

    @app.get("/trends/class/{class_id}", response_model=schemas.TrendOut)
    def class_trend(class_id: int, db: Session = Depends(get_db)):
        points = repo.class_improvement_over_time(db, class_id)
        return schemas.TrendOut(
            class_id=class_id,
            points=[
                schemas.SubjectTrendPoint(
                    exam_id=p.exam_id,
                    exam_name=p.exam_name,
                    applied_on=p.applied_on,
                    sequence=p.sequence,
                    overall=_performance_out(p.summary),
                    by_subject=p.by_subject,
                )
                for p in points
            ],
        )


def _performance_out(summary: repo.PerformanceSummary) -> schemas.PerformanceOut:
    return schemas.PerformanceOut(
        total=summary.total,
        acertos=summary.acertos,
        erros=summary.erros,
        em_branco=summary.em_branco,
        taxa_acerto=summary.taxa_acerto,
    )


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


# Default app instance for `uvicorn api.app:app`
app = create_app()


# Default host/port, overridable by env. The project default port is 8001 (8000
# is a common collision with other local services / Docker mappings).
DEFAULT_HOST = os.environ.get("CPE_API_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CPE_API_PORT", "8001"))


def main() -> None:
    """Run the API with the project defaults: `python -m api.app`.

    This is the recommended way to start the backend because it binds to port
    8001 by default. Using the bare `uvicorn api.app:app` CLI instead would fall
    back to uvicorn's own default of 8000.
    """
    import uvicorn

    uvicorn.run(
        "api.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=os.environ.get("CPE_API_RELOAD", "1") == "1",
    )


if __name__ == "__main__":
    main()
