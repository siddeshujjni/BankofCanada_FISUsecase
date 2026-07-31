"""Z4 balance-sheet concept taxonomy + datapoint dictionary.

This is the *data-organization* backbone of the demo: it turns the cryptic Z4
datapoint addresses (``[1045]`` / ``V1045``) into a hierarchy of named, defined,
linkable **concepts** (Total Assets, Cash & Cash Equivalents, …) drawn from the
real Section I / II line structure in Chapter 2 of the config PDF.

Two products:
  * ``CONCEPTS`` — the balance-sheet line taxonomy (id, section, line code,
    label, parent, definition). One row per concept.
  * ``build_datapoint_dictionary(rules)`` — maps every datapoint address that
    appears in the parsed Z4 equations to a concept, using each rule's parsed
    ``bs_line`` (e.g. ``A1(a)``) plus a set of well-known named cells. Addresses
    with no rule-supplied line fall back to a generic concept for their section.

The named cells below are grounded in the config file (e.g. the doc states
``V1045`` = "Total Assets"; cell ``[1045]`` is the Total-Assets total in the
equations). Keeping this in one place lets the synthetic generator, the UC
comments, and the Genie semantics all agree.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    concept_id: str      # stable slug, e.g. "A1" or "A1_a"
    bs_section: str      # "I - Assets" | "II - Liabilities"
    bs_line: str         # "A1", "A1(a)", "L1", …
    label: str
    parent_id: str       # "" for top-level section totals
    definition: str


# Top-level Z4 balance-sheet lines (Section I Assets, Section II Liabilities),
# from Chapter 2 of the config PDF. Sub-lines like A1(a) are attached to these.
CONCEPTS: list[Concept] = [
    # --- Section I: Assets ---
    Concept("A1", "I - Assets", "A1", "Cash and Cash Equivalents", "TOTAL_ASSETS",
            "Gold, bank notes, deposits with the Bank of Canada, cheques and other "
            "items in transit, and deposits with regulated financial institutions."),
    Concept("A1_a", "I - Assets", "A1(a)", "Gold, bank notes, deposits with Bank of Canada, cheques and items in transit", "A1",
            "Gold and silver, Bank of Canada notes, foreign currency notes, Canadian "
            "coin, and completed deposit transactions with the Bank of Canada."),
    Concept("A1_b", "I - Assets", "A1(b)", "Deposits with Regulated Financial Institutions", "A1",
            "Non-interest and interest-bearing deposit balances, correspondent "
            "relationships, term deposits, and certificates of deposit purchased."),
    Concept("A2", "I - Assets", "A2", "Securities", "TOTAL_ASSETS",
            "Securities issued or guaranteed by Canada / Canadian entities, and other securities."),
    Concept("A2_a", "I - Assets", "A2(a)", "Securities Issued or Guaranteed by Canada/Canadian", "A2",
            "Government of Canada and Canadian-guaranteed securities holdings."),
    Concept("A2_b", "I - Assets", "A2(b)", "Other Securities", "A2",
            "Corporate and other securities not issued or guaranteed by Canada."),
    Concept("A3", "I - Assets", "A3", "Loans", "TOTAL_ASSETS",
            "Non-mortgage loans (including to households and non-financial businesses) and mortgages."),
    Concept("A3_a", "I - Assets", "A3(a)", "Non-Mortgage Loans", "A3",
            "Loans other than mortgages, including auto loans, HELOCs, and loans to "
            "individuals and others for business purposes."),
    Concept("A3_b", "I - Assets", "A3(b)", "Mortgages", "A3",
            "Residential and non-residential mortgage loans."),
    Concept("A4", "I - Assets", "A4", "Customers' Liability Under Acceptances", "TOTAL_ASSETS",
            "Customers' liability under acceptances (acceptances outstanding)."),
    Concept("A5", "I - Assets", "A5", "Land, Buildings and Equipment", "TOTAL_ASSETS",
            "Land, buildings and equipment less accumulated depreciation."),
    Concept("A6", "I - Assets", "A6", "Other Assets", "TOTAL_ASSETS",
            "Insurance-related assets, accrued interest, prepaid/deferred charges, "
            "goodwill, intangibles, deferred tax, derivative-related amounts, and other."),
    # --- Section II: Liabilities & Equity ---
    Concept("L1", "II - Liabilities", "L1", "Demand and Notice Deposits", "TOTAL_LIABILITIES",
            "Federal, provincial, and other demand and notice deposits."),
    Concept("L2", "II - Liabilities", "L2", "Fixed-Term Deposits", "TOTAL_LIABILITIES",
            "Fixed-term deposits by counterparty and term."),
    Concept("L3", "II - Liabilities", "L3", "Cheques and Other Items in Transit", "TOTAL_LIABILITIES",
            "Cheques and other items in transit (credit balances)."),
    Concept("L4", "II - Liabilities", "L4", "Advances from the Bank of Canada", "TOTAL_LIABILITIES",
            "Advances from the Bank of Canada."),
    Concept("L5", "II - Liabilities", "L5", "Acceptances", "TOTAL_LIABILITIES",
            "Bank's own acceptances outstanding."),
    Concept("L6", "II - Liabilities", "L6", "Other Liabilities", "TOTAL_LIABILITIES",
            "Insurance-related liabilities, mortgages/loans payable, derivative amounts, and other."),
    Concept("L7", "II - Liabilities", "L7", "Subordinated Debt", "TOTAL_LIABILITIES",
            "Subordinated debentures and notes."),
    Concept("L8", "II - Liabilities", "L8", "Shareholders' Equity", "TOTAL_EQUITY",
            "Share capital, retained earnings, and accumulated other comprehensive income."),
    # --- Roll-up totals (the balance-sheet identity) ---
    Concept("TOTAL_ASSETS", "I - Assets", "Total Assets", "Total Assets", "",
            "Total worldwide assets (A1 through A6). Datapoint V1045."),
    Concept("TOTAL_LIABILITIES", "II - Liabilities", "Total Liabilities", "Total Liabilities", "",
            "Total liabilities (L1 through L7)."),
    Concept("TOTAL_EQUITY", "II - Liabilities", "Total Equity", "Total Shareholders' Equity", "",
            "Total shareholders' equity (L8)."),
]

CONCEPT_BY_LINE = {c.bs_line: c for c in CONCEPTS}
CONCEPT_BY_ID = {c.concept_id: c for c in CONCEPTS}

# Headline "booked-in-Canada" total cells, from the Section III reconciliation in
# Chapter 2 of the config PDF (the -400x series). These are the clean, business
# meaningful measures that drive the metric view and the liquidity narrative —
# far more useful than the thousands of cryptic component cells.
#   address -> (label, concept_id, metric_key)
HEADLINE_CELLS: dict[str, tuple[str, str, str]] = {
    "4000": ("Cash and Cash Equivalents (booked in Canada)", "A1", "cash"),
    "4001": ("Securities (booked in Canada)", "A2", "securities"),
    "4002": ("Loans (booked in Canada)", "A3", "loans"),
    "4005": ("Customers' Liability Under Acceptances (booked in Canada)", "A4", "acceptances_asset"),
    "4006": ("Land, Buildings and Equipment (booked in Canada)", "A5", "premises"),
    "4007": ("Other Assets (booked in Canada)", "A6", "other_assets"),
    "4009": ("Total Assets (booked in Canada)", "TOTAL_ASSETS", "total_assets"),
    "4010": ("Demand and Notice Deposits (booked in Canada)", "L1", "demand_deposits"),
    "4011": ("Fixed-Term Deposits (booked in Canada)", "L2", "term_deposits"),
    "4012": ("Cheques and Other Items in Transit (booked in Canada)", "L3", "transit"),
    "4013": ("Acceptances (booked in Canada)", "L5", "acceptances_liab"),
    "4014": ("Other Liabilities (booked in Canada)", "L6", "other_liabilities"),
    "4017": ("Subordinated Debt (booked in Canada)", "L7", "subordinated_debt"),
    "4018": ("Shareholders' Equity (booked in Canada)", "L8", "equity"),
    "4019": ("Total Liabilities and Shareholders' Equity (booked in Canada)", "TOTAL_LIABILITIES", "total_liab_equity"),
}

# Well-known individual datapoint addresses grounded in the config file.
NAMED_CELLS: dict[str, tuple[str, str]] = {
    # address -> (label, concept_id)
    "1045": ("Total Assets (worldwide)", "TOTAL_ASSETS"),
    **{addr: (label, cid) for addr, (label, cid, _m) in HEADLINE_CELLS.items()},
}



# --- Canonical metric spine ----------------------------------------------------
# A curated set of clean, non-overlapping datapoint cells used as the headline
# measures in the metric view and the app narrative. Total Assets (V1045) is the
# exact worldwide total; the others are canonical line cells drawn from V1045's
# primary decomposition (real Z4 lines, e.g. A3(a) Non-Mortgage Loans), so the
# numbers are interpretable and a BoC SME trusts them. The thousands of cryptic
# component cells remain in the fact table for the decoding / validation story.
#   metric_key -> (cell_code, label, higher_is_more_of)
CANONICAL_METRICS: dict[str, tuple[str, str]] = {
    "total_assets": ("1045", "Total Assets (worldwide)"),
    "non_mortgage_loans": ("0468", "Non-Mortgage Loans (A3(a))"),
    "cash_and_equivalents": ("0863", "Cash & Cash Equivalents (A1(a))"),
    "deposits_with_fis": ("0488", "Deposits with Regulated Financial Institutions (A1(b))"),
    # Largest L1 / L2 total cells, chosen so deposit magnitudes (and the resulting
    # loan-to-deposit ratio) are realistic for the demo.
    "demand_deposits": ("0873", "Demand & Notice Deposits (L1(a))"),
    "term_deposits": ("2339", "Fixed-Term Deposits (L2(e))"),
}


def _line_to_concept_id(bs_line: str) -> str:
    """Map a parsed bs_line (A1(a), A3(a)(ii), …) to the nearest known concept."""
    if not bs_line:
        return ""
    # Exact match first (A1(a)), then the top line (A1), then section fallback.
    if bs_line in CONCEPT_BY_LINE:
        return CONCEPT_BY_LINE[bs_line].concept_id
    top = bs_line.split("(")[0]  # "A3(a)(ii)" -> "A3"
    if top in CONCEPT_BY_LINE:
        return CONCEPT_BY_LINE[top].concept_id
    return ""


def time_series_name(return_code: str, bank_code: str, data_point_address: str) -> str:
    """Build the RRS time-series name, e.g. ('Z4','OAB','V1045') -> 'RZ4.OAB.V1045'."""
    return f"R{return_code}.{bank_code}.{data_point_address}"


def time_series_key(return_code: str, bank_code: str, data_point_address: str) -> str:
    """Build the lowercase metadata key with the #rrs suffix, e.g. 'rz4.oab.v1045#rrs'."""
    return f"{time_series_name(return_code, bank_code, data_point_address).lower()}#rrs"


