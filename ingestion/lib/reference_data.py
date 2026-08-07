"""Reference data for the demo: returns and financial institutions.

Return codes/titles are the real OSFI / Bank of Canada deposit-taking returns.
Financial-institution codes follow the RRS ``O<xx>`` convention used in the
config file (RZ4.O**AB**.V1045 → FI "AB"). The Big Six use plausible codes and
their real abbreviations; a handful of smaller / foreign-bank entries make the
"~80 filers" story read true at demo scale. Asset scales are order-of-magnitude
realistic (RBC/TD ≈ $2T; mid-size banks far smaller) so the generated filings
land at believable magnitudes. The mix "emphasis" knobs differentiate each
bank's liquidity / lending / deposit strategy so the flagship comparative
question has genuine signal.
"""
from __future__ import annotations

from .generate_filings import Bank

# --- Regulatory returns (real OSFI / BoC codes) ---------------------------------
RETURNS: list[dict] = [
    {
        "return_code": "Z4",
        "return_title": "Balance Sheet by Booking Location",
        "agency": "Bank of Canada",
        "frequency": "Monthly",
        "statutory_basis": "Sections 628 and 600 of the Bank Act, Section 24 of the Bank of Canada Act, and the Statistics Act",
        "last_updated": "2022-10-01",
        "purpose": "Consolidated balance sheet of the institution as at the last day of each month, separating assets and liabilities into total and foreign currencies, by booking location (in Canada, outside Canada, worldwide).",
    },
    {
        "return_code": "M4",
        "return_title": "Balance Sheet",
        "agency": "OSFI",
        "frequency": "Monthly",
        "statutory_basis": "Section 628 of the Bank Act",
        "last_updated": "2022-10-01",
        "purpose": "Consolidated monthly balance sheet; the Z4 total worldwide amounts reconcile to the M4.",
    },
    {
        "return_code": "A2",
        "return_title": "Non-Mortgage Loans Report",
        "agency": "OSFI",
        "frequency": "Quarterly",
        "statutory_basis": "Section 628 of the Bank Act",
        "last_updated": "2022-10-01",
        "purpose": "Detail of non-mortgage loans by borrower type and purpose.",
    },
    {
        "return_code": "LA",
        "return_title": "Liquidity Coverage Ratio (LCR)",
        "agency": "OSFI",
        "frequency": "Monthly",
        "statutory_basis": "Liquidity Adequacy Requirements (LAR) Guideline",
        "last_updated": "2023-01-01",
        "purpose": "High-quality liquid assets over total net cash outflows over a 30-day stress period.",
    },
]

# --- Financial institutions (RRS FI codes) --------------------------------------
# (bank_code, short_name, legal_name, is_big6, asset_scale $000, cash_e, sec_e, loan_e, dep_e)
_FI_SPECS: list[tuple] = [
    # Big Six — differentiated strategies.
    ("OAB", "RBC", "Royal Bank of Canada", True, 2.10e9, 0.9, 1.2, 1.0, 1.05),
    ("OCB", "TD", "The Toronto-Dominion Bank", True, 1.95e9, 1.3, 0.9, 1.05, 1.30),
    ("ODB", "BNS", "Bank of Nova Scotia", True, 1.40e9, 1.0, 1.1, 1.10, 1.00),
    ("OEB", "BMO", "Bank of Montreal", True, 1.35e9, 0.95, 1.15, 1.05, 1.00),
    ("OFB", "CIBC", "Canadian Imperial Bank of Commerce", True, 1.00e9, 0.9, 1.0, 1.20, 0.95),
    ("OGB", "NBC", "National Bank of Canada", True, 0.45e9, 1.1, 1.05, 0.95, 1.10),
    # Mid-size / other Canadian banks.
    ("OHB", "HSBC-CA", "HSBC Bank Canada", False, 0.12e9, 1.4, 1.2, 0.8, 1.1),
    ("OJB", "LAUR", "Laurentian Bank of Canada", False, 0.05e9, 1.0, 0.9, 1.2, 1.0),
    ("OKB", "CWB", "Canadian Western Bank", False, 0.04e9, 0.8, 0.8, 1.4, 0.9),
    ("OLB", "EQB", "Equitable Bank", False, 0.03e9, 0.7, 0.7, 1.5, 0.85),
    ("OMB", "MANU", "Manulife Bank of Canada", False, 0.028e9, 1.1, 1.0, 1.1, 1.2),
    # Foreign bank branches / subsidiaries.
    ("ONB", "JPM-CA", "J.P. Morgan Bank Canada", False, 0.02e9, 1.6, 1.5, 0.5, 0.8),
    ("OPB", "CITI-CA", "Citibank Canada", False, 0.018e9, 1.5, 1.4, 0.6, 0.85),
    ("OQB", "BofA-CA", "Bank of America Canada", False, 0.015e9, 1.5, 1.4, 0.6, 0.85),
    ("ORB", "BNP-CA", "BNP Paribas (Canada)", False, 0.012e9, 1.4, 1.3, 0.7, 0.9),
]

BANKS: list[Bank] = [
    Bank(code, short, legal, big6, scale, ce, se, le, de)
    for (code, short, legal, big6, scale, ce, se, le, de) in _FI_SPECS
]
BANK_BY_CODE: dict[str, Bank] = {b.bank_code: b for b in BANKS}

# --- Return tables to materialize in views_db --------------------------------
# The FIS team's catalog has one v* table per return (dozens of them). We
# materialize Z4 in full and derive a few related returns from the same filings so
# the "one table per return" reality is visible and the generic tools (decode /
# get_series_values) work across tables. Each derived return projects a slice of
# the Z4 datapoints (per the doc, e.g. M4 worldwide totals reconcile to Z4).
#   table -> {return_code, select: fn(dict_row)->bool, note}
RETURN_TABLES: list[dict] = [
    {
        "table": "vz4", "return_code": "Z4",
        "select": None,  # all Z4 datapoints
        "note": "Full Z4 Balance Sheet by Booking Location (the flagship return).",
    },
    {
        "table": "vm4", "return_code": "M4",
        # M4 consolidated balance sheet reconciles to the Z4 worldwide totals:
        # take the section/total datapoints (totals + the -400x/-40xx reconciliation cells).
        "select": lambda d: d["role"] == "total" or d["cell_code"][:1] == "4",
        "note": "M4 consolidated balance sheet — worldwide totals that reconcile to Z4.",
    },
    {
        "table": "va2", "return_code": "A2",
        # A2 Non-Mortgage Loans: the loan datapoints (A3(a) family).
        "select": lambda d: d["bs_line"].startswith("A3(a)") or d["concept_id"] == "A3_a",
        "note": "A2 Non-Mortgage Loans — the loan-detail datapoints.",
    },
    {
        "table": "vla", "return_code": "LA",
        # LA / LCR: liquid-asset and deposit datapoints feeding the liquidity story.
        "select": lambda d: d["concept_id"] in ("A1", "A1_a", "A1_b", "A2", "L1", "L2")
        or d["bs_line"].startswith(("A1", "A2", "L1", "L2")),
        "note": "LA Liquidity Coverage Ratio — liquid assets and deposit datapoints.",
    },
]


# Common bank-name abbreviations (from Chapter 1 of the config file).
ABBREVIATIONS: dict[str, str] = {
    "RBC": "Royal Bank of Canada",
    "TD": "The Toronto-Dominion Bank",
    "BNS": "Bank of Nova Scotia",
    "BMO": "Bank of Montreal",
    "CIBC": "Canadian Imperial Bank of Commerce",
    "NBC": "National Bank of Canada",
}
