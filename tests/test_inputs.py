"""Files that are not what they claim, directories, and exit codes."""

import invoices


def test_missing_file(lintvoice, tmp_path):
    r = lintvoice("check", tmp_path / "nope.xml")
    assert r.code == 2
    assert "file not found" in r.out
    assert "1 file checked: 0 with errors, 0 without, 1 unreadable." in r.out


def test_not_well_formed_xml(lintvoice, write):
    r = lintvoice("check", write("broken.xml", "<Invoice><oops></Invoice>"))
    assert r.code == 2
    assert "not well-formed XML" in r.out


def test_xml_that_is_not_an_invoice(lintvoice, write):
    r = lintvoice("check", write("order.xml", "<Order xmlns='urn:example'/>"))
    assert r.code == 2
    assert "not a CII or UBL invoice (root element 'Order')" in r.out


def test_pdf_without_embedded_invoice(lintvoice, write):
    r = lintvoice("check", write("plain.pdf", invoices.facturx_pdf(None)))
    assert r.code == 2
    assert "no embedded invoice XML" in r.out


def test_corrupt_pdf(lintvoice, write):
    r = lintvoice("check", write("bad.pdf", b"%PDF-1.7\nnot really a pdf"))
    assert r.code == 2
    assert "cannot read this PDF" in r.out


def test_utf8_bom_is_accepted(lintvoice, write):
    r = lintvoice("check", write("bom.xml", b"\xef\xbb\xbf" + invoices.xml()))
    assert r.code == 0, r


def test_directory_checks_xml_and_pdf_recursively(lintvoice, write, tmp_path):
    write("a/ok.xml", invoices.xml())
    write("a/b/ok.pdf", invoices.facturx_pdf(invoices.xml()))
    write("a/notes.txt", "ignored")
    r = lintvoice("check", tmp_path / "a")
    assert r.code == 0, r
    assert "2 files checked: 0 with errors, 2 without." in r.out


def test_one_failing_file_makes_the_run_fail(lintvoice, write):
    ok = write("ok.xml", invoices.xml())
    bad = write("bad.xml", invoices.xml(invoices.french(notes=[])))
    r = lintvoice("check", ok, bad)
    assert r.code == 1
    assert "2 files checked: 1 with errors, 1 without." in r.out


def test_an_unreadable_file_wins_over_errors(lintvoice, write):
    bad = write("bad.xml", invoices.xml(invoices.french(notes=[])))
    junk = write("junk.xml", "not xml")
    assert lintvoice("check", bad, junk).code == 2


def test_empty_directory(lintvoice, tmp_path):
    r = lintvoice("check", tmp_path)
    assert r.code == 2
    assert "no .xml or .pdf file found" in r.err


def test_non_invoice_xml_in_a_directory_is_skipped(lintvoice, write, tmp_path):
    """Found in KoSIT's XRechnung test suite (github.com/itplr-kosit/xrechnung-testsuite, v2026-08-31): a build.xml next to the invoices must not fail the run."""
    write("repo/build.xml", "<project name='x'/>")
    write("repo/invoices/ok.xml", invoices.xml())
    r = lintvoice("check", tmp_path / "repo")
    assert r.code == 0, r
    assert "Skipped 1 XML file that is not an invoice" in r.out
    assert "1 file checked: 0 with errors, 1 without." in r.out


def test_non_invoice_xml_named_explicitly_still_fails(lintvoice, write):
    r = lintvoice("check", write("build.xml", "<project name='x'/>"))
    assert r.code == 2
    assert "not a CII or UBL invoice (root element 'project')" in r.out


def test_skipped_files_are_listed_in_json(lintvoice, write, tmp_path):
    import json

    write("repo/build.xml", "<project/>")
    write("repo/ok.xml", invoices.xml())
    data = json.loads(lintvoice("check", "--format", "json", tmp_path / "repo").out)
    assert data["exit_code"] == 0
    assert [p.endswith("build.xml") for p in data["skipped"]] == [True]


def test_a_directory_with_only_non_invoices(lintvoice, write, tmp_path):
    write("repo/pom.xml", "<project/>")
    r = lintvoice("check", tmp_path / "repo")
    assert r.code == 2
    assert "only 1 XML file(s) that are not invoices" in r.err


def test_malformed_xml_in_a_directory_still_fails(lintvoice, write, tmp_path):
    write("repo/broken.xml", "<Invoice><oops></Invoice>")
    write("repo/ok.xml", invoices.xml())
    assert lintvoice("check", tmp_path / "repo").code == 2
