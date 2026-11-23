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
REFERENCE = re.compile(r"\{(BT-\d+)\}")


def _find(node, path):
    """The elements at the end of a path of local names ('|' for alternatives, '[@attr=value]' as a filter); a last
    step '@name' gives that attribute's values instead."""
    nodes = [node]
    for step in path.split("/"):
        if step.startswith("@"):
            return [n.get(step[1:]) for n in nodes if n.get(step[1:]) is not None]
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


def _first(node, paths, terms=None):
    """What the first path that finds something finds: a term's path, or its list of paths. A '{BT-n}' in a path
    stands for that header term's value, read before (terms): the VAT total in the invoice's currency (BT-110) and in
    the VAT accounting currency (BT-111) are told apart that way."""
    for path in [paths] if isinstance(paths, str) else paths:
        if terms is not None:
            path = REFERENCE.sub(lambda m: terms.get(m.group(1), ""), path)
        if found := _find(node, path):
            return found
    return []


def _text(nodes):
    if not nodes:
        return ""
    return (nodes[0] if isinstance(nodes[0], str) else "".join(nodes[0].itertext())).strip()


def _terms(node, spec, syntax):
    """A group item's terms; a term with no path for this syntax is not read."""
    return {bt: _text(_first(node, paths[syntax])) for bt, paths in spec.items() if syntax in paths}


def _split(node, spec, allowance_terms, charge_terms, syntax):
    """The allowances and the charges under a node (the invoice, or a line), told apart by their charge indicator."""
    allowances, charges = [], []
    for item in _find(node, spec[syntax]["path"]):
        if _text(_find(item, spec[syntax]["charge"])).lower() == "true":
            charges.append(_terms(item, SPEC[charge_terms], syntax))
        else:
            allowances.append(_terms(item, SPEC[allowance_terms], syntax))
    return allowances, charges


def _line(line, syntax):
    """A line's terms, with its allowances, charges and item attributes."""
    allowances, charges = _split(
        line, SPEC["line_allowances_charges"], "line_allowance_terms", "line_charge_terms", syntax
    )
    attributes = [_terms(a, SPEC["line_attribute_terms"], syntax) for a in _find(line, SPEC["line_attributes"][syntax])]
    return {
        **_terms(line, SPEC["line_terms"], syntax),
        "allowances": allowances,
        "charges": charges,
        "attributes": attributes,
    }


def read(xml, syntax):
    """The invoice's values: header terms (an empty string when absent), the identifier schemes given, each line's
    terms with its allowances, charges and item attributes, the notes with their subject code, the VAT breakdown, the
    document level allowances and charges, and the additional supporting documents."""
    root = etree.fromstring(xml.lstrip(b"\xef\xbb\xbf"), PARSER)
    terms, schemes = {}, {}
    header = {bt: paths[syntax] for bt, paths in SPEC["header"].items() if syntax in paths}
    # the terms whose paths refer to another term's value come second, once that value is read
    for bt in sorted(header, key=lambda bt: bool(REFERENCE.search(json.dumps(header[bt])))):
        found = _first(root, header[bt], terms)
        terms[bt] = _text(found)
        if found and not isinstance(found[0], str) and found[0].get("schemeID"):
            schemes[bt] = found[0].get("schemeID")
    terms = {bt: terms[bt] for bt in header}
    lines = [_line(line, syntax) for line in _find(root, SPEC["lines"][syntax])]
    breakdown = [_terms(tax, SPEC["vat_breakdown_terms"], syntax) for tax in _find(root, SPEC["vat_breakdown"][syntax])]
    allowances, charges = _split(root, SPEC["allowances_charges"], "allowance_terms", "charge_terms", syntax)
    documents = [_terms(d, SPEC["document_terms"], syntax) for d in _find(root, SPEC["documents"][syntax])]
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
        "documents": documents,
    }


def _decimal(value):
    if not NUMBER.match(value or ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def number(value, places):
    """A decimal written with at least two places, more when the invoice's amounts carry more: '1230.00'. A value
    that rounds to zero is written without a sign ('0.00', never '-0.00'), as the check page writes it."""
    text = f"{value:.{max(2, places)}f}"
    return text[1:] if text.startswith("-") and Decimal(text) == 0 else text


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


def _deviation(calc, spec):
    """How far an item's stated amount is from its expected amount, as its rule measures it: without the signs when
    the rule compares absolute values ('absolute': BR-CO-17 and BR-S-09 accept a VAT amount whose sign differs from
    its base's, so a breakdown with only its sign flipped passes them)."""
    stated, expected = Decimal(calc["stated"]), Decimal(calc["expected"])
    if spec.get("absolute"):
        stated, expected = abs(stated), abs(expected)
    return abs(stated - expected)


def computation(rule, values):
    """The computation a totals or VAT rule makes, with the invoice's values: parts [sign, value, BT], expected,
    stated, and the gap (stated - expected); for a rule checked per VAT breakdown, the breakdown furthest from its
    expected amount as the rule measures it (the one the rule rejects), as `group`. None when the rule has no
    computation or a value is not a number."""
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
    return max(calcs, key=lambda c: _deviation(c, spec), default=None)
