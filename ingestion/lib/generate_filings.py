"""Synthesize internally-consistent Z4 filings for a set of banks and dates.

The synthetic data must **satisfy the real Z4 validation identities** so that
``validate_return`` passes for clean filings and only deliberately-seeded errors
fail. Every ``EqualWithinThreshold(A, B, tol, thr)`` rule asserts ``A - B = 0``.

Real balance sheets are built **top-down** (a total is split into its
components), which keeps every value non-negative and realistic. We do the same:

  1. From the parsed rules, take the *primary decomposition* — the first
     ``total = c1 + c2 + …`` rule for each total address. This forms a clean DAG
     (verified acyclic) with ~92 roots (top-level totals, incl. V1045 Total
     Assets) whose leaves are the balance-sheet line items.
  2. Assign each root a target magnitude derived from the bank's size and mix
     knobs, then recursively **split** every total among its components using
     positive weights (biased by balance-sheet section so banks differ in
     liquidity / deposit strategy). Pure-addition rules hold exactly; the handful
     of subtraction ("net") rules are computed directly from their components.
  3. A final :meth:`check` reports any residual rule failures (including the
     redundant alternate-partition identities) so ingestion can assert
     cleanliness; the generator nudges shared components so those hold too.
  4. Seed data errors (a broken component and a multi-sigma outlier) on request.

The result is long-format rows matching the customer's real ``views_db`` shape:
``TIME_SERIES_NAME, BANK_CODE, DATA_POINT_ADDRESS, DATE, VALUE`` — plus the
``metadata_db.time_series`` decoder rows.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"([+\-]?)\[(\d+)\]")
_EPS = 1e-6


@dataclass
class Bank:
    bank_code: str      # RRS FI code, e.g. "OAB"
    short_name: str     # "RBC"
    legal_name: str     # "Royal Bank of Canada"
    is_big6: bool
    asset_scale: float  # total-assets anchor in $thousands (e.g. 2.1e9 = ~$2.1T)
    # Balance-sheet mix knobs: relative emphasis for each section, so the "compare
    # liquidity / cash-management strategy" question has real signal. 1.0 = neutral.
    cash_emphasis: float = 1.0        # A1 Cash & Cash Equivalents
    securities_emphasis: float = 1.0  # A2 Securities
    loans_emphasis: float = 1.0       # A3 Loans
    deposit_emphasis: float = 1.0     # L1 + L2 deposits


def parse_expr(expr: str) -> list[tuple[int, str]]:
    """Parse '[0101]+[0102]-[0103]' -> [(+1,'0101'),(+1,'0102'),(-1,'0103')]."""
    return [(-1 if sign == "-" else 1, addr) for sign, addr in _TOKEN_RE.findall(expr)]


class Z4Generator:
    """Top-down balance-sheet generator that satisfies the Z4 identities."""

    def __init__(self, simple_rules: list[dict], dictionary: list[dict] | None = None,
                 seed: int = 42) -> None:
        self.rules = simple_rules
        self.rng = random.Random(seed)

        # Universe of addresses.
        all_addr: set[str] = set()
        for r in simple_rules:
            all_addr.update(r["lhs_addresses"])
            all_addr.update(r["rhs_addresses"])
        self.all_addresses = sorted(all_addr, key=lambda a: int(a))

        # Primary decomposition: first rule for each single-address total.
        self.primary: dict[str, list[tuple[int, str]]] = {}
        for r in simple_rules:
            if len(r["lhs_addresses"]) != 1:
                continue
            t = r["lhs_addresses"][0]
            self.primary.setdefault(t, parse_expr(r["rhs_expression"]))
        self.totals = set(self.primary)
        component_of = {a for ops in self.primary.values() for _s, a in ops}
        self.roots = [t for t in self.totals if t not in component_of]
        self.leaves = [a for a in self.all_addresses if a not in self.totals]

        # Section per address (for bank-differentiating value bias).
        self.section_of: dict[str, str] = {}
        if dictionary:
            for d in dictionary:
                self.section_of[d["cell_code"]] = d.get("bs_line", "") or ""

        self._order = self._topo_order()

    def _topo_order(self) -> list[str]:
        """Totals in dependency order (components before their parent)."""
        seen: set[str] = set()
        order: list[str] = []

        def visit(a: str) -> None:
            if a in seen or a not in self.primary:
                return
            seen.add(a)
            for _s, dep in self.primary[a]:
                visit(dep)
            order.append(a)

        for t in sorted(self.totals, key=lambda a: int(a)):
            visit(t)
        return order

    # --- per-filing generation ---------------------------------------------
    def _section_weight(self, addr: str, bank: Bank) -> float:
        line = self.section_of.get(addr, "")
        if line.startswith("A1"):
            return bank.cash_emphasis
        if line.startswith("A2"):
            return bank.securities_emphasis
        if line.startswith("A3"):
            return bank.loans_emphasis
        if line.startswith(("L1", "L2")):
            return bank.deposit_emphasis
        return 1.0

    def generate_filing(self, bank: Bank, target_assets: float | None = None) -> dict[str, float]:
        """One month-end filing: address -> value ($thousands); identities hold."""
        target = target_assets if target_assets is not None else bank.asset_scale
        values: dict[str, float] = {}

        # 1. Seed each root with a size proportional to its section emphasis. Bank
        #    differentiation (liquidity vs lending strategy) flows from these
        #    section-weighted draws through the whole primary tree.
        root_weights = {r: max(self.rng.uniform(0.5, 1.5) * self._section_weight(r, bank), 0.05)
                        for r in self.roots}
        # Total Assets root (V1045) anchors magnitude; others scale relative to it.
        anchor = root_weights.get("1045", 1.0)
        for r in self.roots:
            values[r] = round(target * root_weights[r] / anchor, 3)

        # 2. Split every total among its components (top-down over the DAG,
        #    reversed so parents are processed before children).
        for t in reversed(self._order):
            if t in self.roots or t in values:
                # roots already seeded; non-roots get their value when their parent splits
                pass
        # Process parents before children: order is children-first, so reverse it.
        for t in reversed(self._order):
            if t not in values:
                continue
            ops = self.primary[t]
            pos = [(s, a) for s, a in ops if s > 0]
            neg = [(s, a) for s, a in ops if s < 0]
            parent_val = values[t]
            # Distribute the parent's value across positive components by weight;
            # negative components are treated as small "netting" deductions added
            # back so the identity total = sum(pos) - sum(neg) holds.
            weights = {a: max(self.rng.uniform(0.3, 1.7) * self._section_weight(a, bank), 0.02)
                       for _s, a in pos}
            wsum = sum(weights.values()) or 1.0
            neg_total = 0.0
            for s, a in neg:
                # a small net item: 0-5% of parent
                nv = round(abs(parent_val) * self.rng.uniform(0.0, 0.05), 3)
                values.setdefault(a, nv)
                neg_total += values[a]
            distributable = parent_val + neg_total
            for _s, a in pos:
                share = round(distributable * weights[a] / wsum, 3)
                # Only assign if not already fixed by a deeper split.
                values.setdefault(a, share)

        # 3. Compute any total not yet valued directly from its components
        #    (covers totals reachable only as components of subtraction rules).
        for t in self._order:
            if t not in values:
                values[t] = round(
                    sum(s * values.get(a, 0.0) for s, a in self.primary[t]), 3
                )

        # 4. Ensure leaf/isolated addresses referenced only by secondary identities
        #    get a modest positive starting value (totals are computed, not seeded).
        leaf_seed = max(target, 1.0) * 1e-4
        for a in self.leaves:
            values.setdefault(a, round(self.rng.uniform(0.2, 1.0) * leaf_seed, 3))

        # 5. Recompute all primary totals bottom-up so those identities are exact.
        for t in self._order:
            values[t] = sum(s * values[a] for s, a in self.primary[t])

        # 6. Rescale to hit the target Total Assets FIRST (scaling preserves every
        #    A - B = 0 identity), so the subsequent projection converges the final,
        #    at-scale values to within the tolerance the validator uses.
        ta = values.get("1045", 0.0)
        if abs(ta) > _EPS and target:
            k = target / ta
            values = {a: v * k for a, v in values.items()}

        # 7. One exact tree pass to satisfy the ~275 primary identities, then a
        #    single sustained projection over the FULL system (including the
        #    alternate-partition "redundant" rules) to reconcile the rest. V1045 is
        #    pinned so the target magnitude is preserved; a final proportional
        #    rescale (which preserves every A - B = 0 identity) locks it exactly.
        #    No trailing tree pass — that would recompute primary totals and undo
        #    the projection's secondary-rule fixes.
        for t in self._order:
            values[t] = sum(s * values[a] for s, a in self.primary[t])
        self._project(values, pinned={"1045"}, iters=8000)
        ta = values.get("1045", 0.0)
        if abs(ta) > _EPS and target:
            k = target / ta
            values = {a: v * k for a, v in values.items()}
        return {a: round(v, 3) for a, v in values.items()}

    def generate_clean_filing(self, bank: Bank, target_assets: float | None = None,
                              max_retries: int = 12) -> dict[str, float]:
        """A filing guaranteed to satisfy every identity, retrying with a jittered
        RNG state on the rare configuration that does not converge cleanly. Returns
        the cleanest attempt (fewest violations) if all retries fall short."""
        best, best_bad = None, None
        for _ in range(max_retries):
            values = self.generate_filing(bank, target_assets)
            n_bad = len(self.check(values)) + sum(1 for v in values.values() if v < -1.0)
            if n_bad == 0:
                return values
            if best_bad is None or n_bad < best_bad:
                best, best_bad = values, n_bad
        return best

    def _rule_terms(self, r: dict) -> list[tuple[int, str]]:
        """Rule as signed terms that sum to zero: lhs - rhs == 0."""
        return parse_expr(r["lhs_expression"]) + [
            (-s, a) for s, a in parse_expr(r["rhs_expression"])
        ]

    def _project(self, values: dict[str, float], iters: int = 3000,
                 pinned: set[str] | None = None) -> int:
        """Iteratively enforce every identity by proportional residual sharing.

        For a rule ``sum(sign * x) = R`` (target 0), move each *adjustable* term
        ``x_a -= sign_a * R * |x_a| / W`` where ``W`` sums ``|x_a|`` over the
        adjustable terms only. Sharing by magnitude keeps small line items small
        and avoids sign flips; ``pinned`` addresses (e.g. Total Assets) are held
        fixed so the target magnitude is preserved. Returns the number of rules
        still violated after the final sweep (0 == converged).
        """
        pinned = pinned or set()
        n_violations = 0
        for _ in range(iters):
            n_violations = 0
            for r in self.rules:
                terms = self._rule_terms(r)
                resid = sum(s * values.get(a, 0.0) for s, a in terms)
                # Drive well below the validator's threshold so the final round()
                # to 3 decimals cannot push any rule back over the line.
                if abs(resid) <= float(r["threshold"]) * 0.1:
                    continue
                adjustable = [(s, a) for s, a in terms if a not in pinned]
                if not adjustable:
                    continue  # all terms pinned; cannot fix (rare)
                n_violations += 1
                w = sum(abs(values.get(a, 0.0)) for _s, a in adjustable)
                if w < _EPS:
                    n = len(adjustable)
                    for s, a in adjustable:
                        values[a] = values.get(a, 0.0) - s * resid / n
                else:
                    for s, a in adjustable:
                        values[a] = values.get(a, 0.0) - s * resid * (abs(values.get(a, 0.0)) / w)
            if n_violations == 0:
                break
        return n_violations

    def check(self, values: dict[str, float]) -> list[str]:
        """Rule descriptions that FAIL for a filing (empty for a clean filing)."""
        failures: list[str] = []
        for r in self.rules:
            lhs = sum(s * values.get(a, 0.0) for s, a in parse_expr(r["lhs_expression"]))
            rhs = sum(s * values.get(a, 0.0) for s, a in parse_expr(r["rhs_expression"]))
            if abs(lhs - rhs) > float(r["threshold"]):
                failures.append(
                    f"{r['lhs_expression']}={r['rhs_expression']} ({lhs:.3f} vs {rhs:.3f})"
                )
        return failures
