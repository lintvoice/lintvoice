"""What the invoice says, read from its XML, and the computation behind each totals and VAT rule: the values a person
needs to understand an error ("1025.00 + 205.00 = 1230.00, the invoice states 1231.00").

Where to read each business term (BT) in CII and UBL, and the computations, are data in terms.json. The lintvoice.com
check page reads the same file, so the command line and the page show the same values.
"""

import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from importlib.resources import files

from lxml import etree

from .document import PARSER

SPEC = json.loads(files(__package__).joinpath("terms.json").read_text(encoding="utf-8"))
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _find(node, path):
    """The elements at the end of a path of local names ('|' for alternatives, '[@attr=value]' as a filter)."""
    nodes = [node]
    for step in path.split("/"):
        names, _, condition = step.partition("[@")
        wanted = names.split("|")
        attr, _, value = condition.rstrip("]").partition("=")
        nodes = [
            child
            for n in nodes
            for child in n
            if isinstance(child.tag, str)
            and etree.QName(child).localname in wanted
            and (not attr or child.get(attr) == value)
        ]
    return nodes


def _text(nodes):
    return "".join(nodes[0].itertext()).strip() if nodes else ""


def _terms(node, spec, syntax):
    return {bt: _text(_find(node, paths[syntax])) for bt, paths in spec.items()}


def read(xml, syntax):
    """The invoice's values: header terms (an empty string when absent), the identifier schemes given, each line's
    terms, the notes with their subject code, the VAT breakdown, and the document level allowances and charges."""
    root = etree.fromstring(xml.lstrip(b"\xef\xbb\xbf"), PARSER)
    terms, schemes = {}, {}
    for bt, paths in SPEC["header"].items():
        found = _find(root, paths[syntax])
        terms[bt] = _text(found)
        if found and found[0].get("schemeID"):
            schemes[bt] = found[0].get("schemeID")
    lines = [_terms(line, SPEC["line_terms"], syntax) for line in _find(root, SPEC["lines"][syntax])]
    breakdown = [_terms(tax, SPEC["vat_breakdown_terms"], syntax) for tax in _find(root, SPEC["vat_breakdown"][syntax])]
    allowances, charges = [], []
    ac = SPEC["allowances_charges"][syntax]
    for node in _find(root, ac["path"]):
        if _text(_find(node, ac["charge"])).lower() == "true":
            charges.append(_terms(node, SPEC["charge_terms"], syntax))
        else:
            allowances.append(_terms(node, SPEC["allowance_terms"], syntax))
    notes_spec = SPEC["notes"][syntax]
    notes = []
    for note in _find(root, notes_spec["path"]):
        if syntax == "CII":
            notes.append(
                {"code": _text(_find(note, notes_spec["code"])), "text": _text(_find(note, notes_spec["text"]))}
            )
        else:
            text = "".join(note.itertext()).strip()
            m = re.match(notes_spec["code_in_text"] + r"([\s\S]*)$", text)
            notes.append({"code": m.group(1), "text": m.group(2).strip()} if m else {"code": "", "text": text})
    return {
        "syntax": syntax,
        "terms": terms,
        "schemes": schemes,
        "lines": lines,
        "notes": notes,
        "vat_breakdown": breakdown,
        "allowances": allowances,
        "charges": charges,
    }


def _decimal(value):
    if not NUMBER.match(value or ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def number(value, places):
    """A decimal written with at least two places, more when the invoice's amounts carry more: '1230.00'."""
    return f"{value:.{max(2, places)}f}"


SCOPES = {
    "each line": "lines",
    "each charge": "charges",
    "each allowance": "allowances",
    "each VAT breakdown": "vat_breakdown",
}


def _same(a, b):
    """Two values of the invoice match: as numbers when both are (a rate 20 is 20.00), else as written."""
    x, y = _decimal(a), _decimal(b)
    return x == y if x is not None and y is not None else (a or "").strip() == (b or "").strip()


def _places(numbers):
    return max([-n.as_tuple().exponent for n in numbers if n.as_tuple().exponent < 0] or [2])


def _compute(spec, values, item=None):
    """One computation, on the header terms or on one group item (a VAT breakdown): the result, or None when a
    value is not a number."""
    source = item if item is not None else values["terms"]
    parts = []
    for sign, bt, *scope in spec["parts"]:
        if scope:
            match = scope[1] if len(scope) > 1 else {}
            rows = [
                row
                for row in values.get(SCOPES[scope[0]], [])
                if all(_same(row.get(mine), (item or {}).get(theirs)) for mine, theirs in match.items())
            ]
            sources = [row.get(bt, "") for row in rows]
        else:
            sources = [source.get(bt, values["terms"].get(bt, ""))]
        parts += [[sign, v, bt] for v in sources if v]
    stated = source.get(spec["result"], "")
    numbers = [_decimal(v) for _, v, _ in parts] + [_decimal(stated)]
    if any(n is None for n in numbers):
        return None
    places = _places(numbers)
    expected = Decimal(0)
    for (sign, _, _), n in zip(parts, numbers, strict=False):
        expected = expected * n / 100 if sign == "×" else expected + (n if sign == "+" else -n)
    if "round" in spec:  # half away from zero, as the rules round the absolute value
        expected = expected.copy_abs().quantize(Decimal(1).scaleb(-spec["round"]), ROUND_HALF_UP).copy_sign(expected)
    calc = {
        "result": spec["result"],
        "parts": parts,
        "expected": number(expected, places),
        "stated": stated,
        "gap": number(numbers[-1] - expected, places),
    }
    if item is not None:
        calc["group"] = dict(item)
    return calc


def computation(rule, values):
    """The computation a totals or VAT rule makes, with the invoice's values: parts [sign, value, BT], expected,
    stated, and the gap (stated - expected); for a rule checked per VAT breakdown, the breakdown with the largest
    gap (the one that fails), as `group`. None when the rule has no computation or a value is not a number."""
    spec = SPEC["computations"].get(rule)
    if not spec:
        return None
    if "each" not in spec:
        return _compute(spec, values)
    items = [
        item
        for item in values.get(spec["each"], [])
        if all(_same(item.get(bt), v) for bt, v in spec.get("where", {}).items())
    ]
    calcs = [c for c in (_compute(spec, values, item) for item in items) if c]
    return max(calcs, key=lambda c: abs(Decimal(c["gap"])), default=None)
