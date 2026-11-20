"""Smoke tests: a stubbed API payload flows through the client into the charts.

Asserts that the four charts render (produce a Plotly figure with data) from the
DataFrame the client builds out of a /results-shaped payload, without touching
the network.
"""
import sys
from pathlib import Path

import plotly.graph_objects as go

# front/ is not a package on the path when tests run from back/; add it
FRONT_DIR = Path(__file__).resolve().parent.parent
if str(FRONT_DIR) not in sys.path:
    sys.path.insert(0, str(FRONT_DIR))

import charts  # noqa: E402
from api_client import LONG_FORMAT_COLUMNS, rows_to_dataframe  # noqa: E402

# A /results-shaped payload: two students x three questions across two subjects
PAYLOAD = {
    "columns": LONG_FORMAT_COLUMNS,
    "rows": [
        {
            "Nome do Aluno": "Giovanna",
            "Turma": "3A",
            "Área": "Matemática",
            "Subárea": "Álgebra",
            "Número da questão": 1,
            "Questão": "Q1",
            "Resposta do aluno": "E",
            "Resultado": "Acerto",
        },
        {
            "Nome do Aluno": "Giovanna",
            "Turma": "3A",
            "Área": "Linguagem e Códigos",
            "Subárea": "Português",
            "Número da questão": 2,
            "Questão": "Q2",
            "Resposta do aluno": "-",
            "Resultado": "Não Respondeu",
        },
        {
            "Nome do Aluno": "Pedro",
            "Turma": "3A",
            "Área": "Matemática",
            "Subárea": "Álgebra",
            "Número da questão": 1,
            "Questão": "Q1",
            "Resposta do aluno": "C",
            "Resultado": "Erro",
        },
        {
            "Nome do Aluno": "Pedro",
            "Turma": "3A",
            "Área": "Linguagem e Códigos",
            "Subárea": "Português",
            "Número da questão": 2,
            "Questão": "Q2",
            "Resposta do aluno": "B",
            "Resultado": "Acerto",
        },
    ],
}


def _frame():
    return rows_to_dataframe(PAYLOAD["rows"], PAYLOAD["columns"])


def test_client_builds_canonical_frame():
    frame = _frame()
    assert list(frame.columns) == LONG_FORMAT_COLUMNS
    assert len(frame) == 4
    assert set(frame["Resultado"]) == {"Acerto", "Erro", "Não Respondeu"}


def test_performance_by_area_renders():
    fig = charts.performance_by_dimension(_frame(), "Área")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_performance_by_subarea_renders():
    fig = charts.performance_by_dimension(_frame(), "Subárea")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_accuracy_by_question_renders():
    fig = charts.accuracy_by_question(_frame())
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_accuracy_by_question_sorted_by_rate_renders():
    fig = charts.accuracy_by_question(_frame(), sort_by_rate=True)
    assert isinstance(fig, go.Figure)


def test_ranking_by_student_renders():
    fig = charts.ranking_by_student(_frame())
    assert isinstance(fig, go.Figure)
    # One trace per result category
    assert len(fig.data) == 3


def test_empty_frame_has_columns():
    frame = rows_to_dataframe([], LONG_FORMAT_COLUMNS)
    assert list(frame.columns) == LONG_FORMAT_COLUMNS
    assert frame.empty
