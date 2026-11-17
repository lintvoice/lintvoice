"""One business rule's answer on an invoice (lintvoice check --rule ID): it fails, it finds no error, it does not apply
(and why), or it could not be checked.

The answer reads an ordinary check: the full official rule sets run, then the answer looks at that rule only. Whether
a rule applies comes from the official files themselves: each compiled rule file reports the rule contexts that fired
on the invoice (svrl:fired-rule), and each assert sits in one rule context, read from the same file (contexts()).
"""

import html
import re
from dataclasses import dataclass

from .engine import FACTURX_DIRS, FACTURX_RULE_FILES, FRANCE_RFE


@dataclass(frozen=True)
class RuleFile:
    """A compiled Schematron file that select() may run: its rule set, its syntax, where it is."""

    rule_set: str
    syntax: str
    pack: str
    path: str


# Every compiled Schematron file select() can choose (the same paths), so that a rule's answer knows the files that
# hold it, including those not run on this invoice.
RULE_FILES = (
    RuleFile("en16931", "CII", "en16931", "cii/xslt/EN16931-CII-validation.xslt"),
    RuleFile("en16931", "UBL", "en16931", "ubl/xslt/EN16931-UBL-validation.xslt"),
    *(
        RuleFile(
            "factur-x",
            "CII",
            "france-rfe",
            str(FRANCE_RFE / f"Factur-X/{d}/2xslt/FACTUR-X_{FACTURX_RULE_FILES[p]}.xslt"),
        )
        for p, d in FACTURX_DIRS.items()
    ),
    RuleFile("br-fr", "CII", "france-rfe", str(FRANCE_RFE / "CII/EN16931/2xslt/BR-FR-Flux2-Schematron-CII.xslt")),
    RuleFile(
        "extended-ctc-fr", "CII", "france-rfe", str(FRANCE_RFE / "CII/EXTENDED-CTC-FR/2xslt/EXTENDED-CTC-FR-CII.xslt")
    ),
    RuleFile("br-fr", "UBL", "france-rfe", str(FRANCE_RFE / "UBL/EN16931/2xslt/BR-FR-Flux2-Schematron-UBL.xslt")),
)

ANSWERS = ("fails", "warns", "no-error", "does-not-apply", "not-checked")
# Why a rule does not apply: the French rules are not run (the seller is not in France); the rule exists only for the
# other syntax (CII or UBL); only for another invoice profile; or its rule context is not in this invoice.
REASONS = ("seller-not-in-france", "other-syntax", "other-profile", "not-in-invoice")

_TEMPLATE = re.compile(r"<xsl:template\b[^>]*>(.*?)</xsl:template>", re.S)
_FIRED = re.compile(r'<svrl:fired-rule\b[^>]*\bcontext="([^"]*)"')
_ASSERT_ID = re.compile(
    r'<svrl:(?:failed-assert|successful-report)\b[^>]*\bid="([^"]+)"|<xsl:attribute name="id">\s*([^<]+?)\s*</xsl:attribute>'
)


def contexts(xslt):
    """For one compiled Schematron file, the rule context of each assert id, as the result names it when that rule
    fires (XML entities and doubled braces undone): {assert id: [context, ...]}."""
    found = {}
    for template in _TEMPLATE.finditer(xslt):
        body = template.group(1)
        fired = _FIRED.search(body)
        if not fired:
            continue
        context = html.unescape(fired.group(1)).replace("{{", "{").replace("}}", "}")
        for a in _ASSERT_ID.finditer(body):
            found.setdefault(a.group(1) or a.group(2), set()).add(context)
    return {rule: sorted(c) for rule, c in sorted(found.items())}


def belongs(assert_id, rule):
    """Whether an official assert id is reported under a rule: the id itself, a variant per business term
    (BR-FR-23_BT-34) or a named variant (BR-FR-32-GLOBALID)."""
    return (
        assert_id == rule
        or assert_id.startswith(rule + "_")
        or re.fullmatch(re.escape(rule) + r"-[A-Za-z]+(?:_.*)?", assert_id) is not None
    )


class UnknownRule(Exception):
    pass


@dataclass(frozen=True)
class Answer:
    rule: str
    answer: str  # one of ANSWERS
    reason: str | None = None  # one of REASONS, for "does-not-apply"


def answer(eng, result, rule):
    """The answer for one rule on a checked invoice (an engine.Result)."""
    holders = [f for f in RULE_FILES if any(belongs(a, rule) for a in eng.contexts(f.pack, f.path))]
    if not holders:
        raise UnknownRule(f"no rule {rule} in the official rule files")
    own = [f for f in result.findings if belongs(f.rule, rule)]
    if own:
        return Answer(rule, "fails" if any(f.severity == "error" for f in own) else "warns")
    ran = [f for f in holders if f.path in result.fired]
    if not ran and any(n.path in {f.path for f in holders} for n in result.not_run):
        return Answer(rule, "not-checked")
    for f in ran:
        wanted = {c for a, cs in eng.contexts(f.pack, f.path).items() if belongs(a, rule) for c in cs}
        if wanted & result.fired[f.path]:
            return Answer(rule, "no-error")
    if ran:
        return Answer(rule, "does-not-apply", "not-in-invoice")
    # none of the files that hold the rule ran on this invoice
    if any(n.startswith("BR-FR rules not applied") for n in result.notes) and all(
        f.rule_set in ("br-fr", "extended-ctc-fr") for f in holders
    ):
        return Answer(rule, "does-not-apply", "seller-not-in-france")
    if result.document.syntax not in {f.syntax for f in holders}:
        return Answer(rule, "does-not-apply", "other-syntax")
    return Answer(rule, "does-not-apply", "other-profile")