def build_time_series_rows(
    dictionary: list[dict], banks: list, returns_of: dict[str, str],
) -> list[dict]:
    """One decoder row per (bank, datapoint): the cryptic name + its plain-English
    meaning, assembled from the FI, the return title, and the datapoint's concept.

    ``banks`` is a list of objects with ``bank_code`` / ``legal_name`` / ``short_name``;
    ``returns_of`` maps return_code -> return title.
    """
    rows: list[dict] = []
    for b in banks:
        for d in dictionary:
            rc = d["return_code"]
            addr = d["data_point_address"]
            name = time_series_name(rc, b.bank_code, addr)
            key = time_series_key(rc, b.bank_code, addr)
            ret_title = returns_of.get(rc, rc)
            desc = (
                f"{rc} ({ret_title}) · {b.legal_name} ({b.short_name}) · "
                f"{d['label']}"
                + (f" · line {d['bs_line']}" if d.get("bs_line") else "")
                + f" · datapoint {addr}"
            )
            rows.append(
                {
                    "time_series_key": key,
                    "time_series_name": name,
                    "return_code": rc,
                    "bank_code": b.bank_code,
                    "data_point_address": addr,
                    "cell_code": d["cell_code"],
                    "bs_section": d["bs_section"],
                    "bs_line": d["bs_line"],
                    "concept_id": d["concept_id"],
                    "label": d["label"],
                    "role": d["role"],
                    "unit": "thousands CAD",
                    "description": desc,
                }
            )
    return rows


