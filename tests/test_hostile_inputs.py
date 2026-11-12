"""Hostile or heavy files: each one ends in a clean verdict or a clean "unreadable" (exit 2),
never a traceback, within a time and memory budget. Run in a real process, so that native code is measured too."""

import io
import subprocess
import sys
import time
import zlib

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, StreamObject

import invoices

try:
    import resource  # not on Windows: the time budget still applies there
except ImportError:
    resource = None

TIME_BUDGET = 60  # seconds, per file
MEMORY_BUDGET = 1024  # MiB, peak resident memory of the lintvoice process


def _xml_with_prolog(prolog, body=None):
    head, rest = invoices.xml().decode().split("?>", 1)
    return (head + "?>" + prolog + (body if body is not None else rest)).encode()


def _pdf(*attachments, encrypt=None):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    for name, data in attachments:
        writer.add_attachment(name, data)
    if encrypt:
        writer.encrypt(encrypt)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _flate_bomb():
    """A factur-x.xml attachment whose stream inflates to 1 GiB."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_pdf(("factur-x.xml", b"<a/>")))))
    bomb = zlib.compress(b"<a>" + b" " * (1 << 30), 9)
    for ref in writer._objects:
        obj = ref.get_object() if ref is not None else None
        if isinstance(obj, StreamObject) and obj.get("/Type") == "/EmbeddedFile":
            obj._data = bomb
            obj[NameObject("/Filter")] = NameObject("/FlateDecode")
            obj[NameObject("/Length")] = NumberObject(len(bomb))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _cases():
    pdf = invoices.facturx_pdf(invoices.xml())
    laughs = (
        '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        + "".join(f'<!ENTITY {n} "{("&" + p + ";") * 10}">' for p, n in zip("abcdefg", "bcdefgh", strict=True))
        + "]>"
    )
    big = invoices.french(lines=[(f"Article {i}", "1", "10.00", "S", "20") for i in range(2000)])
    return {
        "deep-nesting.xml": (_xml_with_prolog("", "<a>" * 100_000 + "</a>" * 100_000), 2),
        "billion-laughs.xml": (_xml_with_prolog(laughs), 2),
        "2000-lines.xml": (invoices.xml(big), 0),
        "truncated.pdf": (pdf[: len(pdf) // 2], 2),
        "no-trailer.pdf": (pdf.split(b"trailer")[0], 2),
        "garbage.pdf": (b"%PDF-1.7\n" + bytes(range(256)) * 800, 2),
        "300-attachments.pdf": (
            _pdf(*[(f"other-{i}.xml", b"<x/>") for i in range(300)], ("factur-x.xml", invoices.xml())),
            0,
        ),
        "encrypted.pdf": (_pdf(("factur-x.xml", invoices.xml()), encrypt="secret"), 2),
        "flate-bomb.pdf": (_flate_bomb(), 2),
    }


CASES = _cases()


@pytest.mark.parametrize("name", list(CASES))
def test_hostile_file_gets_a_clean_answer_within_budget(write, name):
    data, expected = CASES[name]
    path = write(name, data)
    start = time.monotonic()
    p = subprocess.run(
        [sys.executable, "-m", "lintvoice", "check", str(path)], capture_output=True, text=True, timeout=TIME_BUDGET
    )
    elapsed = time.monotonic() - start
    assert p.returncode == expected, (p.returncode, p.stdout[-500:], p.stderr[-500:])
    assert "Traceback" not in p.stdout + p.stderr
    assert elapsed < TIME_BUDGET
    if resource is not None:
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        peak_mib = peak / (1 << 20) if sys.platform == "darwin" else peak / 1024  # bytes on macOS, KiB on Linux
        assert peak_mib < MEMORY_BUDGET, f"{peak_mib:.0f} MiB (the largest child process so far)"
