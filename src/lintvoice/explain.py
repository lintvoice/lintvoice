"""What the invoice says, read from its XML, and the computation behind each totals rule: the values a person needs
to understand an error ("1025.00 + 205.00 = 1230.00, the invoice states 1231.00").

Where to read each business term (BT) in CII and UBL, and the computations, are data in terms.json. The lintvoice.com
check page reads the same file, so the command line and the page show the same values.
"""

import json
import re
from decimal import Decimal, InvalidOperation
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


def read(xml, syntax):
    """The invoice's values: header terms (an empty string when absent), the identifier schemes given, each line's
    terms, and the notes with their subject code."""
    root = etree.fromstring(xml.lstrip(b"\xef\xbb\xbf"), PARSER)
    terms, schemes = {}, {}
    for bt, paths in SPEC["header"].items():
        found = _find(root, paths[syntax])
        terms[bt] = _text(found)
        if found and found[0].get("schemeID"):
            schemes[bt] = found[0].get("schemeID")
    lines = [
        {bt: _text(_find(line, paths[syntax])) for bt, paths in SPEC["line_terms"].items()}
        for line in _find(root, SPEC["lines"][syntax])
    ]
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
    return {"syntax": syntax, "terms": terms, "schemes": schemes, "lines": lines, "notes": notes}


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


def computation(rule, values):
    """The computation a totals rule makes, with the invoice's values: parts [sign, value, BT], expected, stated,
    and the gap (stated - expected). None when the rule has no computation or a value is not a number."""
    spec = SPEC["computations"].get(rule)
    if not spec:
        return None
    parts = []
    for sign, bt, *scope in spec["parts"]:
        sources = [line.get(bt, "") for line in values["lines"]] if scope else [values["terms"].get(bt, "")]
        parts += [[sign, v, bt] for v in sources if v]
    stated = values["terms"].get(spec["result"], "")
    numbers = [_decimal(v) for _, v, _ in parts] + [_decimal(stated)]
    if any(n is None for n in numbers):
        return None
    places = max([-n.as_tuple().exponent for n in numbers if n.as_tuple().exponent < 0] or [2])
    expected = sum((n if sign == "+" else -n for (sign, _, _), n in zip(parts, numbers, strict=False)), Decimal(0))
    return {
        "result": spec["result"],
        "parts": parts,
        "expected": number(expected, places),
        "stated": stated,
        "gap": number(numbers[-1] - expected, places),
    }