def build_datapoint_dictionary(simple_rules: list[dict]) -> list[dict]:
    """Return one dict per datapoint address with its concept and role.

    ``role`` is ``total`` if the address is the LHS of any identity, else
    ``component``. ``concept_id`` links to :data:`CONCEPTS`.
    """
    lhs_addresses: set[str] = set()
    line_by_addr: dict[str, str] = {}
    all_addresses: set[str] = set()
    for r in simple_rules:
        for a in r["lhs_addresses"]:
            lhs_addresses.add(a)
            if r.get("bs_line"):
                line_by_addr.setdefault(a, r["bs_line"])
        for a in r["rhs_addresses"]:
            if r.get("bs_line"):
                line_by_addr.setdefault(a, r["bs_line"])
        all_addresses.update(r["lhs_addresses"])
        all_addresses.update(r["rhs_addresses"])

    rows: list[dict] = []
    for addr in sorted(all_addresses, key=lambda a: int(a)):
        bs_line = line_by_addr.get(addr, "")
        if addr in NAMED_CELLS:
            label, concept_id = NAMED_CELLS[addr]
        else:
            concept_id = _line_to_concept_id(bs_line)
            concept = CONCEPT_BY_ID.get(concept_id)
            label = concept.label if concept else "Z4 datapoint"
        concept = CONCEPT_BY_ID.get(concept_id)
        rows.append(
            {
                "data_point_address": f"V{addr}",
                "cell_code": addr,
                "return_code": "Z4",
                "bs_section": concept.bs_section if concept else "",
                "bs_line": bs_line,
                "concept_id": concept_id,
                "label": label,
                "role": "total" if addr in lhs_addresses else "component",
            }
        )
    return rows
