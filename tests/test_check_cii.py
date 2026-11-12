"""Checking CII and Factur-X invoices: verdicts, rule selection, grouping, pinned counts."""

import json

import invoices
from invoices import NS


def test_valid_french_invoice_passes(lintvoice, write):
    r = lintvoice("check", write("ok.xml", invoices.xml()))
    assert r.code == 0, r
    assert "✓" in r.out and "No errors." in r.out
    assert "BR-FR rules applied: the seller's country is FR." in r.out
    assert "1 file checked: 0 with errors, 1 without." in r.out


def test_valid_french_facturx_pdf_passes(lintvoice, write):
    r = lintvoice("check", write("ok.pdf", invoices.facturx_pdf(invoices.xml())))
    assert r.code == 0, r
    assert "Factur-X EN 16931 · CII · PDF (factur-x.xml)" in r.out
    assert "Factur-X 1.09.2 EN 16931" in r.out  # profile rules run on a PDF


def test_zugferd_attachment_name_is_found(lintvoice, write):
    r = lintvoice("check", write("z.pdf", invoices.facturx_pdf(invoices.xml(), name="zugferd-invoice.xml")))
    assert r.code == 0, r
    assert "PDF (zugferd-invoice.xml)" in r.out


def test_missing_siren_is_reported(lintvoice, write):
    conf = invoices.french()
    conf["seller"] = {**conf["seller"], "legal_id": None}
    r = lintvoice("check", write("no-siren.xml", invoices.xml(conf)))
    assert r.code == 1, r
    assert "BR-FR-10_BT-30" in r.out
    assert "✗" in r.out


def test_one_failure_per_line_is_grouped(lintvoice, write):
    """No seller VAT number with standard-rated lines: one BR-S-02 group, counted once per line."""
    conf = invoices.french(lines=[("Article", "1", "10.00", "S", "20")] * 4)
    conf["seller"] = {**conf["seller"], "vat": None}
    r = lintvoice("check", write("no-vat.xml", invoices.xml(conf)))
    assert r.code == 1
    assert r.out.count("BR-S-02") == 1
    assert "BR-S-02  ×4" in r.out
    assert "(+3 more)" in r.out


def test_verbose_lists_every_location(lintvoice, write):
    conf = invoices.french(lines=[("Article", "1", "10.00", "S", "20")] * 3)
    conf["seller"] = {**conf["seller"], "vat": None}
    r = lintvoice("check", "-v", write("no-vat.xml", invoices.xml(conf)))
    assert "(+2 more)" not in r.out
    assert "IncludedSupplyChainTradeLineItem[3]" in r.out


def test_missing_legal_notes_are_three_rules(lintvoice, write):
    r = lintvoice("check", write("no-notes.xml", invoices.xml(invoices.french(notes=[]))))
    assert r.code == 1
    for code in ("PMT", "PMD", "AAB"):
        assert f"BR-FR-05_BT-22_{code}" in r.out
    assert "BR-FR-05/BT-22 :" not in r.out  # the rule id is not repeated inside the message


def test_br_fr_skipped_for_a_foreign_seller(lintvoice, write):
    conf = invoices.french()
    conf["seller"] = {**conf["seller"], "address": ("1011", "Damrak 1", "Amsterdam", "NL"), "legal_id": None}
    r = lintvoice("check", write("nl.xml", invoices.xml(conf)))
    assert r.code == 0, r
    assert "BR-FR rules not applied: the seller's country is NL" in r.out


def test_rules_option_limits_the_rule_sets(lintvoice, write):
    conf = invoices.french()
    conf["seller"] = {**conf["seller"], "legal_id": None}
    path = write("no-siren.xml", invoices.xml(conf))
    assert lintvoice("check", path).code == 1
    r = lintvoice("check", "--rules", "en16931", path)
    assert r.code == 0, r
    assert "BR-FR" not in r.out


def test_en16931_error_is_reported_with_plain_message(lintvoice, write):
    edit = invoices.remove("//ram:ApplicableHeaderTradeSettlement/ram:InvoiceCurrencyCode")
    r = lintvoice("check", write("no-currency.xml", invoices.xml(edit=edit)))
    assert r.code == 1
    assert "BR-05" in r.out
    assert "[BR-05]-" not in r.out  # the official prefix is dropped


