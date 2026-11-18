"""The invoice's values and the totals computations: what the output shows next to an error."""

import json
from pathlib import Path

import invoices
import pytest
from lxml import etree

from lintvoice import explain

UBL_EXAMPLE = next(
    Path(__file__).parent.parent.glob(".rules-cache/en16931-*/ubl/examples/ubl-tc434-example1.xml"), None
)


def _grand_total(delta):
    def edit(root):
        for tag in ("GrandTotalAmount", "DuePayableAmount"):
            node = root.find(f".//{{{invoices.NS['ram']}}}{tag}")
            node.text = f"{float(node.text) + delta:.2f}"

    return edit


def test_cii_values_are_read():
    values = explain.read(invoices.xml(), "CII")
    assert values["syntax"] == "CII"
    assert values["terms"]["BT-1"] and values["terms"]["BT-5"] == "EUR"
    assert values["terms"]["BT-30"] == invoices.SELLER_SIREN and values["schemes"]["BT-30"] == "0002"
    assert values["terms"]["BT-25"] == ""  # an absent term (no preceding invoice) is an empty string
    assert len(values["lines"]) == len(invoices.FRENCH["lines"])
    assert {n["code"] for n in values["notes"]} >= {"PMT", "PMD", "AAB"}


@pytest.mark.skipif(UBL_EXAMPLE is None, reason="EN 16931 rule pack not installed")
def test_ubl_values_are_read():
    values = explain.read(UBL_EXAMPLE.read_bytes(), "UBL")
    root = etree.parse(str(UBL_EXAMPLE)).getroot()
    assert values["terms"]["BT-1"] == root.findtext(
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID"
    )
    assert values["terms"]["BT-112"] and len(values["lines"]) >= 1


def test_totals_computation_with_the_gap():
    values = explain.read(invoices.xml(edit=_grand_total(1)), "CII")
    calc = explain.computation("BR-CO-15", values)
    assert calc["result"] == "BT-112" and [bt for _, _, bt in calc["parts"]] == ["BT-109", "BT-110"]
    assert calc["gap"] == "1.00" and calc["stated"] == values["terms"]["BT-112"]


def test_computation_is_exact_and_keeps_the_invoice_decimals():
    values = {"terms": {"BT-109": "0.1", "BT-110": "0.2", "BT-112": "0.300"}, "lines": []}
    assert explain.computation("BR-CO-15", values) == {
        "result": "BT-112",
        "parts": [["+", "0.1", "BT-109"], ["+", "0.2", "BT-110"]],
        "expected": "0.300",
        "stated": "0.300",
        "gap": "0.000",
    }


def test_no_computation_for_another_rule_or_a_value_that_is_not_a_number():
    assert explain.computation("BR-FR-10", {"terms": {}, "lines": []}) is None
    assert (
        explain.computation(
            "BR-CO-15", {"terms": {"BT-109": "1 025,00", "BT-110": "205.00", "BT-112": "1230.00"}, "lines": []}
        )
        is None
    )


def test_json_and_text_show_the_computation(lintvoice, write):
    path = write("total.xml", invoices.xml(edit=_grand_total(1)))
    data = json.loads(lintvoice("check", "--format", "json", path).out)
    group = next(g for g in data["files"][0]["findings"] if g["rule"] == "BR-CO-15")
    assert group["computation"]["gap"] == "1.00"
    assert data["files"][0]["values"]["terms"]["BT-112"] == group["computation"]["stated"]
    text = lintvoice("check", path).out
    assert "= " in text and "the invoice states" in text and "a gap of 1.00" in text


TWO_RATES = invoices.french(
    lines=[
        ("Atelier de formation", "2", "450.00", "S", "20"),
        ("Livre", "4", "25.00", "S", "10"),
    ],
    allowances=[("10.00", "95", "Remise", "S", "20")],
)


