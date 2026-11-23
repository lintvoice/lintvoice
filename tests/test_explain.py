"""The invoice's values and the totals computations: what the output shows next to an error."""

import io
import json
from pathlib import Path

import invoices
import pytest
from lxml import etree

from lintvoice import explain

UBL_EXAMPLE = next(
    Path(__file__).parent.parent.glob(".rules-cache/en16931-*/ubl/examples/ubl-tc434-example1.xml"), None
)
UBL_EXAMPLES = sorted(Path(__file__).parent.parent.glob(".rules-cache/en16931-*/ubl/examples/ubl-tc434-*.xml"))
CII_EXAMPLES = sorted(Path(__file__).parent.parent.glob(".rules-cache/en16931-*/cii/examples/*.xml"))


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
    assert values["allowances"] == [
        {"BT-92": "10.00", "BT-93": "", "BT-95": "S", "BT-96": "20", "BT-97": "Remise", "BT-98": "95"}
    ]
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


# --- the terms behind every explained rule: header, lines and their allowances, charges and attributes, documents


@pytest.fixture(scope="module")
def failing(tmp_path_factory):
    """The values of one failing example of invoice-examples (target fr, CII), by name."""
    examples_cli = pytest.importorskip("invoice_examples.cli")
    out = tmp_path_factory.mktemp("examples")
    assert examples_cli.main(["generate", "--target", "fr", "--out", str(out)], out=io.StringIO()) == 0
    return lambda name: explain.read((out / "fr" / "invalid" / f"{name}.xml").read_bytes(), "CII")


def test_cii_payee_delivery_and_period_terms_are_read(failing):
    values = failing("BR-FR-09-payee")
    terms, schemes = values["terms"], values["schemes"]
    assert (terms["BT-59"], terms["BT-60"], terms["BT-61"]) == ("Affacturage Exemple", "01234567400019", "034567891")
    assert (schemes["BT-60"], schemes["BT-61"]) == ("0009", "0002")
    assert terms["BT-72"] == "20261015"
    assert terms["BT-12"] == terms["BT-73"] == terms["BT-74"] == ""  # absent terms are empty strings


def test_the_first_path_of_a_list_that_finds_an_element_counts(failing):
    # a seller identifier under another scheme than SIRET (0009) is read, with its scheme
    values = failing("BR-FR-32-GLOBALID")
    assert (values["terms"]["BT-29"], values["schemes"]["BT-29"]) == ("01234567", "0002")
    # a payee identifier without a scheme is read, and has no scheme
    values = failing("BR-FR-CO-10-BT-60-1")
    assert values["terms"]["BT-60"] == "03456789100014" and "BT-60" not in values["schemes"]


def test_a_last_step_reads_an_attribute(failing):
    assert {line["BT-130"] for line in failing("BR-FR-29")["lines"]} == {"C62"}
    assert {line["BT-130"] for line in failing("BR-23")["lines"]} >= {""}  # the quantity without its unit


def test_cii_documents_are_read(failing):
    assert failing("BR-FR-29")["documents"] == [
        {"BT-122": "OBJ-1", "BT-123": "", "type": "130", "BT-18-1": "AFL", "BT-125": "", "BT-125-1": ""},
        {"BT-122": "OBJ-2", "BT-123": "", "type": "130", "BT-18-1": "AFL", "BT-125": "", "BT-125-1": ""},
    ]
    assert failing("BR-FR-17")["documents"] == [
        {"BT-122": "PJ-1", "BT-123": "CONTRAT", "type": "916", "BT-18-1": "", "BT-125": "", "BT-125-1": ""}
    ]


def test_cii_line_allowances_charges_price_and_attributes_are_read(failing):
    line = failing("BR-CO-23")["lines"][0]
    assert line["allowances"] == [{"BT-136": "50.00", "BT-137": "", "BT-139": "", "BT-140": ""}]
    assert line["charges"] == [] and line["attributes"] == []
    line = failing("BR-FR-DEC-03-BT-147")["lines"][0]
    assert (line["BT-147"], line["BT-148"]) == ("50.0000000", "500.00")
    assert failing("BR-FR-27")["lines"][0]["attributes"] == [{"BT-160": "", "BT-161": "Bleu"}]


