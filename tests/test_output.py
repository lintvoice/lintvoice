"""Output formats: JSON for CI, quiet mode, colour."""

import json

import invoices


def _bad(write):
    conf = invoices.french(lines=[("Article", "1", "10.00", "S", "20")] * 2)
    conf["seller"] = {**conf["seller"], "vat": None}
    return write("bad.xml", invoices.xml(conf))


def test_json_report_structure(lintvoice, write):
    r = lintvoice("check", "--format", "json", write("ok.xml", invoices.xml()), _bad(write), write("junk.xml", "x"))
    data = json.loads(r.out)
    assert data["exit_code"] == r.code == 2
    ok, bad, junk = data["files"]
    assert ok["status"] == "ok" and ok["summary"] == {"errors": 0, "warnings": 0, "rules_failed": 0}
    assert ok["document"] == {
        "syntax": "CII",
        "profile": "en16931",
        "specification_id": "urn:cen.eu:en16931:2017",
        "source": "XML",
        "seller_country": "FR",
    }
    assert [rs["id"] for rs in ok["rule_sets"]] == ["xsd", "en16931", "br-fr"]
    assert bad["status"] == "errors"
    group = next(f for f in bad["findings"] if f["rule"] == "BR-S-02")
    assert group["count"] == 2 and group["severity"] == "error" and group["rule_set"] == "en16931"
    assert len(group["messages"]) == 1 and len(group["messages"][0]["locations"]) == 2
    assert junk == {"path": str(junk["path"]), "status": "unreadable", "error": junk["error"]}


def test_json_has_no_colour_codes(lintvoice, write):
    r = lintvoice("check", "--format", "json", "--color", "always", _bad(write))
    assert "\033[" not in r.out
    json.loads(r.out)


def test_quiet_lists_only_files_with_errors(lintvoice, write):
    ok, bad = write("ok.xml", invoices.xml()), _bad(write)
    r = lintvoice("check", "-q", ok, bad)
    assert str(bad) in r.out and str(ok) not in r.out
    assert "2 files checked: 1 with errors, 1 without." in r.out


def test_no_colour_when_not_a_terminal(lintvoice, write):
    assert "\033[" not in lintvoice("check", _bad(write)).out


def test_colour_on_request(lintvoice, write):
    assert "\033[31m" in lintvoice("check", "--color", "always", _bad(write)).out


def test_header_names_the_rule_sets_used(lintvoice, write):
    first_line = lintvoice("check", write("ok.xml", invoices.xml())).out.splitlines()[0]
    assert first_line.startswith("lintvoice ")
    assert "EN 16931 1.3.17 (CII)" in first_line and "BR-FR 1.4.0.04 (CII)" in first_line
