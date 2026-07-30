"""Parse the FIS-DDS LLM config PDF into structured, reviewable data artifacts.

The config file (`info/LLM_config_file_V1 ProtectedA Copy.pdf`, ~1090 pp) is the
customer's real source of truth for the Z4 "Balance Sheet by Booking Location"
return. It has three chapters:

  * Chapter 1 — general instructions (abbreviations, analyst guidance).
  * Chapter 2 — Z4 line-item reporting instructions (Section I Assets … IV).
  * Chapter 3 — ALL validation equations for Z4 (a wide table that ordinary text
    extraction mangles into vertical columns).

This module extracts the **validation equations** robustly using word bounding
boxes (`pdftotext -bbox`). Every equation lives in a fixed x-band (the "Formula"
column, xMin ~= 261); we group the word fragments of each rule by vertical
contiguity and reassemble them into complete formulas, then classify:

  * ``simple``  — ``EqualWithinThreshold(<sum>,<sum>,0,10)`` intra-Z4 identities
    (components add to a total). These drive the synthetic data generator and are
    evaluated by the ``validate_return`` UC function.
  * ``complex`` — nested / conditional (``If(ElementExists(...))``) rules, many of
    which reference other returns (GQ, GR, J2). Kept verbatim for completeness and
    audit, but not evaluated (they need out-of-scope returns).

Run standalone to (re)generate the checked-in JSON artifacts under
``ingestion/data/`` so the ingestion notebooks don't need the PDF at runtime:

    python ingestion/lib/parse_config_pdf.py \
        --pdf "info/LLM_config_file_V1 ProtectedA Copy.pdf" \
        --out ingestion/data
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Bounding-box word extraction
# ---------------------------------------------------------------------------

# The Formula column's left edge sits at xMin ~= 260.9 in the source PDF; the
# whole formula + tolerance cells run out to ~506. Description text ends left of
# ~250, so a >=258 cut cleanly isolates the formula column.
FORMULA_BAND_LO = 258.0
FORMULA_BAND_HI = 506.0
# Anchor detection: the first word of each formula cell also starts in a tight
# sub-band; use it to find where rules begin.
ANCHOR_BAND_LO = 258.0
ANCHOR_BAND_HI = 266.5
FUNC_PREFIXES = (
    "EqualWithinThreshold",
    "If(",
    "GreaterThanOrEqual",
    "LessThanOrEqual",
    "GreaterThan",
    "LessThan",
    "Equal(",
)
# The "Description" column sits between the Rule-Type column and the Formula
# column; it carries the human line reference (e.g. "Components add to total
# A1(a)"), which links each rule's total to its balance-sheet line.
DESC_BAND_LO = 178.0
DESC_BAND_HI = 255.0
# A balance-sheet line reference embedded in a description, e.g. A1(a), A3(a)(ii),
# L6(b), Section I memo.
_BS_LINE_RE = re.compile(r"\b([AL]\d+(?:\s*\([a-z0-9]+\))*)")

_WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)


@dataclass
class Word:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def _unescape(s: str) -> str:
    return s.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")


def _extract_words(pdf_path: str) -> list[Word]:
    """Run ``pdftotext -bbox`` and parse every word with its coordinates."""
    html = subprocess.run(
        ["pdftotext", "-bbox", pdf_path, "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    words: list[Word] = []
    page = -1
    for chunk in re.split(r'(<page width="[\d.]+" height="[\d.]+">)', html):
        if chunk.startswith("<page"):
            page += 1
            continue
        for m in _WORD_RE.finditer(chunk):
            x0, y0, x1, y1, w = m.groups()
            words.append(Word(page, float(x0), float(y0), float(x1), float(y1), w))
    return words


def _balanced(s: str) -> bool:
    return s.count("(") > 0 and s.count("(") == s.count(")") and s.endswith(")")


def _description_for(anchor: Word, by_page: dict[int, list[Word]]) -> str:
    """Read the Description-column text aligned with a formula's anchor row."""
    desc = [
        w
        for w in by_page[anchor.page]
        if DESC_BAND_LO <= w.x0 < DESC_BAND_HI and anchor.y0 - 1 <= w.y0 <= anchor.y0 + 90
    ]
    desc.sort(key=lambda w: (round(w.y0 / 6), w.x0))
    return re.sub(r"\s+", " ", " ".join(w.text for w in desc)).strip()


