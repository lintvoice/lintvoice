"""The command line itself: version, help, usage errors, rule packs."""

import subprocess
import sys

from lintvoice import __version__, rulepacks


def test_version(lintvoice):
    r = lintvoice("--version")
    assert r.code == 0
    assert f"lintvoice {__version__}" in r.out


def test_module_entry_point_runs():
    r = subprocess.run([sys.executable, "-m", "lintvoice", "--version"], capture_output=True, text=True)
    assert r.returncode == 0
    assert __version__ in r.stdout


def test_help_lists_the_commands(lintvoice):
    r = lintvoice("--help")
    assert r.code == 0
    assert "check" in r.out and "rules" in r.out


def test_check_needs_a_path(lintvoice):
    r = lintvoice("check")
    assert r.code == 2
    assert "paths" in r.err


def test_unknown_rule_set_is_a_usage_error(lintvoice, write):
    r = lintvoice("check", "--rules", "en16931,peppol", write("a.xml", "<a/>"))
    assert r.code == 2
    assert "unknown rule set peppol" in r.err


def test_rules_list_shows_versions_licences_and_sources(lintvoice):
    r = lintvoice("rules", "list")
    assert r.code == 0
    assert "en16931     1.3.17    installed" in r.out
    assert "france-rfe  1.4.0.04  installed" in r.out
    assert "EUPL-1.2" in r.out
    assert "https://github.com/fnfempe/France_RFE/tree/97ba0f3" in r.out


def test_check_without_rule_packs_says_how_to_install(lintvoice, write, tmp_path):
    r = lintvoice("check", "--rules-dir", tmp_path / "empty", write("a.xml", "<a/>"))
    assert r.code == 3
    assert "Run: lintvoice rules install" in r.err


def test_rules_install_is_idempotent(lintvoice):
    r = lintvoice("rules", "install")
    assert r.code == 0
    assert r.out.count("already installed") == len(rulepacks.PACKS)


def test_install_rejects_a_download_that_is_not_the_pinned_version(tmp_path):
    pack = rulepacks.PACKS["en16931"]
    try:
        rulepacks.install(pack, tmp_path, fetch=lambda url: b"not the release")
    except ValueError as e:
        assert "checksum mismatch" in str(e)
    else:
        raise AssertionError("a tampered download was installed")
    assert not rulepacks.is_installed(pack, tmp_path)


def test_france_rfe_pack_holds_no_afnor_documents(rules):
    """France_RFE's Z.notes_&_docs/ and Z.example/ hold AFNOR documents: they must never be installed."""
    folder = rulepacks.pack_path(rulepacks.PACKS["france-rfe"], rules)
    names = [str(p.relative_to(folder)) for p in folder.rglob("*")]
    assert names, "pack is empty"
    assert not [n for n in names if "/Z." in n or n.startswith("Z.")]
    assert not [n for n in names if n.lower().endswith((".pdf", ".xlsx"))]


def test_install_writes_a_manifest(rules):
    for pack in rulepacks.PACKS.values():
        manifest = rulepacks.pack_path(pack, rules) / ".installed.json"
        assert pack.version in manifest.read_text()
