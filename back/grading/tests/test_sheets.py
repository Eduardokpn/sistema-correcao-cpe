"""The per-size CPE sheet templates: selection, answer-key validation and an
end-to-end read of a synthetic sheet through the real OMR pipeline."""
import json

import pandas as pd
import pytest

from grading import sheets
from grading.sheets import (
    QUESTION_COUNTS,
    SheetError,
    answer_key_mismatch,
    check_answer_key,
    template_and_config_paths,
)

OPTIONS = "ABCDE"


@pytest.mark.parametrize("question_count", QUESTION_COUNTS)
def test_each_size_has_a_template_reading_exactly_its_questions(question_count):
    template_path, config_path = template_and_config_paths(question_count)
    assert template_path.name == f"template_{question_count}.json"
    assert config_path is not None and config_path.name == "config.json"

    template = json.loads(template_path.read_text(encoding="utf-8"))
    questions = set()
    for block in template["fieldBlocks"].values():
        for label in block["fieldLabels"]:
            first, last = label[1:].split("..")
            questions.update(range(int(first), int(last) + 1))
    assert questions == set(range(1, question_count + 1))


def test_unknown_size_is_rejected():
    with pytest.raises(SheetError):
        template_and_config_paths(85)


def test_no_size_means_the_default_sheet():
    template_path, _config = template_and_config_paths(None)
    assert template_path.name == f"template_{sheets.DEFAULT_QUESTION_COUNT}.json"


def test_answer_key_mismatch_both_directions():
    outside, missing = answer_key_mismatch(["q1", "q2", "q85", "3"], 80)
    assert outside == ["q85", "3"]
    assert missing[:2] == ["q3", "q4"] and len(missing) == 78


def test_check_answer_key_blocks_only_questions_outside_the_sheet():
    check_answer_key(["q1", "q2"], 80)  # missing answers only warn in the UI
    with pytest.raises(SheetError, match="q85"):
        check_answer_key(["q1", "q85"], 80)


# --------------------------------------------------------------------------- #
# End to end on a drawn sheet
# --------------------------------------------------------------------------- #
def _draw_sheet(template, marked):
    """A white page with the four corner L marks and `marked` bubbles filled.

    `marked` maps question label -> option letter. Bubble positions come from
    the template, mapped into the frame the marks' centroids define - the same
    frame CropOnCornerMarks crops to.
    """
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    width, height = 1240, 1754
    page = np.full((height, width), 255, dtype=np.uint8)

    arm, thickness, margin = 36, 12, 50
    centroids = []
    for right, bottom in ((0, 0), (1, 0), (1, 1), (0, 1)):
        mask = np.zeros_like(page)
        x0 = width - margin - arm if right else margin
        y0 = height - margin - arm if bottom else margin
        # Horizontal arm on the outer edge, vertical arm on the outer side
        hy = y0 + arm - thickness if bottom else y0
        vx = x0 + arm - thickness if right else x0
        mask[hy : hy + thickness, x0 : x0 + arm] = 255
        mask[y0 : y0 + arm, vx : vx + thickness] = 255
        page[mask > 0] = 0
        moments = cv2.moments(mask, binaryImage=True)
        centroids.append(
            (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])
        )

    (left, top), (right_x, _), (_, bottom_y), _ = centroids
    page_width, page_height = template["pageDimensions"]
    scale_x = (right_x - left) / page_width
    scale_y = (bottom_y - top) / page_height
    bubble_w, bubble_h = template["bubbleDimensions"]

    for block in template["fieldBlocks"].values():
        origin_x, origin_y = block["origin"]
        first, last = (int(n) for n in block["fieldLabels"][0][1:].split(".."))
        for row, number in enumerate(range(first, last + 1)):
            for column, option in enumerate(OPTIONS):
                centre = (
                    int(round(left + (origin_x + column * block["bubblesGap"] + bubble_w / 2) * scale_x)),
                    int(round(top + (origin_y + row * block["labelsGap"] + bubble_h / 2) * scale_y)),
                )
                filled = marked.get(f"q{number}") == option
                cv2.circle(page, centre, 9, 0, -1 if filled else 1)

    encoded, buffer = cv2.imencode(".png", page)
    assert encoded
    return buffer.tobytes()


@pytest.mark.parametrize("question_count", QUESTION_COUNTS)
def test_synthetic_sheet_is_read_through_the_pipeline(question_count):
    pytest.importorskip("cv2")

    template_path, _config = template_and_config_paths(question_count)
    template = json.loads(template_path.read_text(encoding="utf-8"))

    labels = [f"q{number}" for number in range(1, question_count + 1)]
    key = {label: OPTIONS[index % 5] for index, label in enumerate(labels)}
    # The student answers everything right except q1 (wrong) and q2 (blank)
    marked = dict(key)
    marked["q1"] = "C" if key["q1"] != "C" else "D"
    del marked["q2"]

    answer_key = pd.DataFrame(
        {"Questão": labels, "Gabarito": [key[label] for label in labels]}
    )
    # Accent in the file name: cv2.imread used to return None for these on Windows
    from grading.bridge import grade

    graded = grade(
        [("Isabelli_Valença.png", _draw_sheet(template, marked))],
        answer_key,
        question_count=question_count,
    )
    results = graded.results
    # The run's files come back in memory and its temp folder is gone
    assert "Isabelli_Valença.png" in graded.raw_csv
    assert list(graded.marked_images) == ["Isabelli_Valença.png"]
    assert graded.marked_images["Isabelli_Valença.png"][:4] == b"\x89PNG"
    assert not graded.work_dir.exists()

    column = "Isabelli_Valença.png"
    by_question = results.set_index("question")[column]
    assert by_question["q1"].startswith("incorrect")
    assert by_question["q2"].startswith("unmarked")
    correct = [label for label in labels if by_question[label].startswith("correct")]
    assert len(correct) == question_count - 2
    assert float(by_question["score"]) == question_count - 2


def test_answer_key_outside_the_sheet_is_refused_before_grading():
    from grading.bridge import grade_and_frame

    answer_key = pd.DataFrame({"Questão": ["q1", "q85"], "Gabarito": ["A", "B"]})
    with pytest.raises(SheetError, match="q85"):
        grade_and_frame([("a.png", b"")], answer_key, question_count=80)


def test_failed_run_leaves_no_temp_folder(monkeypatch, tmp_path):
    import tempfile

    from grading import pipeline

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def boom(*_args, **_kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(pipeline, "entry_point", boom)
    answer_key = pd.DataFrame({"Questão": ["q1"], "Gabarito": ["A"]})
    with pytest.raises(pipeline.CorrectionError):
        pipeline.run_correction(
            [("a.png", b"x")], b"{}", answer_key, "Questão", "Gabarito"
        )
    assert list(tmp_path.iterdir()) == []