def _reassemble_formulas(words: list[Word]) -> list[tuple[str, str]]:
    """Reassemble every ``(formula, description)`` pair from word fragments.

    Strategy: the leftmost word of each formula row sits in a tight x-band. Group
    those anchor words by vertical contiguity to find each rule's starting row,
    then, for each anchor, read all formula-column words at or below its y on the
    same page (ordered by line then x) and concatenate until the parentheses
    balance — which yields the complete formula even when it wraps many lines. The
    aligned Description-column text is captured alongside.
    """
    # Words in the tight anchor sub-band, grouped by vertical contiguity so each
    # rule's wrapped lines cluster together. The anchor is the FIRST word of a
    # group that begins with a function name — this dedupes the nested
    # ``EqualWithinThreshold`` that appears mid-rule inside conditional rules.
    band = [w for w in words if ANCHOR_BAND_LO <= w.x0 <= ANCHOR_BAND_HI]
    band.sort(key=lambda w: (w.page, w.y0))
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in band:
        if cur and w.page == cur[-1].page and (w.y0 - cur[-1].y0) < 20.0:
            cur.append(w)
        else:
            if cur:
                groups.append(cur)
            cur = [w]
    if cur:
        groups.append(cur)
    anchors = [g[0] for g in groups if g[0].text.startswith(FUNC_PREFIXES)]
    anchors.sort(key=lambda w: (w.page, w.y0))

    by_page: dict[int, list[Word]] = {}
    for w in words:
        by_page.setdefault(w.page, []).append(w)
    for page_words in by_page.values():
        page_words.sort(key=lambda w: (round(w.y0 / 6), w.x0))

    pages = sorted(by_page)
    formulas: list[tuple[str, str]] = []
    for a in anchors:
        s = ""
        # Read from the anchor's row onward; continue onto following pages if the
        # formula's parentheses have not yet balanced (a handful wrap page breaks).
        for pi in [a.page] + [p for p in pages if p > a.page]:
            row = [
                w
                for w in by_page[pi]
                if FORMULA_BAND_LO <= w.x0 <= FORMULA_BAND_HI
                and (pi > a.page or w.y0 >= a.y0 - 1)
            ]
            row.sort(key=lambda w: (round(w.y0 / 6), w.x0))
            done = False
            for w in row:
                s += w.text
                if _balanced(s):
                    done = True
                    break
            if done:
                break
        formulas.append((_unescape(s), _description_for(a, by_page)))
    return formulas


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# A "simple" Z4 identity: EqualWithinThreshold(<lhs sum>, <rhs sum>, tol, threshold)
# where both sides are sums/differences of bare [NNNN] datapoint addresses.
_ADDR = r"\[[0-9]+\]"
_SUM = rf"{_ADDR}(?:\s*[+\-]\s*{_ADDR})*"
_SIMPLE_RE = re.compile(
    rf"^EqualWithinThreshold\(\s*({_SUM})\s*,\s*({_SUM})\s*,\s*(\d+)\s*,\s*(\d+)\)$"
)
_ADDR_RE = re.compile(r"\[([0-9]+)\]")


@dataclass
class SimpleRule:
    rule_index: int
    return_code: str
    description: str             # e.g. "Components add to total A1(a)"
    bs_line: str                 # e.g. "A1(a)" (parsed from description)
    lhs_expression: str          # e.g. "[0100]"
    rhs_expression: str          # e.g. "[0101]+[0102]+[0103]+[0104]"
    lhs_addresses: list[str]     # ["0100"]
    rhs_addresses: list[str]     # ["0101","0102","0103","0104"]
    tolerance: int
    threshold: int
    raw: str


@dataclass
class ComplexRule:
    rule_index: int
    return_code: str
    description: str
    bs_line: str
    raw: str
    references_returns: list[str] = field(default_factory=list)


def _referenced_returns(formula: str) -> list[str]:
    return sorted(set(re.findall(r"@schema=([A-Z0-9]+)", formula)))


def _bs_line(description: str) -> str:
    m = _BS_LINE_RE.search(description)
    return m.group(1) if m else ""


def classify(
    formulas: list[tuple[str, str]], return_code: str = "Z4"
) -> dict:
    simple: list[SimpleRule] = []
    complex_: list[ComplexRule] = []
    unparsed: list[str] = []
    for i, (f, desc) in enumerate(formulas):
        if not _balanced(f):
            unparsed.append(f)
            continue
        bs_line = _bs_line(desc)
        m = _SIMPLE_RE.match(f.replace(" ", ""))
        if m:
            lhs, rhs, tol, thr = m.groups()
            simple.append(
                SimpleRule(
                    rule_index=i,
                    return_code=return_code,
                    description=desc,
                    bs_line=bs_line,
                    lhs_expression=lhs,
                    rhs_expression=rhs,
                    lhs_addresses=_ADDR_RE.findall(lhs),
                    rhs_addresses=_ADDR_RE.findall(rhs),
                    tolerance=int(tol),
                    threshold=int(thr),
                    raw=f,
                )
            )
        else:
            complex_.append(
                ComplexRule(
                    rule_index=i,
                    return_code=return_code,
                    description=desc,
                    bs_line=bs_line,
                    raw=f,
                    references_returns=_referenced_returns(f),
                )
            )
    return {"simple": simple, "complex": complex_, "unparsed": unparsed}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_pdf(pdf_path: str, return_code: str = "Z4") -> dict:
    words = _extract_words(pdf_path)
    formulas = _reassemble_formulas(words)
    return classify(formulas, return_code)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True, help="Path to the LLM config PDF")
    ap.add_argument("--out", required=True, help="Output dir for JSON artifacts")
    ap.add_argument("--return-code", default="Z4")
    args = ap.parse_args()

    res = parse_pdf(args.pdf, args.return_code)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    simple = [asdict(r) for r in res["simple"]]
    complex_ = [asdict(r) for r in res["complex"]]
    (out / "validation_rules_simple.json").write_text(json.dumps(simple, indent=2))
    (out / "validation_rules_complex.json").write_text(json.dumps(complex_, indent=2))

    total = len(simple) + len(complex_) + len(res["unparsed"])
    print(f"parsed {total} formulas from {args.pdf}")
    print(f"  simple (evaluable Z4 identities): {len(simple)}")
    print(f"  complex (nested/conditional/cross-return): {len(complex_)}")
    print(f"  unparsed (cross-page, kept out): {len(res['unparsed'])}")
    print(f"  wrote {out}/validation_rules_simple.json")
    print(f"  wrote {out}/validation_rules_complex.json")


if __name__ == "__main__":
    main()
