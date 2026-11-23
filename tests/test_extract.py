"""lintvoice extract: the invoice XML attached to a PDF, written to a file the user can open."""

import subprocess
import sys

import invoices
import pytest

from lintvoice.document import EMBEDDED_NAMES


def test_help_lists_extract(lintvoice):
    r = lintvoice("--help")
    assert "extract" in r.out
    r = lintvoice("extract", "--help")
    assert "Write the invoice XML attached to a Factur-X, ZUGFeRD or XRechnung PDF." in r.out


@pytest.mark.parametrize("name", EMBEDDED_NAMES)
def test_writes_the_attached_xml_next_to_the_pdf(lintvoice, write, name):
    xml = invoices.xml()
    pdf = write("invoice.pdf", invoices.facturx_pdf(xml, name))
    r = lintvoice("extract", pdf)
    assert r.code == 0
    assert (pdf.parent / "invoice.xml").read_bytes() == xml  # the attachment's own bytes, untouched
    assert r.out.strip() == f"Wrote {pdf.parent / 'invoice.xml'} ({name} from {pdf})."


def test_a_pdf_without_xml_keeps_the_check_message(lintvoice, write):
    pdf = write("plain.pdf", invoices.facturx_pdf(None))
    r = lintvoice("extract", pdf)
    assert r.code == 2
    assert "this PDF has no embedded invoice XML (not a Factur-X, ZUGFeRD or XRechnung PDF)" in r.err
    assert not (pdf.parent / "plain.xml").exists()


def test_a_file_that_is_not_a_pdf(lintvoice, write):
    r = lintvoice("extract", write("invoice.xml", invoices.xml()))
    assert r.code == 2
    assert "not a PDF: there is no attached XML to extract" in r.err


def test_a_corrupt_pdf_and_a_missing_file(lintvoice, write, tmp_path):
    r = lintvoice("extract", write("bad.pdf", b"%PDF-1.7\nnot really a pdf"), tmp_path / "missing.pdf")
    assert r.code == 2
    assert "cannot read this PDF" in r.err and "missing.pdf: file not found" in r.err


def test_several_pdfs_each_next_to_its_own(lintvoice, write):
    a = write("a/one.pdf", invoices.facturx_pdf(invoices.xml()))
    b = write("b/two.pdf", invoices.facturx_pdf(invoices.xml(invoices.french(number="F2026-0043"))))
    r = lintvoice("extract", a, b)
    assert r.code == 0
    assert (a.parent / "one.xml").read_bytes() == invoices.xml()
    assert b"F2026-0043" in (b.parent / "two.xml").read_bytes()


def test_output_names_the_file(lintvoice, write, tmp_path):
    pdf = write("invoice.pdf", invoices.facturx_pdf(invoices.xml()))
    r = lintvoice("extract", pdf, "-o", tmp_path / "chosen.xml")
    assert r.code == 0
    assert (tmp_path / "chosen.xml").read_bytes() == invoices.xml()


def test_a_folder_that_does_not_exist_is_said_not_raised(lintvoice, write, tmp_path):
    pdf = write("invoice.pdf", invoices.facturx_pdf(invoices.xml()))
    r = lintvoice("extract", pdf, "-o", tmp_path / "missing" / "chosen.xml")
    assert r.code == 2
    assert "cannot write" in r.err and "No such file or directory" in r.err


def test_output_takes_one_pdf(lintvoice, write):
    pdf = write("invoice.pdf", invoices.facturx_pdf(invoices.xml()))
    r = lintvoice("extract", pdf, pdf, "-o", "x.xml")
    assert r.code == 2
    assert "-o takes one PDF" in r.err


def test_output_dash_writes_the_bytes_to_standard_output(write):
    xml = invoices.xml()
    pdf = write("invoice.pdf", invoices.facturx_pdf(xml))
    r = subprocess.run([sys.executable, "-m", "lintvoice", "extract", str(pdf), "-o", "-"], capture_output=True)
    assert r.returncode == 0
    assert r.stdout == xml
    assert not (pdf.parent / "invoice.xml").exists()


def test_a_different_file_is_kept_unless_forced(lintvoice, write):
    pdf = write("invoice.pdf", invoices.facturx_pdf(invoices.xml()))
    mine = write("invoice.xml", b"<notes>mine</notes>")
    r = lintvoice("extract", pdf)
    assert r.code == 2
    assert "exists with other content" in r.err and "--force" in r.err
    assert mine.read_bytes() == b"<notes>mine</notes>"
    r = lintvoice("extract", pdf, "--force")
    assert r.code == 0
    assert mine.read_bytes() == invoices.xml()


def test_the_same_file_again_is_not_an_error(lintvoice, write):
    pdf = write("invoice.pdf", invoices.facturx_pdf(invoices.xml()))
    assert lintvoice("extract", pdf).code == 0
    assert lintvoice("extract", pdf).code == 0
