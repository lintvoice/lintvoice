"""Properties of the computations shown next to a totals or VAT error, over generated invoices (Hypothesis).

The reference is the official rule itself: each invoice is checked by the EN 16931 rule files, and what lintvoice
explains must agree with what the rule decided.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

pytest.importorskip("hypothesis")  # Hypothesis needs Python 3.11 or later; the rest of the suite runs on 3.10 too

import invoices
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from lintvoice import document, engine, explain

RAM = invoices.NS["ram"]
CENT = Decimal("0.01")
ENGINE = engine.Engine(Path(__file__).parent.parent / ".rules-cache")  # installed by conftest.py
# Each example runs the rule files; the environment fixtures do not change between examples.
SLOW = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

TWO_RATES = invoices.french(
    lines=[
        ("Atelier de formation", "2", "450.00", "S", "20"),
        ("Livre", "4", "25.00", "S", "10"),
    ],
    allowances=[("10.00", "95", "Remise", "S", "20")],
)


def failed_rules(xml_bytes, tmp_path):
    path = tmp_path / "invoice.xml"
    path.write_bytes(xml_bytes)
    return {f.rule for f in ENGINE.check(document.load(path)).findings}


def vat_amounts(changes):
    """An edit: the VAT amount (BT-117) of the breakdown at each rate becomes sign × amount + delta."""

    def edit(root):
        for tax in root.iterfind(f".//{{{RAM}}}ApplicableHeaderTradeSettlement/{{{RAM}}}ApplicableTradeTax"):
            rate = tax.findtext(f"{{{RAM}}}RateApplicablePercent")
            if rate in changes:
                sign, delta = changes[rate]
                node = tax.find(f"{{{RAM}}}CalculatedAmount")
                node.text = str((Decimal(node.text) * sign + delta).quantize(CENT))

    return edit


def rejects(rule, breakdown):
    """BR-CO-17 and BR-S-09 as the EN 16931 rule files test a VAT breakdown in CII: the stated amount, without its
    sign, within 1 of round(|base| × rate / 100, 2); BR-CO-17 accepts a difference of exactly 1, BR-S-09 does not."""
    tax, base, rate = (Decimal(breakdown[bt]) for bt in ("BT-117", "BT-116", "BT-119"))
    expected = (abs(base) * rate / 100).quantize(CENT, ROUND_HALF_UP)
    if rule == "BR-CO-17":
        return not abs(tax) - 1 <= expected <= abs(tax) + 1
    return not abs(tax) - 1 < expected < abs(tax) + 1


deltas = st.decimals(min_value=-3, max_value=3, places=2, allow_nan=False, allow_infinity=False)
changes = st.tuples(st.sampled_from([1, -1]), deltas)


@SLOW
@given(at_20=changes, at_10=changes)
# The 20 % breakdown is 1.00 off (BR-S-09 rejects it); the 10 % one only has its sign flipped (both rules accept it).
@example(at_20=(1, Decimal("1.00")), at_10=(-1, Decimal("0")))
def test_the_breakdown_explained_is_one_the_rule_rejects(at_20, at_10, tmp_path):
    xml_bytes = invoices.xml(TWO_RATES, edit=vat_amounts({"20": at_20, "10": at_10}))
    values = explain.read(xml_bytes, "CII")
    for rule in failed_rules(xml_bytes, tmp_path) & {"BR-CO-17", "BR-S-09"}:
        calc = explain.computation(rule, values)
        assert calc is not None, rule
        assert rejects(rule, calc["group"]), (rule, calc)


totals = ["LineTotalAmount", "TaxBasisTotalAmount", "TaxTotalAmount", "GrandTotalAmount", "DuePayableAmount"]


@SLOW
@given(tag=st.sampled_from(totals), delta=deltas.filter(lambda d: d != 0))
def test_a_failing_total_shows_a_gap(tag, delta, tmp_path):
    def edit(root):
        node = root.find(f".//{{{RAM}}}{tag}")
        node.text = str((Decimal(node.text) + delta).quantize(CENT))

    xml_bytes = invoices.xml(TWO_RATES, edit=edit)
    values = explain.read(xml_bytes, "CII")
    for rule in failed_rules(xml_bytes, tmp_path) & {"BR-CO-10", "BR-CO-13", "BR-CO-14", "BR-CO-15", "BR-CO-16"}:
        calc = explain.computation(rule, values)
        assert calc is not None and Decimal(calc["gap"]) != 0, (rule, calc)


@given(
    base=st.decimals(min_value=-1, max_value=1, places=2, allow_nan=False, allow_infinity=False),
    rate=st.sampled_from(["5.5", "10", "20"]),
)
@example(base=Decimal("-0.01"), rate="5.5")
def test_an_amount_that_rounds_to_zero_has_no_sign(base, rate):
    values = {
        "terms": {},
        "lines": [],
        "vat_breakdown": [{"BT-116": str(base), "BT-117": "2.00", "BT-118": "S", "BT-119": rate}],
    }
    calc = explain.computation("BR-CO-17", values)
    for key in ("expected", "gap"):
        if Decimal(calc[key]) == 0:
            assert not calc[key].startswith("-"), (key, calc)
