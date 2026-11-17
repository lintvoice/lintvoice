"""Turn results into a readable verdict (grouped by rule) or JSON."""

import json
import textwrap
from dataclasses import dataclass

from . import __version__, explain, rulecheck

# Schema errors come last: a missing element often shows up as a confusing "element not expected".
LAYER_ORDER = {"en16931": 0, "factur-x": 1, "br-fr": 2, "extended-ctc-fr": 3, "xsd": 4}
SEVERITY_ORDER = {"error": 0, "warning": 1}


@dataclass
class Group:
    rule: str
    severity: str
    rule_set: str
    messages: dict  # message -> list of locations, in order of appearance

    @property
    def count(self):
        return sum(len(v) for v in self.messages.values())


def group(findings):
    groups = {}
    for f in findings:
        g = groups.setdefault((f.rule, f.severity), Group(f.rule, f.severity, f.rule_set, {}))
        g.messages.setdefault(f.message, []).append(f.location)
    return sorted(groups.values(), key=lambda g: (SEVERITY_ORDER[g.severity], LAYER_ORDER.get(g.rule_set, 9), g.rule))


class Style:
    def __init__(self, color):
        self.color = color

    def _c(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def red(self, t):
        return self._c("31", t)

    def green(self, t):
        return self._c("32", t)

    def yellow(self, t):
        return self._c("33", t)

    def bold(self, t):
        return self._c("1", t)

    def dim(self, t):
        return self._c("2", t)


def _summary(result):
    errors, warnings = len(result.errors), len(result.warnings)
    rules = len({f.rule for f in result.errors})
    if not errors and not warnings:
        return "No errors in the rules that ran." if result.not_run else "No errors."
    parts = []
    if errors:
        parts.append(f"{errors} error{'s' * (errors != 1)} in {rules} rule{'s' * (rules != 1)}")
    if warnings:
        parts.append(f"{warnings} warning{'s' * (warnings != 1)}")
    return ", ".join(parts) + "."


ANSWER_TEXT = {
    "fails": "fails",
    "warns": "gives a warning",
    "no-error": "no error found",
    "does-not-apply": "does not apply",
    "not-checked": "could not be checked: its rule set stopped with an error",
}
REASON_TEXT = {
    "seller-not-in-france": "the seller is not in France, so the French rules do not run",
    "other-syntax": "the rule exists only for the other syntax (CII or UBL)",
    "other-profile": "the rule is for another invoice profile",
    "not-in-invoice": "the invoice does not hold what the rule checks",
}


def _answer_line(a):
    return f"{a.rule}: {ANSWER_TEXT[a.answer]}" + (f" ({REASON_TEXT[a.reason]})" if a.reason else "")


def _mine(result, rule_id):
    return any(rulecheck.belongs(rule_id, a.rule) for a in result.answers)


def _values(result):
    """The invoice's values, read once per result; None when they cannot be read."""
    try:
        return explain.read(result.document.xml, result.document.syntax)
    except Exception:  # the values are an aid: a file the rules could check never fails for them
        return None


def computation_line(calc):
    """'1025.00 (BT-109) + 205.00 (BT-110) = 1230.00; the invoice states 1231.00 (BT-112), a gap of 1.00'."""
    if len(calc["parts"]) > 6:
        terms = f"sum of {len(calc['parts'])} {calc['parts'][0][2]}"
    else:
        terms = " ".join(
            f"{'' if i == 0 and sign == '+' else sign + ' '}{v} ({bt})" for i, (sign, v, bt) in enumerate(calc["parts"])
        )
    return (
        f"{terms} = {calc['expected']}; the invoice states {calc['stated']} ({calc['result']}), a gap of {calc['gap']}"
    )


def text_result(result, style, verbose=False, width=100):
    doc = result.document
    values = _values(result)
    asked = result.answers
    listed = [f for f in result.findings if _mine(result, f.rule)] if asked else result.findings
    if asked:  # the rules asked first; the rest in one line
        answers = {a.answer for a in asked}
        bad, unsure = "fails" in answers, "not-checked" in answers
    else:
        bad, unsure = bool(result.errors), bool(result.not_run)
    mark = style.red("✗") if bad else style.yellow("!") if unsure else style.green("✓")
    lines = [f"{mark} {style.bold(str(doc.path))}", f"  {doc.label}"]
    lines += [f"  {style.dim(n)}" for n in result.notes]
    for n in result.not_run:
        lines += textwrap.wrap(
            f"{n.name} could not run on this file: its official rule file stopped with an error, "
            "so this check is incomplete. The other rule sets ran.",
            width=width,
            initial_indent=f"  {style.yellow('!')} ",
            subsequent_indent="    ",
        )
        shown = n.error if verbose or len(n.error) <= 220 else n.error[:217] + "…"
        lines += textwrap.wrap(f"Error: {shown}", width=width, initial_indent="    ", subsequent_indent="    ")
    if asked:
        lines += [f"  {_answer_line(a)}" for a in asked]
    else:
        lines.append(f"  {_summary(result)}")
    indent = " " * 4
    for g in group(listed):
        sev = style.red("error  ") if g.severity == "error" else style.yellow("warning")
        lines.append("")
        lines.append(f"  {sev} {style.bold(g.rule)}  ×{g.count}")
        calc = explain.computation(g.rule, values) if values else None
        if calc:
            lines += textwrap.wrap(computation_line(calc), width=width, initial_indent=indent, subsequent_indent=indent)
        for message, locations in g.messages.items():
            shown = message if verbose or len(message) <= 220 else message[:217] + "…"
            prefix = f"{indent}×{len(locations)} " if len(g.messages) > 1 else indent
            lines += textwrap.wrap(shown, width=width, initial_indent=prefix, subsequent_indent=" " * len(prefix)) or [
                prefix
            ]
            locs = [loc for loc in locations if loc]
            if locs:
                more = "" if verbose or len(locs) == 1 else style.dim(f" (+{len(locs) - 1} more)")
                for loc in locs if verbose else locs[:1]:
                    lines.append(f"{' ' * len(prefix)}{style.dim('at ' + loc)}{more if loc == locs[0] else ''}")
    if asked:
        others = {f.rule for f in result.errors if not _mine(result, f.rule)}
        lines.append("")
        lines.append(
            style.dim(
                f"  Other rules: errors in {len(others)} rule{'s' * (len(others) != 1)} (run without --rule to see them)."
                if others
                else "  Other rules: no errors."
            )
        )
    return "\n".join(lines)


def text_error(path, message, style):
    return f"{style.red('!')} {style.bold(str(path))}\n  {message}"


def header(rule_sets, style):
    names = ", ".join(dict.fromkeys(rs.name for rs in rule_sets if rs.kind != "xsd"))
    return style.dim(f"lintvoice {__version__} · {names}") if names else style.dim(f"lintvoice {__version__}")


def footer(results, failures, style):
    total = len(results) + len(failures)
    bad = sum(1 for r in results if r.errors)
    incomplete = sum(1 for r in results if r.not_run and not r.errors)
    parts = [f"{total} file{'s' * (total != 1)} checked", f"{bad} with errors"]
    if incomplete:
        parts.append(f"{incomplete} incomplete")
    parts.append(f"{len(results) - bad - incomplete} without")
    if failures:
        parts.append(f"{len(failures)} unreadable")
    return style.bold(": ".join([parts[0], ", ".join(parts[1:])]) + ".")


def json_report(results, failures, exit_code, skipped=()):
    files = []
    for r in results:
        d = r.document
        values = _values(r)
        files.append(
            {
                "path": str(d.path),
                "status": "errors" if r.errors else "incomplete" if r.not_run else "ok",
                "document": {
                    "syntax": d.syntax,
                    "profile": d.profile,
                    "specification_id": d.specification_id,
                    "source": d.source,
                    "seller_country": d.seller_country,
                },
                "rule_sets": [{"id": rs.id, "name": rs.name} for rs in r.rule_sets],
                "notes": r.notes,
                "not_run": [{"rule_set": n.rule_set, "name": n.name, "error": n.error} for n in r.not_run],
                "summary": {
                    "errors": len(r.errors),
                    "warnings": len(r.warnings),
                    "rules_failed": len({f.rule for f in r.errors}),
                },
                "findings": [
                    {
                        "rule": g.rule,
                        "severity": g.severity,
                        "rule_set": g.rule_set,
                        "count": g.count,
                        "messages": [{"message": m, "locations": locs} for m, locs in g.messages.items()],
                        **({"computation": c} if values and (c := explain.computation(g.rule, values)) else {}),
                    }
                    for g in group(r.findings)
                ],
                # what the invoice says (business terms, lines, notes): to show an error with the invoice's values
                "values": values,
                # with --rule: each rule asked, its answer and, when it does not apply, why
                **({"rules": [vars(a) for a in r.answers]} if r.answers else {}),
            }
        )
    for path, message in failures:
        files.append({"path": str(path), "status": "unreadable", "error": message})
    return json.dumps(
        {"lintvoice": __version__, "exit_code": exit_code, "files": files, "skipped": [str(s) for s in skipped]},
        indent=2,
        ensure_ascii=False,
    )
