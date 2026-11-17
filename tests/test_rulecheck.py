"""lintvoice check --rule: one business rule's answer on an invoice (fails, no error found, does not apply and why,
could not be checked), read from an ordinary check and the rule contexts the official files report as fired."""

import json
from decimal import Decimal

import invoices
from invoices import NS
from test_rule_set_failure import _ship_to_with_two_sirets

from lintvoice import rulecheck, rulepacks


def _answers(lintvoice, path, *rules):
    r = lintvoice("check", "--format", "json", *[a for rule in rules for a in ("--rule", rule)], path)
    entry = json.loads(r.out)["files"][0]
    return r.code, {a["rule"]: (a["answer"], a["reason"]) for a in entry.get("rules", [])}


def _total_off_by_one(root):
    grand = root.find(".//ram:GrandTotalAmount", NS)
    grand.text = str(Decimal(grand.text) + 1)
    due = root.find(".//ram:DuePayableAmount", NS)
    due.text = grand.text


def test_contexts_are_read_as_the_result_writes_them():
    # an assert id as an attribute or as xsl:attribute; the context with its XML entities and doubled braces
    xslt = """
    <xsl:template match="a" priority="2" mode="M7"><svrl:fired-rule context="//a[. = &apos;E&apos;][{{1}}]" />
      <xsl:choose><xsl:when test="t"/><xsl:otherwise><svrl:failed-assert test="t">
        <xsl:attribute name="id">BR-E-10</xsl:attribute></svrl:failed-assert></xsl:otherwise></xsl:choose></xsl:template>
    <xsl:template match="b" priority="1" mode="M8"><svrl:fired-rule context="/r"/>
      <svrl:failed-assert id="BR-FR-21_BT-49" test="t"/></xsl:template>
    <xsl:template match="text()" mode="M8"/>
    """
    assert rulecheck.contexts(xslt) == {"BR-E-10": ["//a[. = 'E'][{1}]"], "BR-FR-21_BT-49": ["/r"]}


def test_a_rule_covers_its_variants_only():
    assert rulecheck.belongs("BR-FR-23_BT-34", "BR-FR-23")
    assert rulecheck.belongs("BR-FR-32-GLOBALID", "BR-FR-32")
    assert not rulecheck.belongs("BR-CO-10", "BR-CO-1")
    assert not rulecheck.belongs("BR-FR-CO-05", "BR-FR")


def test_every_rule_file_is_in_the_packs(rules):
    for f in rulecheck.RULE_FILES:
        assert (rulepacks.pack_path(rulepacks.PACKS[f.pack], rules) / f.path).is_file(), f


def test_a_rule_that_fails(lintvoice, write):
    code, answers = _answers(lintvoice, write("total.xml", invoices.xml(edit=_total_off_by_one)), "BR-CO-15")
    assert code == 1
    assert answers == {"BR-CO-15": ("fails", None)}


def test_no_error_and_does_not_apply_on_a_valid_invoice(lintvoice, write):
    code, answers = _answers(lintvoice, write("valid.xml", invoices.xml()), "BR-CO-15", "br-co-21", "BR-CO-25")
    assert code == 0
    assert answers == {
        "BR-CO-15": ("no-error", None),
        "BR-CO-21": ("does-not-apply", "not-in-invoice"),  # no document-level allowance
        "BR-CO-25": ("does-not-apply", "other-profile"),  # an EXTENDED-CTC-FR rule only
    }


def test_why_a_rule_does_not_apply_to_an_official_ubl_invoice(lintvoice, official):
    code, answers = _answers(lintvoice, official("ubl", "ubl-tc434-example1.xml"), "BR-FR-10", "BR-AF-01")
    assert code == 0
    assert answers == {
        "BR-FR-10": ("does-not-apply", "seller-not-in-france"),
        "BR-AF-01": ("does-not-apply", "other-syntax"),  # in the CII rule files only
    }


def test_a_rule_whose_rule_set_stopped_was_not_checked(lintvoice, write):
    code, answers = _answers(lintvoice, write("ship-to.xml", invoices.xml(edit=_ship_to_with_two_sirets)), "BR-FR-09")
    assert code == 4
    assert answers == {"BR-FR-09": ("not-checked", None)}


def test_an_unknown_rule_is_refused(lintvoice, write):
    r = lintvoice("check", "--rule", "BR-XX-99", write("valid.xml", invoices.xml()))
    assert r.code == 2
    assert "no rule BR-XX-99 in the official rule files" in r.err


def test_text_output_answers_first_then_one_line_on_the_rest(lintvoice, write):
    r = lintvoice(
        "check", "--color", "never", "--rule", "BR-CO-21", write("total.xml", invoices.xml(edit=_total_off_by_one))
    )
    assert r.code == 0  # the rule asked does not fail
    assert "BR-CO-21: does not apply (the invoice does not hold what the rule checks)" in r.out
    assert "error   BR-CO-15" not in r.out  # the other rules' findings stay out
    assert "Other rules: errors in 1 rule (run without --rule to see them)." in r.out


def test_json_without_rule_has_no_answers(lintvoice, write):
    r = lintvoice("check", "--format", "json", write("valid.xml", invoices.xml()))
    assert "rules" not in json.loads(r.out)["files"][0]
