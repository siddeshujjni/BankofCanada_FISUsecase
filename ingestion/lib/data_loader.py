"""Load the checked-in data artifacts produced from the config PDF.

The artifacts under ``ingestion/data/`` are generated once (from the 4.9 MB config
PDF) by ``parse_config_pdf.py`` and ``extract_instructions.py`` and committed to
the repo, so the ingestion notebooks reproduce the exact same tables without
needing the PDF or ``pdftotext`` at runtime. Paths are resolved relative to this
module's location, which works both locally and when the ``ingestion`` folder is
synced into a Databricks workspace.
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_json(name: str) -> list[dict]:
    return json.loads((_DATA_DIR / name).read_text())


def load_validation_rules_simple() -> list[dict]:
    """The 330 intra-Z4 ``EqualWithinThreshold`` identities."""
    return _load_json("validation_rules_simple.json")


def load_validation_rules_complex() -> list[dict]:
    """The conditional / cross-return validation rules (kept for completeness)."""
    return _load_json("validation_rules_complex.json")


def load_instruction_chunks() -> list[dict]:
    """Chunked Z4 line-item reporting instructions (Chapter 2)."""
    return _load_json("instruction_chunks.json")


def load_chapter1_instructions() -> str:
    """The general-instructions block (Chapter 1), for the agent system prompt."""
    return (_DATA_DIR / "chapter1_general_instructions.txt").read_text()
