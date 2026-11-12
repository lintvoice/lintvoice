"""Choose the rule sets for a document and run them in-process (XSD with lxml, Schematron with saxonche)."""

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from . import rulepacks

SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
FRANCE_RFE = Path("FNFE_RFE_INVOICE")
# Factur-X profiles whose XSD and profile rules France_RFE 1.4.0.04 ships.
FACTURX_DIRS = {"basicwl": "BASICWL", "en16931": "EN16931", "extended": "EXTENDED"}
# Profiles that carry a full EN 16931 invoice (MINIMUM and BASIC WL do not).
NOT_FULL_INVOICE = ("minimum", "basicwl")

RULE_CHOICES = ("en16931", "factur-x", "br-fr")


@dataclass(frozen=True)
class RuleSet:
    id: str  # "xsd", "en16931", "factur-x", "br-fr", "extended-ctc-fr"
    name: str  # shown to the user
    pack: str  # key of rulepacks.PACKS
    path: str  # inside the pack folder
    kind: str = "schematron"


@dataclass
class Finding:
    rule: str
    severity: str  # "error" or "warning"
    message: str
    location: str
    rule_set: str


@dataclass
class NotRun:
    """A rule set that stopped with an error of its own on this file: the check is incomplete."""

    rule_set: str
    name: str
    error: str


class RuleSetFailed(Exception):
    pass


@dataclass
class Result:
    document: object
    rule_sets: list
    findings: list
    notes: list = field(default_factory=list)
    not_run: list = field(default_factory=list)

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "warning"]


def _fx_profile_label(profile):
    return {"basicwl": "BASIC WL", "en16931": "EN 16931", "extended": "EXTENDED"}[profile]


def select(doc, rules="auto"):
    """Return (rule sets, notes) for this document. rules: "auto" or a set of RULE_CHOICES."""
    notes = []
    auto = rules == "auto"
    wanted = set(RULE_CHOICES) if auto else set(rules)
    french = doc.seller_country == "FR"
    if auto:
        if french:
            notes.append("BR-FR rules applied: the seller's country is FR.")
        else:
            wanted.discard("br-fr")
            if doc.profile != "minimum":
                country = doc.seller_country or "not given"
                notes.append(
                    f"BR-FR rules not applied: the seller's country is {country} "
                    "(--rules en16931,factur-x,br-fr applies them)."
                )
    sets = []
    full = doc.profile not in NOT_FULL_INVOICE
    if doc.syntax == "CII":
        fx_dir = FACTURX_DIRS.get(doc.profile)
        # A bare XML with BT-24 = urn:cen.eu:en16931:2017 may be plain CII: Factur-X rules only when asked.
        facturx = doc.facturx or (not auto and "factur-x" in wanted)
        if facturx and fx_dir:
            sets.append(
                RuleSet(
                    "xsd",
                    f"Factur-X 1.09.2 {_fx_profile_label(doc.profile)} schema",
                    "france-rfe",
                    str(FRANCE_RFE / f"Factur-X/{fx_dir}/1xsd/Factur-X_{fx_dir}.xsd"),
                    "xsd",
                )
            )
        else:
            sets.append(
                RuleSet(
                    "xsd",
                    "CII D22B schema",
                    "france-rfe",
                    str(FRANCE_RFE / "CII/1xsd-CII_D22B_uncoupled/CrossIndustryInvoice_100pD22B.xsd"),
                    "xsd",
                )
            )
        if full and "en16931" in wanted:
            sets.append(RuleSet("en16931", "EN 16931 1.3.17 (CII)", "en16931", "cii/xslt/EN16931-CII-validation.xslt"))
        if facturx and "factur-x" in wanted:
            if fx_dir:
                sets.append(
                    RuleSet(
                        "factur-x",
                        f"Factur-X 1.09.2 {_fx_profile_label(doc.profile)}",
                        "france-rfe",
                        str(FRANCE_RFE / f"Factur-X/{fx_dir}/2xslt/FACTUR-X_{fx_dir}.xslt"),
                    )
                )
            elif doc.profile in ("minimum", "basic"):
                notes.append(
                    f"No Factur-X {doc.profile.upper()} profile rules in France_RFE 1.4.0.04: profile rules skipped."
                )
        if "br-fr" in wanted and doc.profile != "minimum":
            sets.append(
                RuleSet(
                    "br-fr",
                    "BR-FR 1.4.0.04 (CII)",
                    "france-rfe",
                    str(FRANCE_RFE / "CII/EN16931/2xslt/BR-FR-Flux2-Schematron-CII.xslt"),
                )
            )
            if doc.profile == "extended-ctc-fr":
                sets.append(
                    RuleSet(
                        "extended-ctc-fr",
                        "EXTENDED-CTC-FR 1.4.0.04 (CII)",
                        "france-rfe",
                        str(FRANCE_RFE / "CII/EXTENDED-CTC-FR/2xslt/EXTENDED-CTC-FR-CII.xslt"),
                    )
                )
    else:
        root = etree.QName(etree.fromstring(doc.xml)).localname
        sets.append(
            RuleSet(
                "xsd",
                "UBL 2.1 schema",
                "france-rfe",
                str(FRANCE_RFE / f"UBL/1xsd_UBL2.1/maindoc/UBL-{root}-2.1.xsd"),
                "xsd",
            )
        )
        if "en16931" in wanted:
            sets.append(RuleSet("en16931", "EN 16931 1.3.17 (UBL)", "en16931", "ubl/xslt/EN16931-UBL-validation.xslt"))
        if "br-fr" in wanted:
            sets.append(
                RuleSet(
                    "br-fr",
                    "BR-FR 1.4.0.04 (UBL)",
                    "france-rfe",
                    str(FRANCE_RFE / "UBL/EN16931/2xslt/BR-FR-Flux2-Schematron-UBL.xslt"),
                )
            )
    if doc.profile in ("xrechnung", "peppol"):
        name = {"xrechnung": "XRechnung", "peppol": "Peppol BIS"}[doc.profile]
        notes.append(f"{name} rules are not in this version: only EN 16931 was checked.")
    if doc.profile == "unknown":
        notes.append(f"Unknown specification identifier (BT-24) {doc.specification_id!r}: EN 16931 rules only.")
    return sets, notes


