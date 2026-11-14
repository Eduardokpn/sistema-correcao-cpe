"""FastAPI application: builds the app and includes the routers in api/routers/.

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

import os

from fastapi import FastAPI

from api.deps import get_db  # noqa: F401 - re-exported: tests override it
from api.routers import exams, gradings, lookups, performance, results
from db.database import init_db


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

    @app.get("/health")
    def health():
        return {"status": "ok"}

    for module in (exams, lookups, results, gradings, performance):
        app.include_router(module.router)
    return app


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
