"""Rule pack installation checks what it downloads: the bytes when they are stable, the
files when the archive is generated on the fly (GitHub archives), and that no entry escapes the pack folder."""

import io
import zipfile
from pathlib import Path

import pytest

from lintvoice import rulepacks

ROOT = Path(__file__).parent.parent


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def _pack(content_sha256):
    d = rulepacks.Download(
        "https://example.org/pack.zip", None, keep=("rules/",), strip_top=True, content_sha256=content_sha256
    )
    return rulepacks.Pack("test", "test pack", "1", "https://example.org", "MIT", (d,))


GOOD = {"top/rules/a.sch": b"<schema/>", "top/rules/b.xslt": b"<xsl/>", "top/notes/afnor.pdf": b"never kept"}


def test_the_pinned_files_install(tmp_path):
    files = {"rules/a.sch": b"<schema/>", "rules/b.xslt": b"<xsl/>"}
    pack = _pack(rulepacks.content_digest(files))
    assert rulepacks.install(pack, tmp_path, fetch=lambda url: _zip(GOOD)) == 2
    assert (tmp_path / "test-1/rules/a.sch").read_bytes() == b"<schema/>"
    assert not (tmp_path / "test-1/notes").exists()


def test_a_changed_file_is_refused_and_nothing_is_installed(tmp_path):
    pack = _pack(rulepacks.content_digest({"rules/a.sch": b"<schema/>", "rules/b.xslt": b"<xsl/>"}))
    tampered = {**GOOD, "top/rules/b.xslt": b"<xsl>evil</xsl>"}
    with pytest.raises(ValueError, match="content mismatch"):
        rulepacks.install(pack, tmp_path, fetch=lambda url: _zip(tampered))
    assert not rulepacks.is_installed(pack, tmp_path)


def test_an_entry_outside_the_pack_folder_is_refused(tmp_path):
    with pytest.raises(ValueError, match="outside the pack folder"):
        rulepacks.install(_pack(None), tmp_path, fetch=lambda url: _zip({"top/rules/../../evil.txt": b"x"}))
    assert not (tmp_path / "evil.txt").exists()


def test_the_france_rfe_pin_matches_the_installed_files():
    """The pinned digest is the one of the pack the test suite installed (tests/conftest.py)."""
    (d,) = rulepacks.PACKS["france-rfe"].downloads
    folder = ROOT / ".rules-cache" / rulepacks.PACKS["france-rfe"].folder
    files = {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file() and p.name != ".installed.json"
    }
    assert d.content_sha256 and rulepacks.content_digest(files) == d.content_sha256
