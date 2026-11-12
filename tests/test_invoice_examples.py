"""lintvoice against invoice-examples (target fr): the valid example passes, each invalid example fails
exactly the rules its manifest declares. invoice-examples checks its files with the official rules alone,
so this is an independent check of lintvoice's rule selection and reporting."""

import io
import json

import pytest

invoice_examples = pytest.importorskip("invoice_examples")
from invoice_examples import cli as examples_cli  # noqa: E402 (after importorskip)


@pytest.fixture(scope="module")
def examples(tmp_path_factory):
    out = tmp_path_factory.mktemp("examples")
    assert examples_cli.main(["generate", "--target", "fr", "--out", str(out)], out=io.StringIO()) == 0
    folder = out / "fr"
    return folder, json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["examples"]


def _errors(lintvoice, path, *rules):
    r = lintvoice("check", "--format", "json", *rules, path)
    report = json.loads(r.out)["files"][0]
    return {g["rule"] for g in report["findings"] if g["severity"] == "error"}


def test_every_example_gives_the_declared_verdict_as_xml(lintvoice, examples):
    folder, entries = examples
    wrong = {}
    for e in entries:
        got = _errors(lintvoice, folder / e["files"]["xml"], "--rules", "en16931,factur-x,br-fr")
        if got != set(e["fires"]):
            wrong[e["id"]] = (sorted(e["fires"]), sorted(got))
    assert not wrong, wrong


def test_every_example_gives_the_declared_verdict_as_pdf(lintvoice, examples):
    """PDFs go through automatic rule selection: Factur-X, and BR-FR because the seller is in France."""
    folder, entries = examples
    wrong = {}
    for e in entries:
        got = _errors(lintvoice, folder / e["files"]["pdf"])
        if got != set(e["fires"]):
            wrong[e["id"]] = (sorted(e["fires"]), sorted(got))
    assert not wrong, wrong
