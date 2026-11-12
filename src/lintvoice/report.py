"""Turn results into a readable verdict (grouped by rule) or JSON."""

import json
import textwrap
from dataclasses import dataclass

from . import __version__

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


def text_result(result, style, verbose=False, width=100):
    doc = result.document
    mark = style.red("✗") if result.errors else style.yellow("!") if result.not_run else style.green("✓")
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
    lines.append(f"  {_summary(result)}")
    indent = " " * 4
    for g in group(result.findings):
        sev = style.red("error  ") if g.severity == "error" else style.yellow("warning")
        lines.append("")
        lines.append(f"  {sev} {style.bold(g.rule)}  ×{g.count}")
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
                    }
                    for g in group(r.findings)
                ],
            }
        )
    for path, message in failures:
        files.append({"path": str(path), "status": "unreadable", "error": message})
    return json.dumps(
        {"lintvoice": __version__, "exit_code": exit_code, "files": files, "skipped": [str(s) for s in skipped]},
        indent=2,
        ensure_ascii=False,
    )
