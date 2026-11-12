"""An error inside an official rule file is an incomplete check (exit 4), never a verdict or a traceback.

The case: France_RFE 1.4.0.04's BR-FR-09 rule stops with XPTY0004 when the deliver-to party (BG-13) has two
SIRETs (scheme 0009), since its $siren variable calls substring() on both. The invoice is schema-valid.
"""

import json
import subprocess
import sys

from lxml import etree

import invoices
from invoices import NS

SIRETS = [invoices.luhn_complete(invoices.BUYER_SIREN + n) for n in ("0003", "0004")]


def _ship_to_with_two_sirets(root):
    party = etree.Element(f"{{{NS['ram']}}}ShipToTradeParty")
    for siret in SIRETS:
        etree.SubElement(party, f"{{{NS['ram']}}}GlobalID", schemeID="0009").text = siret
    etree.SubElement(party, f"{{{NS['ram']}}}Name").text = "Médiathèque d'Exemple"
    root.find(".//ram:ApplicableHeaderTradeDelivery", NS).insert(0, party)


def test_crash_in_a_rule_file_is_an_incomplete_check(lintvoice, write):
    r = lintvoice("check", write("ship-to.xml", invoices.xml(edit=_ship_to_with_two_sirets)))
    assert r.code == 4, r
    assert "Traceback" not in r.out + r.err
    assert "BR-FR 1.4.0.04 (CII) could not run on this file" in r.out
    assert "fn:substring()" in r.out
    assert "No errors in the rules that ran." in r.out
    assert "1 file checked: 0 with errors, 1 incomplete, 0 without." in r.out


def test_crash_in_a_rule_file_in_json(lintvoice, write):
    r = lintvoice("check", "--format", "json", write("ship-to.xml", invoices.xml(edit=_ship_to_with_two_sirets)))
    assert r.code == 4, r
    report = json.loads(r.out)
    assert report["exit_code"] == 4
    (f,) = report["files"]
    assert f["status"] == "incomplete"
    assert [n["rule_set"] for n in f["not_run"]] == ["br-fr"]
    assert "XPTY0004" in f["not_run"][0]["error"] or "substring" in f["not_run"][0]["error"]


def test_errors_found_elsewhere_still_give_exit_1(lintvoice, write):
    """The invoice is invalid anyway (EN 16931: no seller VAT number), so the verdict stands; the warning stays."""
    conf = invoices.french()
    conf["seller"] = {**conf["seller"], "vat": None}
    r = lintvoice("check", write("ship-to.xml", invoices.xml(conf, edit=_ship_to_with_two_sirets)))
    assert r.code == 1, r
    assert "✗" in r.out and "could not run on this file" in r.out


def test_quiet_still_shows_an_incomplete_file(lintvoice, write):
    r = lintvoice("check", "--quiet", write("ship-to.xml", invoices.xml(edit=_ship_to_with_two_sirets)))
    assert r.code == 4, r
    assert "could not run on this file" in r.out


def test_no_native_trace_on_stderr(write):
    """In a real process: SaxonC's own error trace must not reach the terminal or the CI log."""
    path = write("ship-to.xml", invoices.xml(edit=_ship_to_with_two_sirets))
    p = subprocess.run([sys.executable, "-m", "lintvoice", "check", str(path)], capture_output=True, text=True)
    assert p.returncode == 4, p
    assert p.stderr == "", p.stderr
    assert "could not run on this file" in p.stdout
