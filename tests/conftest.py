"""Shared fixtures. The rule packs are installed once into .rules-cache/ (git-ignored): the first run needs
the network, later runs are offline."""

import io
import sys
from pathlib import Path

import pytest

from lintvoice import cli, rulepacks

ROOT = Path(__file__).parent.parent
RULES = ROOT / ".rules-cache"
sys.path.insert(0, str(Path(__file__).parent))  # tests/invoices.py


def pytest_configure(config):
    # Before collection: test_corpus.py lists the official examples shipped in the EN 16931 pack.
    for pack in rulepacks.PACKS.values():
        rulepacks.install(pack, RULES)


@pytest.fixture(scope="session")
def rules():
    return RULES


@pytest.fixture(autouse=True)
def rules_env(monkeypatch, rules):
    monkeypatch.setenv("LINTVOICE_RULES_DIR", str(rules))
    monkeypatch.delenv("NO_COLOR", raising=False)


class Run:
    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err

    def __repr__(self):
        return f"<exit {self.code}>\n{self.out}\n{self.err}"


@pytest.fixture
def lintvoice(capsys):
    """Run the CLI in-process: lintvoice("check", path) -> Run(code, out, err)."""

    def run(*args):
        out = io.StringIO()
        try:
            code = cli.main([str(a) for a in args], out=out)
        except SystemExit as e:  # argparse: --help, --version, usage errors
            code = e.code
        captured = capsys.readouterr()
        return Run(code, out.getvalue() + captured.out, captured.err)

    return run


@pytest.fixture
def write(tmp_path):
    """write("name.xml", data) -> path in a fresh temp folder."""

    def _write(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    return _write


@pytest.fixture
def official(rules):
    """Path to an official EN 16931 example, e.g. official("cii", "CII_example1.xml")."""

    def _official(syntax, name):
        return rulepacks.pack_path(rulepacks.PACKS["en16931"], rules) / syntax / "examples" / name

    return _official
