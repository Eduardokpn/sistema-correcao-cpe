"""FastAPI service for the CPE OMR system.

Exposes the persisted grading data over HTTP so the Streamlit front-end (and any
other client) can read the long-format results and the teacher-question
aggregations without importing the data package directly.

Import the app from the module directly (`from api.app import app` /
`uvicorn api.app:app`). The package __init__ stays import-free so that running
`python -m api.app` doesn't double-import the module.
"""