def test_cii_allowance_terms_are_read(failing):
    assert failing("BR-FR-DEC-01-BT-93")["allowances"] == [
        {
            "BT-92": "10.25",
            "BT-93": "1025.000",
            "BT-95": "S",
            "BT-96": "20",
            "BT-97": "Remise commerciale",
            "BT-98": "95",
        }
    ]


def test_without_lines_allowances_or_documents_the_groups_are_empty():
    values = explain.read(invoices.xml(edit=invoices.remove("//ram:IncludedSupplyChainTradeLineItem")), "CII")
    assert values["lines"] == values["allowances"] == values["charges"] == values["documents"] == []
    line = explain.read(invoices.xml(), "CII")["lines"][0]
    assert line["allowances"] == line["charges"] == line["attributes"] == []


def _vat_total_in_euros_first(root):
    """Move the VAT total in the VAT accounting currency (BT-111) before the one in the invoice's currency (BT-110)."""
    first, second = root.findall(".//ram:TaxTotalAmount", invoices.NS)
    first.addprevious(second)


def test_the_vat_totals_are_told_apart_by_their_currency():
    """BT-110 is the VAT total in the invoice's currency (BT-5), BT-111 the one in the VAT accounting currency (BT-6),
    in whichever order the invoice gives them."""
    dollars = invoices.french(currency="USD", tax_currency=("EUR", "0.9216"))
    for edit in (None, _vat_total_in_euros_first):
        terms = explain.read(invoices.xml(dollars, edit=edit), "CII")["terms"]
        assert (terms["BT-5"], terms["BT-6"], terms["BT-110"], terms["BT-111"]) == ("USD", "EUR", "205.00", "188.93")
    assert explain.read(invoices.xml(), "CII")["terms"]["BT-111"] == ""
    if UBL_EXAMPLE is not None:
        text = UBL_EXAMPLE.read_text(encoding="utf-8")
        before = explain.read(text.encode(), "UBL")["terms"]
        assert before["BT-110"] and before["BT-111"] == ""
        # the same invoice with a VAT accounting currency, its VAT total in that currency given first
        accounting = "USD" if before["BT-5"] == "EUR" else "EUR"
        code = f"<cbc:DocumentCurrencyCode>{before['BT-5']}</cbc:DocumentCurrencyCode>"
        text = text.replace(code, f"{code}<cbc:TaxCurrencyCode>{accounting}</cbc:TaxCurrencyCode>", 1)
        at = text.index("<cac:TaxTotal>")
        total = f'<cac:TaxTotal><cbc:TaxAmount currencyID="{accounting}">31.12</cbc:TaxAmount></cac:TaxTotal>'
        terms = explain.read((text[:at] + total + text[at:]).encode(), "UBL")["terms"]
        assert (terms["BT-110"], terms["BT-111"]) == (before["BT-110"], "31.12")


def test_a_line_invoiced_object_identifier_is_read():
    """BT-128, in CII under the line's settlement, in UBL its document reference."""

    def object_id(root):
        settle = root.find(".//ram:SpecifiedLineTradeSettlement", invoices.NS)
        doc = etree.SubElement(settle, f"{{{invoices.NS['ram']}}}AdditionalReferencedDocument")
        etree.SubElement(doc, f"{{{invoices.NS['ram']}}}IssuerAssignedID").text = "ABO-42"
        etree.SubElement(doc, f"{{{invoices.NS['ram']}}}TypeCode").text = "130"
        settle.find("ram:SpecifiedTradeSettlementLineMonetarySummation", invoices.NS).addnext(doc)

    lines = explain.read(invoices.xml(edit=object_id), "CII")["lines"]
    assert lines[0]["BT-128"] == "ABO-42" and lines[1]["BT-128"] == ""


def test_a_payment_card_number_is_read():
    """BT-87: no CEN example pays by card, so a card is added, in CII to the payment means, in UBL to a CEN example's."""

    def card(root):
        means = root.find(".//ram:SpecifiedTradeSettlementPaymentMeans", invoices.NS)
        node = etree.Element(f"{{{invoices.NS['ram']}}}ApplicableTradeSettlementFinancialCard")
        etree.SubElement(node, f"{{{invoices.NS['ram']}}}ID").text = "1234"
        means.find("ram:TypeCode", invoices.NS).addnext(node)

    assert explain.read(invoices.xml(edit=card), "CII")["terms"]["BT-87"] == "1234"
    if UBL_EXAMPLE is not None:
        root = etree.fromstring(UBL_EXAMPLE.read_bytes())
        cac = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        cbc = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
        account = etree.SubElement(root.find(f"{{{cac}}}PaymentMeans"), f"{{{cac}}}CardAccount")
        etree.SubElement(account, f"{{{cbc}}}PrimaryAccountNumberID").text = "1234"
        assert explain.read(etree.tostring(root), "UBL")["terms"]["BT-87"] == "1234"


