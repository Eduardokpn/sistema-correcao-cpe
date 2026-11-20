"""The CPE answer sheets: one template per exam size.

The templates live in folha-cpe/ and are measured from the four L-shaped marks
printed at the corners of the sheet (see omrchecker/src/processors/CropOnCornerMarks.py),
so the same template reads a scan regardless of how the scanner positioned,
rotated or scaled the page. The 72-question exam is printed on the 90-question
sheet and simply stops at q72.

Kept free of the OMR/OpenCV stack so the API can validate a request before
importing the pipeline.
"""
from pathlib import Path

BACK_DIR = Path(__file__).resolve().parent.parent
FOLHA_DIR = BACK_DIR / "folha-cpe"
QUESTION_COUNTS = (72, 80, 90)
DEFAULT_QUESTION_COUNT = 80


class SheetError(ValueError):
    """The request cannot be graded with the chosen sheet."""


def template_and_config_paths(question_count=None):
    """(template_path, config_path or None) for an exam size.

    With question_count=None it uses the default CPE sheet.
    """
    if question_count is None:
        question_count = DEFAULT_QUESTION_COUNT

    if question_count not in QUESTION_COUNTS:
        raise SheetError(
            f"Tamanho de prova inválido: {question_count}. "
            f"Opções: {', '.join(str(count) for count in QUESTION_COUNTS)}."
        )
    template_path = FOLHA_DIR / f"template_{question_count}.json"
    if not template_path.exists():
        raise SheetError(
            f"O template da folha não foi encontrado em folha-cpe/{template_path.name}."
        )
    config_path = FOLHA_DIR / "config.json"
    return template_path, config_path if config_path.exists() else None


def answer_key_mismatch(key_questions, question_count):
    """(questions the sheet lacks, sheet questions missing from the key)."""
    sheet_questions = [f"q{number}" for number in range(1, question_count + 1)]
    key_questions = [str(question).strip() for question in key_questions]
    outside_sheet = [q for q in key_questions if q not in set(sheet_questions)]
    without_answer = [q for q in sheet_questions if q not in set(key_questions)]
    return outside_sheet, without_answer


def short_list(items, limit=6):
    shown = ", ".join(str(item) for item in items[:limit])
    return shown + (f" e mais {len(items) - limit}" if len(items) > limit else "")


def check_answer_key(key_questions, question_count):
    """Raise SheetError when the key has questions the chosen sheet cannot read."""
    outside_sheet, _without_answer = answer_key_mismatch(key_questions, question_count)
    if outside_sheet:
        raise SheetError(
            f"O gabarito tem questões que a folha de {question_count} não tem: "
            f"{short_list(outside_sheet)}. As questões precisam se chamar q1, q2, … "
            f"até q{question_count}."
        )
