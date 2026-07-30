"""Extract the reporting-instruction corpus from the FIS-DDS config PDF.

Chapters 1 and 2 of ``info/LLM_config_file_V1 ProtectedA Copy.pdf`` are the
machine-readable reporting instructions Huda asked for:

  * Chapter 1 — general instructions (analyst guidance, abbreviations, the
    households / non-financial-business focus, the data-error heuristic). Short
    enough to also embed verbatim in the agent's system prompt.
  * Chapter 2 — the Z4 line-item instructions (Section I Assets A1…A6, Section II
    Liabilities L1…L8, memo items). These are chunked and indexed in Vector
    Search so the agent can cite the actual reporting rule for a balance-sheet
    line (e.g. what A1(a) "Cash and Cash Equivalents" includes / excludes).

Chapter 3 (the validation equations) is handled separately by
``parse_config_pdf.py``. This module runs ``pdftotext`` in reading order and
slices the text on the chapter markers, then chunks Chapter 2 with a heading
heuristic so each chunk carries a balance-sheet line reference where possible.

Run standalone to (re)generate the checked-in artifacts:

    python ingestion/lib/extract_instructions.py \
        --pdf "info/LLM_config_file_V1 ProtectedA Copy.pdf" \
        --out ingestion/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

_CH1_START = "Beginning of Chapter 1"
_CH1_END = "End of Chapter 1"
_CH2_START = "Beginning of Chapter 2"
_CH2_END = "End of Chapter 2"
_NOISE = re.compile(r"Category/Catégorie:\s*Non-Sensitive/Non-Délicat")
# Balance-sheet line heading, e.g. "A 1 Cash…", "A2 Securities", "L 6 Other…".
_HEADING = re.compile(r"^\s*([AL])\s?(\d+)\b(.*)")


def _pdftext(pdf_path: str) -> str:
    return subprocess.run(
        ["pdftotext", pdf_path, "-"], capture_output=True, text=True, check=True
    ).stdout


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end, i + 1)
    if i == -1 or j == -1:
        return ""
    return text[i + len(start): j]


def _clean(text: str) -> str:
    text = _NOISE.sub(" ", text)
    return re.sub(r"[ \t]+\n", "\n", text)


def chapter1(text: str) -> str:
    """The general-instructions block, cleaned — small enough for the prompt."""
    return re.sub(r"\n{3,}", "\n\n", _clean(_between(text, _CH1_START, _CH1_END))).strip()


def _chunk_words(paragraph: str, size: int = 900, overlap: int = 150) -> list[str]:
    out, start = [], 0
    while start < len(paragraph):
        out.append(paragraph[start: start + size])
        start += size - overlap
    return out


def chapter2_chunks(text: str) -> list[dict]:
    """Chunk the Z4 line-item instructions, tagging each chunk with the nearest
    balance-sheet line heading it falls under."""
    body = _clean(_between(text, _CH2_START, _CH2_END))
    lines = body.split("\n")
    chunks: list[dict] = []
    current_line = ""
    current_title = "Z4 general instructions"
    buf: list[str] = []

    def flush() -> None:
        para = re.sub(r"\s+", " ", " ".join(buf)).strip()
        buf.clear()
        if len(para) < 60:
            return
        for i, piece in enumerate(_chunk_words(para)):
            cid = hashlib.md5(f"Z4-{current_line}-{len(chunks)}-{i}".encode()).hexdigest()
            chunks.append(
                {
                    "chunk_id": cid,
                    "return_code": "Z4",
                    "bs_line": current_line,
                    "section_title": current_title,
                    "chunk_text": piece,
                }
            )

    for ln in lines:
        m = _HEADING.match(ln)
        if m:
            flush()
            current_line = f"{m.group(1)}{m.group(2)}"
            current_title = f"{m.group(1)}{m.group(2)} {m.group(3).strip()}".strip()
        buf.append(ln)
    flush()
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    text = _pdftext(args.pdf)
    ch1 = chapter1(text)
    ch2 = chapter2_chunks(text)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chapter1_general_instructions.txt").write_text(ch1)
    (out / "instruction_chunks.json").write_text(json.dumps(ch2, indent=2))

    print(f"Chapter 1 general instructions: {len(ch1)} chars")
    print(f"Chapter 2 instruction chunks: {len(ch2)}")
    print(f"  wrote {out}/chapter1_general_instructions.txt")
    print(f"  wrote {out}/instruction_chunks.json")


if __name__ == "__main__":
    main()
