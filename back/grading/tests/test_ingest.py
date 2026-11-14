"""Ingest tests: feed a ResultsByQuestion sheet + metadata, assert DB rows.

The sheet mirrors what the OMR pipeline writes: a `question` column, a leading
`score` row, answer-key meta columns (Área, Subárea, Gabarito) carried over, and
one column per graded sheet holding verdicts like 'correct-E' / 'incorrect-C' /
'unmarked'.
"""
import io
from datetime import date

import pandas as pd

from db.models import (
    Answer,
    Class,
    Exam,
    Question,
    Sheet,
    Student,
    Subject,
    Subtopic,
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_UNMARKED,
)
from db.repositories import long_format_dataframe
from grading.ingest import SheetMetadata, ingest_results_by_question, ingest_results_csv

RESULTS_CSV = """question,Área,Subárea,Gabarito,giovanna_santos.png,pedro_alves.png
score,,,,2.0,1.0
q1,Matemática,Álgebra,E,correct-E,incorrect-C
q2,Linguagem e Códigos,Português,B,correct-B,unmarked
q3,Ciências da Natureza,Química,A,unmarked,correct-A
"""


def _metadata():
    return SheetMetadata(
        exam_name="Simulado 1",
        exam_applied_on=date(2026, 3, 1),
        exam_sequence=1,
        student_names={
            "giovanna_santos.png": "Giovanna Santos",
            "pedro_alves.png": "Pedro Alves",
        },
        student_classes={
            "giovanna_santos.png": "3º Ano A",
            "pedro_alves.png": "3º Ano A",
        },
        class_turnos={"3º Ano A": "vespertino"},
    )


def _results_frame():
    from grading.results import load_results_by_question

    return load_results_by_question(io.StringIO(RESULTS_CSV))


def test_ingest_creates_students_sheets_answers(session):
    ingest_results_by_question(session, _results_frame(), _metadata())
    session.commit()

    assert session.query(Student).count() == 2
    assert session.query(Sheet).count() == 2
    # 3 questions x 2 students
    assert session.query(Answer).count() == 6
    # One exam, one class
    assert session.query(Exam).count() == 1
    assert session.query(Class).count() == 1
    # 3 subjects, 3 subtopics, 3 questions (shared across students)
    assert session.query(Subject).count() == 3
    assert session.query(Subtopic).count() == 3
    assert session.query(Question).count() == 3


def test_verdicts_map_to_canonical_states(session):
    ingest_results_by_question(session, _results_frame(), _metadata())
    session.commit()

    giovanna = session.query(Student).filter_by(name="Giovanna Santos").one()
    sheet = session.query(Sheet).filter_by(student_id=giovanna.id).one()
    by_number = {a.question.number: a for a in sheet.answers}

    assert by_number[1].verdict == VERDICT_CORRECT
    assert by_number[1].marked_answer == "E"
    assert by_number[2].verdict == VERDICT_CORRECT
    assert by_number[3].verdict == VERDICT_UNMARKED

    pedro = session.query(Student).filter_by(name="Pedro Alves").one()
    pedro_sheet = session.query(Sheet).filter_by(student_id=pedro.id).one()
    pedro_by_number = {a.question.number: a for a in pedro_sheet.answers}
    assert pedro_by_number[1].verdict == VERDICT_INCORRECT
    assert pedro_by_number[1].marked_answer == "C"
    assert pedro_by_number[3].verdict == VERDICT_CORRECT


def test_answer_key_and_categorisation_stored_on_questions(session):
    ingest_results_by_question(session, _results_frame(), _metadata())
    session.commit()

    q1 = session.query(Question).filter_by(number=1).one()
    assert q1.correct_answer == "E"
    assert q1.subject.name == "Matemática"
    assert q1.subtopic.name == "Álgebra"

    q3 = session.query(Question).filter_by(number=3).one()
    assert q3.correct_answer == "A"
    assert q3.subject.name == "Ciências da Natureza"


def test_scores_land_on_sheets(session):
    ingest_results_by_question(session, _results_frame(), _metadata())
    session.commit()

    giovanna = session.query(Student).filter_by(name="Giovanna Santos").one()
    sheet = session.query(Sheet).filter_by(student_id=giovanna.id).one()
    assert sheet.score == 2.0


def test_ingested_data_reads_back_as_long_format(session):
    ingest_results_by_question(session, _results_frame(), _metadata())
    session.commit()

    frame = long_format_dataframe(session)
    assert len(frame) == 6
    giovanna = frame[frame["Nome do Aluno"] == "Giovanna Santos"].sort_values(
        "Número da questão"
    )
    assert list(giovanna["Resultado"]) == ["Acerto", "Acerto", "Não Respondeu"]
    assert list(giovanna["Área"]) == [
        "Matemática",
        "Linguagem e Códigos",
        "Ciências da Natureza",
    ]
    assert list(giovanna["Turma"]) == ["3º Ano A"] * 3


def test_ingest_from_csv_buffer(session):
    ingest_results_csv(session, io.StringIO(RESULTS_CSV), _metadata())
    session.commit()
    assert session.query(Answer).count() == 6


def test_names_derived_from_filename_when_missing(session):
    metadata = SheetMetadata(exam_name="Simulado 1")
    ingest_results_by_question(session, _results_frame(), metadata)
    session.commit()
    names = {s.name for s in session.query(Student).all()}
    # 'giovanna_santos.png' -> 'Giovanna Santos'
    assert "Giovanna Santos" in names
    assert "Pedro Alves" in names


def test_student_name_from_file_formats_full_names():
    from grading.results import student_name_from_file

    # Underscores -> spaces, title-case, Portuguese connectors stay lowercase
    assert (
        student_name_from_file("Ana_Carolina_Matias_de_Melo.jpg")
        == "Ana Carolina Matias de Melo"
    )
    assert student_name_from_file("Joao-Pedro-da-Silva.png") == "Joao Pedro da Silva"
    assert student_name_from_file("MARIA.png") == "Maria"
    # A connector as the first word is still capitalised
    assert student_name_from_file("do_Carmo_Souza.png") == "Do Carmo Souza"


def test_blank_sheets_names_only_the_unread_ones():
    import io

    from grading.results import blank_sheets, load_results_by_question

    frame = load_results_by_question(
        io.StringIO(
            "question,Gabarito,lida.png,vazia.png,nao_lida.png\n"
            "score,,1.0,0.0,0\n"
            "q1,E,correct-E,unmarked,\n"
            "q2,B,unmarked,unmarked,\n"
        )
    )
    assert blank_sheets(frame) == ["vazia.png", "nao_lida.png"]
