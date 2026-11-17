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
