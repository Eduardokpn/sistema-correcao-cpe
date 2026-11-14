"""Endpoint tests against a temp SQLite DB via FastAPI TestClient.

Seeds data through the /gradings/results-csv ingest endpoint (no OMR stack
needed) and then exercises the read + teacher-question endpoints.
"""
import io
import json

RESULTS_CSV = """question,Área,Subárea,Gabarito,giovanna.png,pedro.png
score,,,,2.0,1.0
q1,Matemática,Álgebra,E,correct-E,incorrect-C
q2,Linguagem e Códigos,Português,B,correct-B,unmarked
q3,Matemática,Geometria,A,unmarked,correct-A
"""


def _ingest(client, exam_name="Simulado 1", applied_on="2026-03-01", sequence=1):
    return client.post(
        "/gradings/results-csv",
        data={
            "exam_name": exam_name,
            "applied_on": applied_on,
            "sequence": str(sequence),
            "student_names": json.dumps(
                {"giovanna.png": "Giovanna", "pedro.png": "Pedro"}
            ),
            "student_classes": json.dumps(
                {"giovanna.png": "3A", "pedro.png": "3A"}
            ),
            "class_turnos": json.dumps({"3A": "vespertino"}),
        },
        files={"results_csv": ("ResultsByQuestion.csv", io.BytesIO(RESULTS_CSV.encode()), "text/csv")},
    )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ingest_and_list_exams(client):
    response = _ingest(client)
    assert response.status_code == 200
    body = response.json()
    assert body["sheets_ingested"] == 2
    assert set(body["students"]) == {"Giovanna", "Pedro"}

    exams = client.get("/exams").json()
    assert len(exams) == 1
    assert exams[0]["name"] == "Simulado 1"
    assert exams[0]["sequence"] == 1


def test_results_shape_and_filters(client):
    _ingest(client)

    results = client.get("/results").json()
    # Canonical long-format columns are advertised
    assert results["columns"][:8] == [
        "Nome do Aluno",
        "Turma",
        "Área",
        "Subárea",
        "Número da questão",
        "Questão",
        "Resposta do aluno",
        "Resultado",
    ]
    # 2 students x 3 questions
    assert len(results["rows"]) == 6

    # Filter by subject: Matemática has q1 + q3 -> 2 per student = 4 rows
    subjects = {s["name"]: s["id"] for s in client.get("/subjects").json()}
    mat_rows = client.get(
        "/results", params={"subject_id": subjects["Matemática"]}
    ).json()["rows"]
    assert len(mat_rows) == 4
    assert all(row["Área"] == "Matemática" for row in mat_rows)


