"""HTTP client for the CPE OMR backend API.

Thin wrapper over the endpoints the Streamlit app needs. The key method is
`long_format_dataframe`, which turns the /results payload into a DataFrame whose
columns are exactly what front/charts.py expects, so the charts render unchanged.

The backend base URL comes from the CPE_API_URL environment variable, defaulting
to http://localhost:8001.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import quote

import pandas as pd
import requests

DEFAULT_BASE_URL = "http://localhost:8001"
API_URL_ENV = "CPE_API_URL"

# Kept in sync with db.repositories.LONG_FORMAT_COLUMNS
LONG_FORMAT_COLUMNS = [
    "Nome do Aluno",
    "Turma",
    "Área",
    "Subárea",
    "Número da questão",
    "Questão",
    "Resposta do aluno",
    "Resultado",
]


class APIError(RuntimeError):
    """Raised when the backend returns an error or is unreachable."""


class CPEClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base_url = (base_url or os.environ.get(API_URL_ENV, DEFAULT_BASE_URL)).rstrip(
            "/"
        )
        self.timeout = timeout

    # ------------------------------------------------------------------ core
    def _get(self, path: str, params: Optional[dict] = None):
        try:
            response = requests.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
        except requests.RequestException as error:
            raise APIError(f"Não foi possível contatar a API: {error}") from error
        return self._json(response)

    def _post(self, path, json=None, data=None, files=None):
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=json,
                data=data,
                files=files,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise APIError(f"Não foi possível contatar a API: {error}") from error
        return self._json(response)

    @staticmethod
    def _json(response):
        if not response.ok:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass
            raise APIError(f"Erro {response.status_code}: {detail}")
        return response.json()

    # --------------------------------------------------------------- health
    def health(self) -> bool:
        try:
            return self._get("/health").get("status") == "ok"
        except APIError:
            return False

    # -------------------------------------------------------------- lookups
    def exams(self) -> List[dict]:
        return self._get("/exams")

    def delete_exam(self, exam_id: int) -> None:
        """Delete an exam with its results and grading files."""
        try:
            response = requests.delete(
                f"{self.base_url}/exams/{exam_id}", timeout=self.timeout
            )
        except requests.RequestException as error:
            raise APIError(f"Não foi possível contatar a API: {error}") from error
        if response.status_code != 204:
            self._json(response)

    def answer_key(self, exam_id: int) -> List[dict]:
        """The exam's stored gabarito: number, correct_answer, area, subarea."""
        return self._get(f"/exams/{exam_id}/answer-key")

    def update_answer_key(self, exam_id: int, changes: List[dict]) -> dict:
        """Change the gabarito of some questions and regrade the exam.

        `changes` is a list of {"number": 36, "correct_answer": "D"}.
        """
        try:
            response = requests.put(
                f"{self.base_url}/exams/{exam_id}/answer-key",
                json=changes,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise APIError(f"Não foi possível contatar a API: {error}") from error
        return self._json(response)

    def classes(self) -> List[dict]:
        return self._get("/classes")

    def students(self, class_id: Optional[int] = None) -> List[dict]:
        params = {"class_id": class_id} if class_id is not None else None
        return self._get("/students", params=params)

    def subjects(self) -> List[dict]:
        return self._get("/subjects")

    def create_exam(
        self,
        name: str,
        applied_on: Optional[date] = None,
        sequence: Optional[int] = None,
    ) -> dict:
        payload = {"name": name}
        if applied_on is not None:
            payload["applied_on"] = applied_on.isoformat()
        if sequence is not None:
            payload["sequence"] = sequence
        return self._post("/exams", json=payload)

    # -------------------------------------------------------------- results
    def results(
        self,
        exam_id: Optional[int] = None,
        class_id: Optional[int] = None,
        student_id: Optional[int] = None,
        subject_id: Optional[int] = None,
    ) -> dict:
        params = {
            key: value
            for key, value in {
                "exam_id": exam_id,
                "class_id": class_id,
                "student_id": student_id,
                "subject_id": subject_id,
            }.items()
            if value is not None
        }
        return self._get("/results", params=params or None)

    def long_format_dataframe(self, **filters) -> pd.DataFrame:
        """Fetch /results and return a DataFrame the charts can read directly."""
        payload = self.results(**filters)
        rows = payload.get("rows", [])
        columns = payload.get("columns", LONG_FORMAT_COLUMNS)
        return rows_to_dataframe(rows, columns)

    # ------------------------------------------------------------- gradings
    def ingest_results_csv(
        self,
        csv_bytes: bytes,
        exam_name: str,
        applied_on: Optional[date] = None,
        sequence: Optional[int] = None,
        student_names: Optional[Dict[str, str]] = None,
        student_classes: Optional[Dict[str, str]] = None,
        class_turnos: Optional[Dict[str, str]] = None,
        question_count: Optional[int] = None,
    ) -> dict:
        import json

        data = {"exam_name": exam_name}
        if question_count is not None:
            data["question_count"] = str(question_count)
        if applied_on is not None:
            data["applied_on"] = applied_on.isoformat()
        if sequence is not None:
            data["sequence"] = str(sequence)
        if student_names:
            data["student_names"] = json.dumps(student_names)
        if student_classes:
            data["student_classes"] = json.dumps(student_classes)
        if class_turnos:
            data["class_turnos"] = json.dumps(class_turnos)
        files = {"results_csv": ("ResultsByQuestion.csv", csv_bytes, "text/csv")}
        return self._post("/gradings/results-csv", data=data, files=files)

    def grade_images(
        self,
        images: List[tuple],
        answer_key_bytes: bytes,
        answer_key_name: str,
        exam_name: str,
        applied_on: Optional[date] = None,
        sequence: Optional[int] = None,
        student_names: Optional[Dict[str, str]] = None,
        student_classes: Optional[Dict[str, str]] = None,
        class_turnos: Optional[Dict[str, str]] = None,
        question_count: Optional[int] = None,
    ) -> dict:
        import json

        data = {"exam_name": exam_name}
        if question_count is not None:
            data["question_count"] = str(question_count)
        if applied_on is not None:
            data["applied_on"] = applied_on.isoformat()
        if sequence is not None:
            data["sequence"] = str(sequence)
        if student_names:
            data["student_names"] = json.dumps(student_names)
        if student_classes:
            data["student_classes"] = json.dumps(student_classes)
        if class_turnos:
            data["class_turnos"] = json.dumps(class_turnos)

        files = [("images", (name, content)) for name, content in images]
        files.append(("answer_key", (answer_key_name, answer_key_bytes)))
        return self._post("/gradings", data=data, files=files)

    # -------------------------------------------------------- grading files
    def _get_bytes(self, path: str) -> Optional[bytes]:
        """Raw body of a file endpoint, or None when the API has no such file."""
        try:
            response = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
        except requests.RequestException as error:
            raise APIError(f"Não foi possível contatar a API: {error}") from error
        if response.status_code == 404:
            return None
        if not response.ok:
            raise APIError(f"Erro {response.status_code}: {response.text}")
        return response.content

    def results_by_question_csv(self, exam_id: int) -> Optional[bytes]:
        """Raw ResultsByQuestion.csv of the exam's latest image grading."""
        return self._get_bytes(f"/exams/{exam_id}/results-by-question.csv")

    def marked_sheets(self, exam_id: int) -> List[str]:
        """File names of the sheets with the detected marks drawn on top."""
        return self._get(f"/exams/{exam_id}/marked-sheets")

    def marked_sheet(self, exam_id: int, file_name: str) -> Optional[bytes]:
        return self._get_bytes(
            f"/exams/{exam_id}/marked-sheets/{quote(file_name, safe='')}"
        )

    # ---------------------------------------------------- teacher questions
    def student_subject_performance(self, student_id: int, subject_id: int) -> dict:
        return self._get(
            "/performance/student-subject",
            params={"student_id": student_id, "subject_id": subject_id},
        )

    def student_exam_performance(self, student_id: int, exam_id: int) -> dict:
        return self._get(
            "/performance/student-exam",
            params={"student_id": student_id, "exam_id": exam_id},
        )

    def class_exam_performance(self, class_id: int, exam_id: int) -> dict:
        return self._get(
            "/performance/class-exam",
            params={"class_id": class_id, "exam_id": exam_id},
        )

    def class_trend(self, class_id: int) -> dict:
        return self._get(f"/trends/class/{class_id}")


def rows_to_dataframe(rows: List[dict], columns=None) -> pd.DataFrame:
    """Build a DataFrame with the canonical long-format columns leading.

    Guarantees the chart columns exist even when the result set is empty, so the
    charts never blow up on a missing key.
    """
    columns = columns or LONG_FORMAT_COLUMNS
    if not rows:
        return pd.DataFrame(columns=LONG_FORMAT_COLUMNS)
    frame = pd.DataFrame(rows)
    for column in LONG_FORMAT_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    ordered = LONG_FORMAT_COLUMNS + [
        column for column in frame.columns if column not in LONG_FORMAT_COLUMNS
    ]
    return frame[ordered]