def test_schema_errors_come_after_rule_findings(lintvoice, write):
    """No invoice number in a Factur-X PDF: EN 16931 says BR-02, the Factur-X schema says 'TypeCode not
    expected'. BR-02 comes first. (The CII D22B schema used for bare XML allows a missing number.)"""
    xml = invoices.xml(edit=invoices.remove("/rsm:CrossIndustryInvoice/rsm:ExchangedDocument/ram:ID"))
    r = lintvoice("check", write("no-id.pdf", invoices.facturx_pdf(xml)))
    assert r.code == 1
    assert "BR-02" in r.out and "XSD" in r.out
    assert r.out.index("BR-02") < r.out.index("XSD")
    assert "TypeCode" in r.out  # the schema message, without namespaces
    assert "{urn:" not in r.out


def test_plain_cii_xml_does_not_get_facturx_profile_rules(lintvoice, official):
    r = lintvoice("check", official("cii", "CII_example1.xml"))
    assert r.code == 0, r
    assert "Factur-X 1.09.2" not in r.out
    assert "EN 16931 · CII · XML" in r.out


def test_facturx_rules_can_be_forced_on_xml(lintvoice, write):
    r = lintvoice("check", "--rules", "en16931,factur-x,br-fr", write("ok.xml", invoices.xml()))
    assert r.code == 0, r
    assert "Factur-X 1.09.2 EN 16931" in r.out


def test_example1_as_pdf_gives_29_br_fr_failures_in_9_rules(lintvoice, write, official):
    """The official CII_example1 as a Factur-X PDF: 29 BR-FR failures in 9 rules, pinned so that a change in
    rule selection, grouping or counting shows up."""
    pdf = write("example1.pdf", invoices.facturx_pdf(official("cii", "CII_example1.xml").read_bytes()))
    r = lintvoice("check", "--format", "json", "--rules", "en16931,factur-x,br-fr", pdf)
    import json

    report = json.loads(r.out)["files"][0]
    br_fr = [f for f in report["findings"] if f["rule_set"] == "br-fr"]
    assert sum(f["count"] for f in br_fr) == 29
    assert sorted(f["rule"] for f in br_fr) == [
        "BR-FR-05_BT-22_AAB",
        "BR-FR-05_BT-22_PMD",
        "BR-FR-05_BT-22_PMT",
        "BR-FR-08_BT-23",
        "BR-FR-10_BT-30",
        "BR-FR-12_BT-49",
        "BR-FR-13_BT-34",
        "BR-FR-16_BT-119",
        "BR-FR-16_BT-152",
    ]
    assert report["summary"]["errors"] == 29
    assert r.code == 1


def test_minimum_profile_skips_en16931_and_br_fr(lintvoice, write):
    r = lintvoice("check", write("min.xml", invoices.xml(invoices.french(profile="urn:factur-x.eu:1p0:minimum"))))
    assert "Factur-X MINIMUM" in r.out
    assert "No Factur-X MINIMUM profile rules" in r.out
    assert "EN 16931 1.3.17" not in r.out.split("\n")[0]


def test_unknown_profile_is_said(lintvoice, write):
    r = lintvoice("check", write("u.xml", invoices.xml(invoices.french(profile="urn:example:unknown"))))
    assert "Unknown specification identifier (BT-24) 'urn:example:unknown'" in r.out


assert NS  # imported for readability of xpath edits in this module


def test_xrechnung_in_a_pdf_is_labelled_xrechnung(lintvoice, write):
    """Found in normapi's examples (github.com/normapi-com/xrechnung-zugferd-examples): a ZUGFeRD PDF carrying an XRechnung was labelled "Factur-X XRechnung"."""
    conf = invoices.french(profile="urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0")
    r = lintvoice("check", write("x.pdf", invoices.facturx_pdf(invoices.xml(conf), name="xrechnung.xml")))
    assert "XRechnung · CII · PDF (xrechnung.xml)" in r.out
    assert "Factur-X XRechnung" not in r.out
    assert "XRechnung rules are not in this version" in r.out


def _plus_one_euro(root):
    """Add 1.00 to the total with VAT and the amount due: BR-CO-15 fails, nothing else."""
    for tag in ("GrandTotalAmount", "DuePayableAmount"):
        node = root.find(f".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:{tag}", NS)
        node.text = f"{float(node.text) + 1:.2f}"


def test_a_rule_repeated_by_the_factur_x_profile_rules_counts_once(lintvoice, write):
    """EN 16931 and the Factur-X profile rules both report BR-CO-15, at two locations: one error, not two."""
    r = lintvoice(
        "check", "--format", "json", write("total.pdf", invoices.facturx_pdf(invoices.xml(edit=_plus_one_euro)))
    )
    assert r.code == 1, r
    (f,) = json.loads(r.out)["files"]
    assert [(g["rule"], g["rule_set"], g["count"]) for g in f["findings"]] == [("BR-CO-15", "en16931", 1)]
    assert f["summary"]["errors"] == 1
