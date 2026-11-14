"""Repository layer: persistence and reads for the CPE OMR data.

Split by what the code does, and re-exported here so callers keep writing
`from db import repositories as repo` / `from db.repositories import ...`:

- writes.py:  get-or-create helpers, persist_graded_sheet, update_answer_key,
              delete_exam
- queries.py: the long-format rows the dashboard consumes, list/get lookups
- stats.py:   performance summaries and the class trend over time

Every function accepts a Session, so callers control the transaction.
"""
from db.repositories.queries import (
    ACERTO,
    ERRO,
    LONG_FORMAT_COLUMNS,
    NAO_RESPONDEU,
    NOT_INFORMED,
    VERDICT_TO_RESULTADO,
    get_exam,
    get_student,
    list_classes,
    list_exams,
    list_questions,
    list_students,
    list_subjects,
    long_format_dataframe,
    long_format_rows,
)
from db.repositories.stats import (
    PerformanceSummary,
    TrendPoint,
    class_improvement_over_time,
    class_performance_in_exam,
    student_performance_in_exam,
    student_performance_in_subject,
)
from db.repositories.writes import (
    AnswerInput,
    AnswerKeyError,
    AnswerKeyUpdate,
    SheetInput,
    delete_exam,
    get_or_create_class,
    get_or_create_exam,
    get_or_create_question,
    get_or_create_student,
    get_or_create_subject,
    get_or_create_subtopic,
    persist_graded_sheet,
    update_answer_key,
)

__all__ = [
    "ACERTO",
    "ERRO",
    "LONG_FORMAT_COLUMNS",
    "NAO_RESPONDEU",
    "NOT_INFORMED",
    "VERDICT_TO_RESULTADO",
    "get_exam",
    "get_student",
    "list_classes",
    "list_exams",
    "list_questions",
    "list_students",
    "list_subjects",
    "long_format_dataframe",
    "long_format_rows",
    "PerformanceSummary",
    "TrendPoint",
    "class_improvement_over_time",
    "class_performance_in_exam",
    "student_performance_in_exam",
    "student_performance_in_subject",
    "AnswerInput",
    "AnswerKeyError",
    "AnswerKeyUpdate",
    "SheetInput",
    "delete_exam",
    "get_or_create_class",
    "get_or_create_exam",
    "get_or_create_question",
    "get_or_create_student",
    "get_or_create_subject",
    "get_or_create_subtopic",
    "persist_graded_sheet",
    "update_answer_key",
]
