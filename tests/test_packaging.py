"""The wheel holds our code only: no rule files, no third-party code."""

import shutil
import subprocess
import zipfile

import pytest


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    if not shutil.which("uv"):
        pytest.skip("uv is needed to build the wheel")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--wheel", "-q", "-o", str(out)], check=True)
    (path,) = out.glob("lintvoice-*.whl")
    return zipfile.ZipFile(path)


def test_wheel_holds_only_our_code(wheel):
    names = wheel.namelist()
    code = [n for n in names if n.startswith("lintvoice/")]
    assert "lintvoice/cli.py" in code and "lintvoice/engine.py" in code
    assert not [n for n in names if n.lower().endswith((".xsl", ".xslt", ".sch", ".xsd", ".pdf", ".xlsx"))]
    assert not [n for n in names if not n.startswith(("lintvoice/", "lintvoice-"))]


def test_wheel_metadata(wheel):
    meta = wheel.read(next(n for n in wheel.namelist() if n.endswith("METADATA"))).decode()
    assert "License-Expression: MIT" in meta
    assert "Requires-Python: >=3.10" in meta
    assert "Requires-Dist: saxonche" in meta
    assert any(n.endswith("licenses/LICENSE") for n in wheel.namelist())


def test_wheel_declares_the_command(wheel):
    entry = wheel.read(next(n for n in wheel.namelist() if n.endswith("entry_points.txt"))).decode()
    assert "lintvoice = lintvoice.cli:main" in entry
