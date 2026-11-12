"""Every official EN 16931 1.3.17 example (CII and UBL) reads cleanly and passes."""

import json

import pytest
from conftest import RULES

from lintvoice import rulepacks


def _examples():
    folder = rulepacks.pack_path(rulepacks.PACKS["en16931"], RULES)
    return sorted(
        p for syntax in ("cii", "ubl") for p in (folder / syntax / "examples").iterdir() if p.suffix.lower() == ".xml"
    )


@pytest.mark.corpus
@pytest.mark.parametrize("path", _examples(), ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_official_example_passes(lintvoice, path):
    r = lintvoice("check", "--format", "json", path)
    report = json.loads(r.out)["files"][0]
    assert report["status"] == "ok", json.dumps(report["findings"], indent=1, ensure_ascii=False)
    assert r.code == 0


@pytest.mark.corpus
def test_whole_corpus_in_one_run(lintvoice):
    paths = _examples()
    r = lintvoice("check", *paths)
    assert r.code == 0, r
    assert f"{len(paths)} files checked: 0 with errors, {len(paths)} without." in r.out
