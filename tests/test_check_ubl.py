"""Checking UBL invoices and credit notes."""

import re


def test_official_ubl_invoice_passes(lintvoice, official):
    r = lintvoice("check", official("ubl", "ubl-tc434-example1.xml"))
    assert r.code == 0, r
    assert "EN 16931 · UBL · XML" in r.out
    assert "EN 16931 1.3.17 (UBL)" in r.out


def test_official_ubl_credit_note_passes(lintvoice, official):
    r = lintvoice("check", official("ubl", "ubl-tc434-creditnote1.xml"))
    assert r.code == 0, r


def test_french_seller_brings_br_fr_rules_to_ubl(lintvoice, official, write):
    xml = official("ubl", "ubl-tc434-example1.xml").read_text(encoding="utf-8")
    # Move the seller to France: its first country code is the AccountingSupplierParty's.
    supplier = xml.index("<cac:AccountingSupplierParty>")
    head, tail = xml[:supplier], xml[supplier:]
    tail = re.sub(
        r"<cbc:IdentificationCode>[A-Z]{2}</cbc:IdentificationCode>",
        "<cbc:IdentificationCode>FR</cbc:IdentificationCode>",
        tail,
        count=1,
    )
    r = lintvoice("check", write("fr.xml", head + tail))
    assert "BR-FR rules applied" in r.out
    assert "BR-FR 1.4.0.04 (UBL)" in r.out
    assert r.code == 1
    assert "BR-FR-10" in r.out


def test_peppol_invoice_says_peppol_rules_are_not_checked(lintvoice, official):
    r = lintvoice("check", official("ubl", "BIS3_Invoice_positive.XML"))
    assert r.code == 0, r
    assert "Peppol BIS Billing 3.0" in r.out
    assert "Peppol BIS rules are not in this version: only EN 16931 was checked." in r.out


def test_broken_ubl_is_reported(lintvoice, official, write):
    xml = official("ubl", "ubl-tc434-example1.xml").read_text(encoding="utf-8")
    xml = re.sub(
        r"<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>",
        "<cbc:DocumentCurrencyCode>EUX</cbc:DocumentCurrencyCode>",
        xml,
    )
    r = lintvoice("check", write("eux.xml", xml))
    assert r.code == 1
    assert "BR-CL-04" in r.out
