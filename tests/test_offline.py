"""The promise: once the rule packs are installed, checking never touches the network."""

import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import invoices


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("lintvoice tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_check_runs_offline(lintvoice, write, no_network):
    r = lintvoice(
        "check",
        write("ok.pdf", invoices.facturx_pdf(invoices.xml())),
        write("bad.xml", invoices.xml(invoices.french(notes=[]))),
    )
    assert r.code == 1, r
    assert "2 files checked: 1 with errors, 1 without." in r.out


def test_rules_list_runs_offline(lintvoice, no_network):
    assert lintvoice("rules", "list").code == 0


@pytest.fixture
def listener():
    """A local HTTP server that records every request: the network access Python's socket patch cannot see
    (SaxonC is native code)."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<!ENTITY x 'y'>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()


def _with_doctype(doctype):
    head, rest = invoices.xml().decode().split("?>", 1)
    return (head + "?>\n" + doctype + rest).encode()


@pytest.mark.parametrize(
    "doctype",
    [
        '<!DOCTYPE rsm:CrossIndustryInvoice SYSTEM "{url}/external.dtd">',
        '<!DOCTYPE rsm:CrossIndustryInvoice [<!ENTITY % p SYSTEM "{url}/parameter-entity"> %p;]>',
        '<!DOCTYPE rsm:CrossIndustryInvoice [<!ENTITY x SYSTEM "file:///etc/hosts">]>',
    ],
    ids=["external-dtd", "parameter-entity", "external-entity"],
)
def test_a_doctype_is_refused_and_nothing_is_fetched(write, listener, doctype):
    """In a real process, XML and PDF: the file is unreadable (exit 2), and the server sees no request."""
    url, hits = listener
    xml = _with_doctype(doctype.format(url=url))
    for path in (write("doctype.xml", xml), write("doctype.pdf", invoices.facturx_pdf(xml))):
        p = subprocess.run([sys.executable, "-m", "lintvoice", "check", str(path)], capture_output=True, text=True)
        assert p.returncode == 2, p
        assert hits == [], hits