def test_bt_32_is_not_read_in_ubl():
    """BT-32 in UBL is told from the VAT number (BT-31) by its tax scheme, which a path does not express."""
    assert "BT-32" in explain.read(invoices.xml(), "CII")["terms"]
    if UBL_EXAMPLE is not None:
        assert "BT-32" not in explain.read(UBL_EXAMPLE.read_bytes(), "UBL")["terms"]


NEW_PLACES = {
    "terms": ["BT-6", "BT-8", "BT-12", "BT-20", "BT-59", "BT-60", "BT-61", "BT-63", "BT-70", "BT-71", "BT-72"],
    "terms ": ["BT-73", "BT-74", "BT-24", "BT-62", "BT-69", "BT-80", "BT-81", "BT-84"],
    "lines": ["BT-130", "BT-134", "BT-135", "BT-147", "BT-148", "BT-149", "BT-126", "BT-157", "BT-157-1"],
    "lines ": ["BT-158", "BT-158-1", "BT-159"],
    "line allowances": ["BT-136", "BT-137", "BT-139", "BT-140"],
    "line charges": ["BT-141", "BT-142", "BT-144", "BT-145"],
    "line attributes": ["BT-160", "BT-161"],
    "vat_breakdown": ["BT-120", "BT-121"],
    "allowances": ["BT-93", "BT-97", "BT-98"],
    "charges": ["BT-100", "BT-104", "BT-105"],
    "documents": ["BT-122", "BT-123", "type", "BT-18-1", "BT-125", "BT-125-1"],
}


def _found(values):
    """Each (place, term) with a value somewhere in the invoice."""
    rows = [("terms", values["terms"]), ("terms ", values["terms"])]
    for line in values["lines"]:
        rows += [("lines", line), ("lines ", line)] + [
            (f"line {g}", item) for g in ("allowances", "charges", "attributes") for item in line[g]
        ]
    rows += [(g, item) for g in ("vat_breakdown", "allowances", "charges", "documents") for item in values[g]]
    return {(place, bt) for place, row in rows for bt, v in row.items() if v and not isinstance(v, list)}


def _with_document_type_and_exemption_code(xml):
    """The CEN examples have no supporting document type or scheme, nor an exemption reason code: add them."""
    root = etree.fromstring(xml)
    cac = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    cbc = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    doc = root.find(f"{{{cac}}}AdditionalDocumentReference")
    if doc is not None:
        doc.find(f"{{{cbc}}}ID").set("schemeID", "AFL")
        etree.SubElement(doc, f"{{{cbc}}}DocumentTypeCode").text = "130"
    category = root.find(f"{{{cac}}}TaxTotal/{{{cac}}}TaxSubtotal/{{{cac}}}TaxCategory")
    etree.SubElement(category, f"{{{cbc}}}TaxExemptionReasonCode").text = "VATEX-EU-79-C"
    return etree.tostring(root)


def _missing(found):
    return [(place, bt) for place, bts in NEW_PLACES.items() for bt in bts if (place, bt) not in found]


@pytest.mark.skipif(not CII_EXAMPLES, reason="EN 16931 rule pack not installed")
def test_cii_new_places_are_read_in_the_cen_and_failing_examples(failing):
    found = set()
    for path in CII_EXAMPLES:
        found |= _found(explain.read(path.read_bytes(), "CII"))
    found |= _found(failing("BR-FR-29")) | _found(failing("BR-S-02"))  # a supporting document's scheme, BT-8
    assert not _missing(found), _missing(found)


@pytest.mark.skipif(not UBL_EXAMPLES, reason="EN 16931 rule pack not installed")
def test_ubl_new_places_are_read_in_the_cen_examples():
    found = set()
    for path in UBL_EXAMPLES:
        found |= _found(explain.read(_with_document_type_and_exemption_code(path.read_bytes()), "UBL"))
    assert not _missing(found), _missing(found)