def _breakdown(rate, tag, delta):
    """Add delta to one element (BasisAmount, CalculatedAmount) of the VAT breakdown at that rate."""

    def edit(root):
        ram = invoices.NS["ram"]
        for tax in root.iterfind(f".//{{{ram}}}ApplicableHeaderTradeSettlement/{{{ram}}}ApplicableTradeTax"):
            if tax.findtext(f"{{{ram}}}RateApplicablePercent") == rate:
                node = tax.find(f"{{{ram}}}{tag}")
                node.text = f"{float(node.text) + delta:.2f}"

    return edit


def test_cii_vat_breakdown_allowances_and_charges_are_read():
    values = explain.read(invoices.xml(TWO_RATES), "CII")
    assert [(b["BT-118"], b["BT-119"], b["BT-116"]) for b in values["vat_breakdown"]] == [
        ("S", "20", "890.00"),
        ("S", "10", "100.00"),
    ]
    assert values["allowances"] == [{"BT-92": "10.00", "BT-95": "S", "BT-96": "20"}]
    assert values["charges"] == []
    assert [line["BT-151"] for line in values["lines"]] == ["S", "S"]


@pytest.mark.skipif(UBL_EXAMPLE is None, reason="EN 16931 rule pack not installed")
def test_ubl_vat_breakdown_is_read():
    values = explain.read(UBL_EXAMPLE.read_bytes(), "UBL")
    assert values["vat_breakdown"] and all(b["BT-116"] and b["BT-118"] for b in values["vat_breakdown"])


def test_vat_amount_computation_shows_the_rate_that_fails():
    values = explain.read(invoices.xml(TWO_RATES, edit=_breakdown("10", "CalculatedAmount", 3)), "CII")
    calc = explain.computation("BR-CO-17", values)
    assert calc["group"]["BT-119"] == "10" and calc["parts"] == [["+", "100.00", "BT-116"], ["×", "10", "BT-119"]]
    assert (calc["expected"], calc["stated"], calc["gap"]) == ("10.00", "13.00", "3.00")


def test_taxable_amount_computation_keeps_the_lines_and_allowances_at_its_rate():
    values = explain.read(invoices.xml(TWO_RATES, edit=_breakdown("20", "BasisAmount", 1)), "CII")
    calc = explain.computation("BR-S-08", values)
    assert calc["group"]["BT-119"] == "20"
    assert calc["parts"] == [["+", "900.00", "BT-131"], ["-", "10.00", "BT-92"]]
    assert (calc["expected"], calc["stated"], calc["gap"]) == ("890.00", "891.00", "1.00")


def test_vat_amount_is_rounded_half_away_from_zero_as_the_rule_does():
    def values(basis):
        return {
            "terms": {},
            "lines": [],
            "vat_breakdown": [{"BT-116": basis, "BT-117": "0.00", "BT-118": "S", "BT-119": "10"}],
        }

    assert explain.computation("BR-CO-17", values("0.25"))["expected"] == "0.03"
    assert explain.computation("BR-CO-17", values("-0.25"))["expected"] == "-0.03"


def test_allowance_total_computation():
    values = explain.read(invoices.xml(TWO_RATES), "CII")
    calc = explain.computation("BR-CO-11", values)
    assert calc["parts"] == [["+", "10.00", "BT-92"]] and calc["gap"] == "0.00"


def test_text_shows_the_rate_of_a_vat_computation(lintvoice, write):
    path = write("vat.xml", invoices.xml(edit=_breakdown("20", "CalculatedAmount", 2)))
    text = lintvoice("check", path).out
    assert "At the rate 20 % (S): 1025.00 (BT-116) × 20 % (BT-119) = 205.00" in text
    data = json.loads(lintvoice("check", "--format", "json", path).out)
    group = next(g for g in data["files"][0]["findings"] if g["rule"] == "BR-CO-17")
    assert group["computation"]["gap"] == "2.00" and group["computation"]["group"]["BT-118"] == "S"


def test_text_says_when_there_is_nothing_to_add_up(lintvoice, write):
    path = write("no-line.xml", invoices.xml(edit=invoices.remove("//ram:IncludedSupplyChainTradeLineItem")))
    text = lintvoice("check", path).out
    assert "nothing to add up = 0.00; the invoice states 1025.00 (BT-106)" in text
