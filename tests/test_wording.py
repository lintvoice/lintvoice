"""Wording: lintvoice checks e-invoices against the official rules, it never certifies them; public terms are "valid" and
"invalid" examples. Every string literal in the source is a potential user-facing text (CLI messages, report notes), so all are checked;
official identifiers (urn:..., such as urn:cen.eu:en16931:2017#compliant#...) are not our words and are skipped."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "lintvoice"
FORBIDDEN = re.compile(r"certif|complian|conform|\bfake|fixture|fausses? factures?", re.I)


def _strings():
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.startswith("urn:"):
                yield path.relative_to(SRC.parent), node.lineno, node.value


def test_no_certification_claim_or_forbidden_term_in_any_string():
    found = [f"{path}:{line}: {text[:80]!r}" for path, line, text in _strings() if FORBIDDEN.search(text)]
    assert not found, found


def test_the_check_sees_a_claim():
    assert FORBIDDEN.search("This invoice is certified compliant") and FORBIDDEN.search("une facture conforme")
    assert not FORBIDDEN.search("lintvoice helps check e-invoices")