_STEP = re.compile(r"(?:\*:|Q\{[^}]*\})([A-Za-z0-9_.-]+)(?:\[namespace-uri\(\)='[^']*'\])?(?:\[(\d+)\])?")


def pretty_location(location):
    """'/*:Invoice[namespace-uri()='…'][1]/*:Line[…][2]' -> '/Invoice/Line[2]'."""
    if not location:
        return ""
    steps = []
    for part in location.split("/")[1:]:
        m = _STEP.fullmatch(part)
        if m:
            name, index = m.groups()
            steps.append(f"{name}[{index}]" if index and index != "1" else name)
        else:
            steps.append(part)
    return "/" + "/".join(steps)


def _clean(text):
    """Drop the rule id the message repeats: '[BR-02]-…' (EN 16931) or 'BR-FR-05/BT-22 : …' (BR-FR)."""
    text = " ".join(text.split())
    text = re.sub(r"^\[[A-Z0-9_-]+\]\s*-\s*", "", text)
    return re.sub(r"^BR-FR[A-Z]*-[0-9A-Z]+/([A-Z0-9-]+)\s*:\s*", r"\1: ", text)


@contextmanager
def _native_stderr_silenced():
    """SaxonC prints its own trace of a dynamic error straight to file descriptor 2, bypassing Python.
    The error is reported cleanly instead (NotRun), so that trace is dropped."""
    saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


class Engine:
    """Compiles each rule set once per process and reuses it."""

    def __init__(self, root):
        from saxonche import PySaxonProcessor

        self.root = Path(root)
        self.proc = PySaxonProcessor(license=False)
        self._xslt = {}
        self._xsd = {}

    def _file(self, rule_set):
        return rulepacks.pack_path(rulepacks.PACKS[rule_set.pack], self.root) / rule_set.path

    def _run_xsd(self, rule_set, xml):
        path = self._file(rule_set)
        if path not in self._xsd:
            self._xsd[path] = etree.XMLSchema(etree.parse(str(path)))
        schema = self._xsd[path]
        if schema.validate(etree.fromstring(xml)):
            return []
        return [
            Finding("XSD", "error", re.sub(r"\{[^}]*\}", "", e.message), f"line {e.line}", rule_set.id)
            for e in schema.error_log
        ]

    def _run_schematron(self, rule_set, xml):
        path = self._file(rule_set)
        if path not in self._xslt:
            self._xslt[path] = self.proc.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(path))
        from saxonche import PySaxonApiError

        node = self.proc.parse_xml(xml_text=xml.decode("utf-8"))
        try:
            with _native_stderr_silenced():
                out = self._xslt[path].transform_to_string(xdm_node=node)
        except PySaxonApiError as e:  # a dynamic error inside the official rule file (e.g. XPTY0004)
            raise RuleSetFailed(" ".join(str(e).split())) from e
        svrl = etree.fromstring(out.encode("utf-8"))
        findings = []
        for f in svrl.xpath("//svrl:failed-assert | //svrl:successful-report", namespaces=SVRL):
            flag = (f.get("flag") or "fatal").lower()
            findings.append(
                Finding(
                    rule=f.get("id") or f"{rule_set.id}:no-id",
                    severity="error" if flag in ("fatal", "error") else "warning",
                    message=_clean(f.xpath("string(svrl:text)", namespaces=SVRL)),
                    location=pretty_location(f.get("location", "")),
                    rule_set=rule_set.id,
                )
            )
        return findings

    def check(self, doc, rules="auto"):
        rule_sets, notes = select(doc, rules)
        rulepacks.require(self.root, {rs.pack for rs in rule_sets})
        xml = doc.xml.lstrip(b"\xef\xbb\xbf")
        findings, seen, not_run = [], {}, []
        for rs in rule_sets:
            run = self._run_xsd if rs.kind == "xsd" else self._run_schematron
            try:
                found = run(rs, xml)
            except RuleSetFailed as e:
                not_run.append(NotRun(rs.id, rs.name, str(e)))
                continue
            for f in found:
                # The Factur-X profile rules repeat many EN 16931 rules, often from another context, so at
                # another location: once an earlier rule set has reported a rule id, the later sets' findings
                # for that id are dropped. Within one rule set, every failure is kept.
                if seen.setdefault(f.rule, rs.id) == rs.id:
                    findings.append(f)
        return Result(doc, rule_sets, findings, notes, not_run)