def test_create_exam_endpoint(client):
    response = client.post(
        "/exams",
        json={"name": "Simulado 2", "applied_on": "2026-05-01", "sequence": 2},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Simulado 2"


def test_student_subject_performance(client):
    _ingest(client)
    students = {s["name"]: s["id"] for s in client.get("/students").json()}
    subjects = {s["name"]: s["id"] for s in client.get("/subjects").json()}

    # Giovanna in Matemática: q1 correct, q3 unmarked -> 1/2 = 50%
    response = client.get(
        "/performance/student-subject",
        params={
            "student_id": students["Giovanna"],
            "subject_id": subjects["Matemática"],
        },
    )
    body = response.json()
    assert body["total"] == 2
    assert body["acertos"] == 1
    assert body["taxa_acerto"] == 50.0


def test_student_exam_performance(client):
    _ingest(client)
    students = {s["name"]: s["id"] for s in client.get("/students").json()}
    exams = client.get("/exams").json()

    # Giovanna: q1 correct, q2 correct, q3 unmarked -> 2/3
    response = client.get(
        "/performance/student-exam",
        params={"student_id": students["Giovanna"], "exam_id": exams[0]["id"]},
    )
    body = response.json()
    assert body["total"] == 3
    assert body["acertos"] == 2
    assert body["em_branco"] == 1


def test_class_exam_performance(client):
    _ingest(client)
    classes = {c["name"]: c["id"] for c in client.get("/classes").json()}
    exams = client.get("/exams").json()

    # Class 3A, exam 1: 6 answers total, 3 acertos (Giovanna q1,q2 + Pedro q3)
    response = client.get(
        "/performance/class-exam",
        params={"class_id": classes["3A"], "exam_id": exams[0]["id"]},
    )
    body = response.json()
    assert body["total"] == 6
    assert body["acertos"] == 3
    assert body["taxa_acerto"] == 50.0


def test_class_trend_over_two_exams(client):
    _ingest(client, exam_name="Simulado 1", applied_on="2026-03-01", sequence=1)
    _ingest(client, exam_name="Simulado 2", applied_on="2026-05-01", sequence=2)

    classes = {c["name"]: c["id"] for c in client.get("/classes").json()}
    trend = client.get(f"/trends/class/{classes['3A']}").json()

    assert trend["class_id"] == classes["3A"]
    assert len(trend["points"]) == 2
    # Ordered by sequence
    assert [p["exam_name"] for p in trend["points"]] == ["Simulado 1", "Simulado 2"]
    # Per-subject breakdown present
    assert "Matemática" in trend["points"][0]["by_subject"]
    assert trend["points"][0]["overall"]["total"] == 6


def _grade(client, question_count, key_csv="Questão,Gabarito\nq1,A\nq2,B\n"):
    return client.post(
        "/gradings",
        data={"exam_name": "Simulado 1", "question_count": str(question_count)},
        files=[
            ("images", ("aluno.png", io.BytesIO(b"not an image"), "image/png")),
            ("answer_key", ("gabarito.csv", io.BytesIO(key_csv.encode()), "text/csv")),
        ],
    )


def test_grading_rejects_unknown_question_count(client):
    response = _grade(client, 85)
    assert response.status_code == 422
    assert "72, 80, 90" in response.json()["detail"]


def test_grading_rejects_answer_key_outside_the_sheet(client):
    response = _grade(client, 80, key_csv="Questão,Gabarito\nq1,A\nq85,B\n")
    assert response.status_code == 422
    assert "q85" in response.json()["detail"]
    assert client.get("/exams").json() == []


def test_grading_files_are_served_per_exam(client):
    from grading import artifacts

    assert client.get("/exams/1/results-by-question.csv").status_code == 404
    assert client.get("/exams/1/marked-sheets").json() == []

    artifacts.save(1, "question,a.png\nq1,correct-A\n", {"a.png": b"\x89PNG fake"})

    response = client.get("/exams/1/results-by-question.csv")
    assert response.status_code == 200
    assert "correct-A" in response.text

    assert client.get("/exams/1/marked-sheets").json() == ["a.png"]
    assert client.get("/exams/1/marked-sheets/a.png").content == b"\x89PNG fake"
    # Only listed files are served - no walking out of the exam's folder
    assert client.get("/exams/1/marked-sheets/..%2FResultsByQuestion.csv").status_code == 404
    assert client.get("/exams/2/marked-sheets/a.png").status_code == 404


def test_image_grading_stores_its_files(client):
    import json as _json

    from grading.sheets import template_and_config_paths
    from grading.tests.test_sheets import OPTIONS, _draw_sheet

    template = _json.loads(template_and_config_paths(80)[0].read_text(encoding="utf-8"))
    labels = [f"q{number}" for number in range(1, 81)]
    key = {label: OPTIONS[index % 5] for index, label in enumerate(labels)}
    key_csv = "Questão,Gabarito\n" + "\n".join(f"{q},{a}" for q, a in key.items())

    response = client.post(
        "/gradings",
        data={"exam_name": "Simulado 1", "question_count": "80"},
        files=[
            ("images", ("aluna.png", io.BytesIO(_draw_sheet(template, key)), "image/png")),
            ("answer_key", ("gabarito.csv", io.BytesIO(key_csv.encode()), "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    exam_id = response.json()["exam_id"]

    assert client.get(f"/exams/{exam_id}/marked-sheets").json() == ["aluna.png"]
    assert client.get(f"/exams/{exam_id}/marked-sheets/aluna.png").content[:4] == b"\x89PNG"
    assert "aluna.png" in client.get(f"/exams/{exam_id}/results-by-question.csv").text


def test_answer_key_endpoint(client):
    exam_id = _ingest(client).json()["exam_id"]

    response = client.get(f"/exams/{exam_id}/answer-key")
    assert response.status_code == 200
    assert response.json() == [
        {"number": 1, "correct_answer": "E", "area": "Matemática", "subarea": "Álgebra"},
        {"number": 2, "correct_answer": "B", "area": "Linguagem e Códigos", "subarea": "Português"},
        {"number": 3, "correct_answer": "A", "area": "Matemática", "subarea": "Geometria"},
    ]

    assert client.get("/exams/9999/answer-key").status_code == 404


def test_changing_the_answer_key_regrades_the_exam(client):
    exam_id = _ingest(client).json()["exam_id"]

    # q1: Giovanna marked E (was right), Pedro marked C (was wrong)
    response = client.put(
        f"/exams/{exam_id}/answer-key",
        json=[{"number": 1, "correct_answer": "C"}, {"number": 2, "correct_answer": "B"}],
    )
    assert response.status_code == 200
    assert response.json() == {
        "questions_changed": 1,
        "answers_regraded": 2,
        "sheets_rescored": 2,
    }

    key = client.get(f"/exams/{exam_id}/answer-key").json()
    assert [item["correct_answer"] for item in key] == ["C", "B", "A"]

    rows = client.get("/results", params={"exam_id": exam_id}).json()["rows"]
    q1 = {
        row["Nome do Aluno"]: row["Resultado"]
        for row in rows
        if row["Número da questão"] == 1
    }
    assert q1 == {"Giovanna": "Erro", "Pedro": "Acerto"}
    # Blank answers stay blank whatever the key says
    q2 = {
        row["Nome do Aluno"]: row["Resultado"]
        for row in rows
        if row["Número da questão"] == 2
    }
    assert q2["Pedro"] == "Não Respondeu"


def test_changing_the_answer_key_moves_the_scores(client):
    from db.models import Sheet

    exam_id = _ingest(client).json()["exam_id"]
    client.put(
        f"/exams/{exam_id}/answer-key", json=[{"number": 1, "correct_answer": "C"}]
    )

    with client.session_factory() as session:
        scores = sorted(sheet.score for sheet in session.query(Sheet).all())
    # Giovanna 2.0 -> 1.0, Pedro 1.0 -> 2.0
    assert scores == [1.0, 2.0]


def test_answer_key_change_is_rejected_whole(client):
    exam_id = _ingest(client).json()["exam_id"]

    for changes in (
        [{"number": 1, "correct_answer": "C"}, {"number": 99, "correct_answer": "A"}],
        [{"number": 1, "correct_answer": "C"}, {"number": 2, "correct_answer": " "}],
        [{"number": 1, "correct_answer": "['A', 'B']"}],
    ):
        response = client.put(f"/exams/{exam_id}/answer-key", json=changes)
        assert response.status_code == 422

    key = client.get(f"/exams/{exam_id}/answer-key").json()
    assert [item["correct_answer"] for item in key] == ["E", "B", "A"]
    assert (
        client.put("/exams/9999/answer-key", json=[]).status_code == 404
    )


def test_blank_sheet_is_saved_with_a_warning(client):
    csv_text = (
        "question,Gabarito,lida.png,nao_lida.png\n"
        "score,,1.0,0.0\n"
        "q1,E,correct-E,unmarked\n"
        "q2,B,incorrect-A,unmarked\n"
    )
    response = client.post(
        "/gradings/results-csv",
        data={"exam_name": "Simulado 1"},
        files={"results_csv": ("r.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sheets_ingested"] == 2
    assert len(body["warnings"]) == 1
    assert body["warnings"][0].startswith("nao_lida.png")

    assert _ingest(client, exam_name="Simulado 2").json()["warnings"] == []


def test_delete_exam_endpoint(client):
    from grading import artifacts

    exam_id = _ingest(client).json()["exam_id"]
    artifacts.save(exam_id, RESULTS_CSV, {"a.png": b"\x89PNG fake"})

    assert client.delete(f"/exams/{exam_id}").status_code == 204

    assert client.get("/exams").json() == []
    assert client.get(f"/exams/{exam_id}/answer-key").status_code == 404
    assert client.get(f"/exams/{exam_id}/marked-sheets").json() == []
    assert client.get(f"/exams/{exam_id}/results-by-question.csv").status_code == 404
    assert client.get("/results").json()["rows"] == []
    # The students are the school's, not the exam's
    assert len(client.get("/students").json()) == 2
    assert client.delete(f"/exams/{exam_id}").status_code == 404


def test_answer_key_change_reaches_the_stored_csv(client):
    from grading import artifacts

    exam_id = _ingest(client).json()["exam_id"]
    stored = (
        '"question","Área","Subárea","Gabarito","giovanna.png","pedro.png"\n'
        '"score","","","",2.0,1.0\n'
        '"q1","Matemática","Álgebra","E","correct-E","incorrect-C"\n'
        '"q2","Linguagem e Códigos","Português","B","correct-B","unmarked"\n'
        '"q3","Matemática","Geometria","A","","correct-A"\n'
    )
    artifacts.save(exam_id, stored, {})

    client.put(
        f"/exams/{exam_id}/answer-key",
        json=[{"number": 1, "correct_answer": "C"}, {"number": 3, "correct_answer": "D"}],
    )

    text = client.get(f"/exams/{exam_id}/results-by-question.csv").text
    assert text == (
        '"question","Área","Subárea","Gabarito","giovanna.png","pedro.png"\n'
        '"score","","","",1.0,1.0\n'
        '"q1","Matemática","Álgebra","C","incorrect-E","correct-C"\n'
        '"q2","Linguagem e Códigos","Português","B","correct-B","unmarked"\n'
        '"q3","Matemática","Geometria","D","","incorrect-A"\n'
    )
