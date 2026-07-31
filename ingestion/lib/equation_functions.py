"""Turn the parsed Z4 equations into a whole schema of governed UC functions.

The FIS team's real catalog has a ``validation_db`` schema (see the data-structure
doc's Catalog Explorer screenshot) that holds the return's validation rules. Here
we materialize each equation as a **callable, documented Unity Catalog function**
in ``{catalog}.validation_db`` — so every rule is discoverable in Catalog Explorer,
runnable from SQL/Genie, lineage-tracked to ``views_db.vz4``, and reusable by any
consumer, not just the app.

For each simple ``EqualWithinThreshold(LHS, RHS, tol, thr)`` identity we emit a
scalar-returning table function::

    {cat}.validation_db.z4_<rule_id>(bank_code STRING, as_of DATE)
      -> (rule_id, description, bs_line, lhs_value, rhs_value, difference,
          threshold, passed)

It sums the LHS and RHS datapoint values for that bank/date from ``views_db.vz4``
and reports pass/fail. A companion ``run_all(bank_code, as_of)`` function and a
``rule_catalog`` view make the schema browsable. Because the SQL only ever
embeds parsed cell codes (``V0100`` …) and integer thresholds — never user input —
these definitions are injection-safe by construction.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"([+\-]?)\[(\d+)\]")


def _sql_sum(expr: str) -> str:
    """Turn '[0101]+[0102]-[0103]' into a SQL sum over filed values:
    sum(CASE WHEN DATA_POINT_ADDRESS='V0101' THEN VALUE ... - ... END-ish).

    We build ``coalesce(max(v_0101),0) + coalesce(max(v_0102),0) - ...`` using a
    filtered aggregate per address so a single scan of the bank/date slice yields
    every operand. Addresses map to ``V<addr>`` in views_db.
    """
    terms = []
    for sign, addr in _TOKEN_RE.findall(expr):
        op = "-" if sign == "-" else "+"
        terms.append(
            f"{op} coalesce(max(CASE WHEN DATA_POINT_ADDRESS = 'V{addr}' THEN VALUE END), 0)"
        )
    body = " ".join(terms).lstrip("+ ").strip()
    return body or "0"


def rule_id(rule: dict) -> str:
    return f"z4_s{rule['rule_index']:04d}"


def function_name(catalog: str, validation_schema: str, rule: dict) -> str:
    return f"{catalog}.{validation_schema}.{rule_id(rule)}"


def _esc(s: str) -> str:
    return str(s).replace("'", "''")


def build_function_ddl(catalog: str, views_schema: str, validation_schema: str,
                       rule: dict) -> str:
    """Return the CREATE FUNCTION DDL for one validation rule."""
    fq = function_name(catalog, validation_schema, rule)
    rid = rule_id(rule)
    vz4 = f"{catalog}.{views_schema}.vz4"
    lhs_sql = _sql_sum(rule["lhs_expression"])
    rhs_sql = _sql_sum(rule["rhs_expression"])
    thr = int(rule["threshold"])
    desc = (rule.get("description") or "").strip() or "Z4 validation identity"
    bs_line = rule.get("bs_line") or ""
    comment = (
        f"Z4 validation rule {rid}: {desc}. Checks {rule['lhs_expression']} = "
        f"{rule['rhs_expression']} within {thr} (thousands CAD) for a bank's filing. "
        f"Returns the computed LHS/RHS, their difference, and pass/fail."
    )
    return f"""
CREATE OR REPLACE FUNCTION {fq}(bank_code STRING, as_of DATE)
RETURNS TABLE (rule_id STRING, description STRING, bs_line STRING,
               lhs_value DOUBLE, rhs_value DOUBLE, difference DOUBLE,
               threshold INT, passed BOOLEAN)
COMMENT '{_esc(comment)}'
RETURN
  WITH agg AS (
    SELECT ({lhs_sql}) AS lhs_value, ({rhs_sql}) AS rhs_value
    FROM {vz4}
    WHERE BANK_CODE = {rid}.bank_code AND DATE = {rid}.as_of
  )
  SELECT '{_esc(rid)}' AS rule_id, '{_esc(desc)}' AS description,
         '{_esc(bs_line)}' AS bs_line,
         lhs_value, rhs_value, (lhs_value - rhs_value) AS difference,
         {thr} AS threshold,
         abs(lhs_value - rhs_value) <= {thr} AS passed
  FROM agg
""".strip()


def build_catalog_view_ddl(catalog: str, validation_schema: str,
                           metadata_schema: str) -> str:
    """A browsable catalog of every generated rule function (name + description),
    joined to the validation_rules metadata so consumers can discover them."""
    fq_view = f"{catalog}.{validation_schema}.rule_catalog"
    rules_tbl = f"{catalog}.{metadata_schema}.validation_rules"
    return f"""
CREATE OR REPLACE VIEW {fq_view} AS
SELECT
  replace(lower(concat('z4_s', lpad(cast(regexp_extract(rule_id, '([0-9]+)$', 1) AS INT), 4, '0'))), ' ', '') AS function_name_hint,
  rule_id, rule_class, bs_line, description, lhs_expression, rhs_expression, threshold
FROM {rules_tbl}
WHERE rule_class = 'simple'
""".strip()
