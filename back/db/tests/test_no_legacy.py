"""Guard test: the retired webapp module and Planilha.csv must stay gone.

Fails if any Python source under back/ or front/ imports the old webapp package
or references the legacy Planilha.csv, so the legacy paths can't creep back in.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACK = REPO_ROOT / "back"
FRONT = REPO_ROOT / "front"

IMPORT_WEBAPP = re.compile(r"^\s*(from|import)\s+webapp\b", re.MULTILINE)
PLANILHA_CSV = re.compile(r"Planilha\.csv")


THIS_FILE = Path(__file__).resolve()


def _python_files():
    for base in (BACK, FRONT):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.resolve() == THIS_FILE:
                # Skip the guard test itself - it names the patterns it forbids
                continue
            yield path


def test_no_webapp_imports():
    offenders = [
        str(path)
        for path in _python_files()
        if IMPORT_WEBAPP.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"Still importing webapp: {offenders}"


def test_no_planilha_csv_reads():
    offenders = [
        str(path)
        for path in _python_files()
        if PLANILHA_CSV.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"Still referencing Planilha.csv: {offenders}"


def test_webapp_directory_removed():
    assert not (BACK / "webapp").exists(), "back/webapp/ should have been deleted"


def test_planilha_csv_removed():
    assert not (FRONT / "Planilha.csv").exists(), "front/Planilha.csv should be gone"
