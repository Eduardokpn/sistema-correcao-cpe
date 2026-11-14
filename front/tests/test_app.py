"""Streamlit AppTest for front/app.py with a mocked API client.

Runs the app end-to-end in-process (no server, no network) by swapping the real
CPEClient for a fake that serves a canned long-format payload, then asserts the
sidebar sections render their charts and filters without error.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

FRONT_DIR = Path(__file__).resolve().parent.parent
if str(FRONT_DIR) not in sys.path:
    sys.path.insert(0, str(FRONT_DIR))

from api_client import LONG_FORMAT_COLUMNS  # noqa: E402

APP_PATH = str(FRONT_DIR / "app.py")

ROWS = [
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
        "Nome do Aluno": "Pedro",
        "Turma": "3A",
        "Área": "Linguagem e Códigos",
        "Subárea": "Português",
        "Número da questão": 2,
        "Questão": "Q2",
        "Resposta do aluno": "B",
        "Resultado": "Erro",
    },
]


class FakeClient:
    base_url = "http://fake"

    def health(self):
        return True

    def exams(self):
        return [{"id": 1, "name": "Simulado 1", "applied_on": None, "sequence": 1}]

    def long_format_dataframe(self, **filters):
        frame = pd.DataFrame(ROWS)
        return frame[LONG_FORMAT_COLUMNS]

    def classes(self):
        return [{"id": 1, "name": "3A", "turno": "vespertino"}]

    def results_by_question_csv(self, exam_id):
        return b"question,giovanna.png\nq1,correct-E\n"

    def marked_sheets(self, exam_id):
        return ["giovanna.png"]

    def marked_sheet(self, exam_id, file_name):
        return None

    def class_trend(self, class_id):
        return {
            "class_id": class_id,
            "points": [
                {
                    "exam_id": 1,
                    "exam_name": "Simulado 1",
                    "applied_on": "2026-03-01",
                    "sequence": 1,
                    "overall": {
                        "total": 4,
                        "acertos": 1,
                        "erros": 3,
                        "em_branco": 0,
                        "taxa_acerto": 25.0,
                    },
                    "by_subject": {"Matemática": 50.0, "Português": 0.0},
                },
                {
                    "exam_id": 2,
                    "exam_name": "Simulado 2",
                    "applied_on": "2026-05-01",
                    "sequence": 2,
                    "overall": {
                        "total": 4,
                        "acertos": 3,
                        "erros": 1,
                        "em_branco": 0,
                        "taxa_acerto": 75.0,
                    },
                    "by_subject": {"Matemática": 100.0, "Português": 50.0},
                },
            ],
        }


def _clear_streamlit_caches():
    """get_client() is @st.cache_resource; clear it so each run rebuilds it."""
    import streamlit as st

    try:
        st.cache_resource.clear()
    except Exception:
        pass


def _run(section=None):
    """Run the app on one sidebar section (the menu renders one at a time)."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    if section:
        at.session_state["secao"] = section
    return at.run()


@pytest.fixture
def app():
    # Patch the class so the app's cached get_client() builds our fake
    _clear_streamlit_caches()
    with patch("api_client.CPEClient", FakeClient):
        yield _run()


@pytest.fixture
def section():
    """Factory: section("dashboard") -> the app run on that section."""
    _clear_streamlit_caches()
    with patch("api_client.CPEClient", FakeClient):
        yield _run


def test_app_runs_without_exception(app):
    assert not app.exception


def test_every_section_runs_without_exception(section):
    for slug in ("correcao", "dashboard", "evolucao", "dados"):
        assert not section(slug).exception, slug


def test_sidebar_menu_switches_section(app):
    # Opens on Correção, with the exam-size choice (72 / 80 / 90, default 80)
    assert "Tamanho da prova" in [h.value for h in app.subheader]
    size = next(r for r in app.radio if r.label == "Quantidade de questões")
    assert list(size.options) == ["72 questões", "80 questões", "90 questões"]
    assert size.value == 80

    app.sidebar.button(key="nav_dashboard").click().run()
    assert not app.exception
    assert "2. Taxa de acerto por questão" in [h.value for h in app.subheader]


def test_dashboard_renders_charts(section):
    # Área and subárea share one section (switched by a radio), so three
    # numbered sections instead of the old four.
    at = section("dashboard")
    subheaders = [h.value for h in at.subheader]
    assert "1. Desempenho por área e subárea" in subheaders
    assert "2. Taxa de acerto por questão" in subheaders
    assert "3. Desempenho por aluno" in subheaders
    assert any(r.label == "Agrupar por" for r in at.radio)


def test_dashboard_without_area_columns_skips_that_section(section):
    blank = [dict(row, **{"Área": None, "Subárea": None}) for row in ROWS]
    with patch.object(
        FakeClient,
        "long_format_dataframe",
        lambda self, **filters: pd.DataFrame(blank)[LONG_FORMAT_COLUMNS],
    ):
        at = section("dashboard")
    assert not at.exception
    subheaders = [h.value for h in at.subheader]
    assert "1. Taxa de acerto por questão" in subheaders
    assert "2. Desempenho por aluno" in subheaders


def test_dados_falls_back_to_last_exam_without_dashboard_filters(section):
    at = section("dados")
    assert "Resumo por aluno" in [h.value for h in at.subheader]


def test_dados_offers_the_grading_files(section):
    at = section("dados")
    assert not at.exception
    assert "Folhas com a leitura marcada" in [h.value for h in at.subheader]
    assert any(t.label == "Mostrar as folhas" for t in at.toggle)


def test_dados_without_grading_files_hides_them(section):
    with patch.object(FakeClient, "results_by_question_csv", lambda self, exam_id: None), \
         patch.object(FakeClient, "marked_sheets", lambda self, exam_id: []):
        at = section("dados")
    assert not at.exception
    assert "Folhas com a leitura marcada" not in [h.value for h in at.subheader]


def test_no_health_error_shown(app):
    errors = [e.value for e in app.error]
    assert not any("não consegui falar com a api" in e.lower() for e in errors)


def test_evolucao_section_renders(section):
    # The evolution section shows the two trend subheaders when >= 2 exams exist
    subheaders = [h.value for h in section("evolucao").subheader]
    assert "Evolução geral da turma" in subheaders
    assert "Evolução por área" in subheaders


def test_health_banner_when_api_down():
    class DownClient(FakeClient):
        def health(self):
            return False

        def exams(self):
            return []

    _clear_streamlit_caches()
    with patch("api_client.CPEClient", DownClient):
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()
        assert not at.exception
        errors = [e.value.lower() for e in at.error]
        assert any("não consegui falar com a api" in e for e in errors)
