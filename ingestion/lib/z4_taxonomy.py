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
    # --- Section I memo / selected-information items (Chapter 2, items 1-24) ---
    # These are supplementary breakdowns reported alongside the main A1-A6 lines;
    # in the parsed equations they surface under line codes A7, A13-A24.
    Concept("A7", "I - Assets · Memo", "A7", "Memo: Selected Asset Information",
            "TOTAL_ASSETS",
            "Selected supplementary information on assets (securitized assets, assets "
            "under custody/administration/management, items in transit, defined-benefit "
            "pension assets, and other memo breakdowns reported with Section I)."),
    Concept("A13", "I - Assets · Memo", "A13", "Memo: Residential Mortgages", "A3",
            "Residential mortgages (equals Section I 3(b)(i), CAD only), broken down by "
            "number of units, readvanceable status, and counterparty."),
    Concept("A14", "I - Assets · Memo", "A14", "Memo: Loans to Individuals Secured by Residential Property", "A3",
            "Loans to individuals for non-business purposes secured by residential "
            "property, by readvanceable status."),
    Concept("A15", "I - Assets · Memo", "A15", "Memo: Non-Residential Mortgages", "A3",
            "Non-residential mortgages (equals Section I 3(b)(ii), CAD only), by "
            "counterparty and property type."),
    Concept("A16", "I - Assets · Memo", "A16", "Memo: Non-Mortgage Loan Portfolio", "A3",
            "Selected information on the non-mortgage loan portfolio (including of-which "
            "securities)."),
    Concept("A20", "I - Assets · Memo", "A20", "Memo: Selected Information on Other Assets", "A6",
            "Selected information on Other Assets (accumulated impairments, software, "
            "purchased items, and other)."),
    # --- Section II memo / other liability items ---
    Concept("L6g", "II - Liabilities · Memo", "L6(g)(i)", "Memo: Derivative-Related Amounts (Other Liabilities)", "L6",
            "Selected information on Other Liabilities — derivative-related amounts."),
    Concept("L9", "II - Liabilities · Memo", "L9", "Memo: Selected Liability & Equity Information",
            "TOTAL_LIABILITIES",
            "Selected supplementary information reported with Section II liabilities and "
            "shareholders' equity (allowances, defined-benefit pension obligations, "
            "preferred shares/trust capital, and other memo breakdowns)."),
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


# Datapoint-address numbering blocks in the Z4 return. Cells that the parsed
# equations don't tie to a Section I/II line still have a well-understood role from
# their address range, so we give them a meaningful label instead of "Z4 datapoint".
#   leading digit -> (section label, meaning)
_ADDR_FAMILY: dict[str, tuple[str, str]] = {
    "0": ("I/II - Detail", "Balance-sheet detail component"),
    "1": ("I/II - Detail", "Balance-sheet detail component"),
    "2": ("Memo", "Memo / of-which breakdown"),
    "3": ("Memo", "Memo / of-which breakdown"),
    "4": ("III - Reconciliation", "Booking-location reconciliation total (in/outside Canada, worldwide)"),
    "5": ("III - Currency split", "Total- vs foreign-currency split total"),
    "7": ("Memo", "Selected memo information"),
    "8": ("Memo", "Selected memo information"),
    "9": ("J2 - Monthly reporting", "Monthly reporting of selected J2 cells"),
}


def _fallback_section(addr: str) -> str:
    return _ADDR_FAMILY.get(addr[:1], ("Z4", ""))[0]


def _fallback_label(addr: str, bs_line: str) -> str:
    return _ADDR_FAMILY.get(addr[:1], ("Z4", "Z4 datapoint"))[1]


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
    return_code: str = "Z4",
) -> list[dict]:
    """One decoder row per (bank, datapoint) for a single return: the cryptic name
    + its plain-English meaning, assembled from the FI, the return title, and the
    datapoint's concept.

    ``banks`` is a list of objects with ``bank_code`` / ``legal_name`` / ``short_name``;
    ``returns_of`` maps return_code -> return title; ``return_code`` is the return
    whose ``dictionary`` slice is being decoded (so RM4.*, RA2.*, … decode too).
    """
    ret_title = returns_of.get(return_code, return_code)
    rows: list[dict] = []
    for b in banks:
        for d in dictionary:
            addr = d["data_point_address"]
            name = time_series_name(return_code, b.bank_code, addr)
            key = time_series_key(return_code, b.bank_code, addr)
            # Show the balance-sheet line only when it adds info beyond the label
            # (roll-up totals like V1045 have bs_line == "Total Assets" == label).
            line = d.get("bs_line") or ""
            line_suffix = f" · line {line}" if line and line != d["label"] else ""
            desc = (
                f"{return_code} ({ret_title}) · {b.legal_name} ({b.short_name}) · "
                f"{d['label']}{line_suffix} · datapoint {addr}"
            )
            rows.append(
                {
                    "time_series_key": key,
                    "time_series_name": name,
                    "return_code": return_code,
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
        rule_line = line_by_addr.get(addr, "")
        if addr in NAMED_CELLS:
            # An explicitly-catalogued cell (e.g. V1045 = Total Assets): its concept
            # is authoritative and OVERRIDES the line inferred from equations, so the
            # decoded meaning and bs_line agree with the concept (not, say, "A7").
            label, concept_id = NAMED_CELLS[addr]
            concept = CONCEPT_BY_ID.get(concept_id)
            bs_line = concept.bs_line if concept else rule_line
        else:
            concept_id = _line_to_concept_id(rule_line)
            concept = CONCEPT_BY_ID.get(concept_id)
            bs_line = rule_line
            label = concept.label if concept else _fallback_label(addr, rule_line)
        concept = CONCEPT_BY_ID.get(concept_id)
        rows.append(
            {
                "data_point_address": f"V{addr}",
                "cell_code": addr,
                "return_code": "Z4",
                "bs_section": concept.bs_section if concept else _fallback_section(addr),
                "bs_line": bs_line,
                "concept_id": concept_id,
                "label": label,
                "role": "total" if addr in lhs_addresses else "component",
            }
        )
    return rows
