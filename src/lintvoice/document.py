"""Read an invoice file and tell what it is: syntax (CII or UBL), profile, seller country."""

import io
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from pypdf import PdfReader

CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
UBL_INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
UBL_CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS = {
    "rsm": CII_NS,
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# Embedded file names used by Factur-X, ZUGFeRD and XRechnung PDFs, in order of preference.
EMBEDDED_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "ZUGFeRD-invoice.xml", "xrechnung.xml")

# Specification identifier (BT-24) -> profile.
PROFILES = {
    "urn:factur-x.eu:1p0:minimum": "minimum",
    "urn:factur-x.eu:1p0:basicwl": "basicwl",
    "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic": "basic",
    "urn:cen.eu:en16931:2017": "en16931",
    "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended": "extended",
    "urn:cen.eu:en16931:2017#conformant#urn.cpro.gouv.fr:1p0:extended-ctc-fr": "extended-ctc-fr",
    "urn:ferd:CrossIndustryDocument:invoice:1p0:comfort": "zugferd-comfort",
}
PROFILE_PREFIXES = {
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung": "xrechnung",
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0": "peppol",
}
PROFILE_LABELS = {
    "minimum": "Factur-X MINIMUM",
    "basicwl": "Factur-X BASIC WL",
    "basic": "Factur-X BASIC",
    "en16931": "EN 16931",
    "extended": "Factur-X EXTENDED",
    "extended-ctc-fr": "Factur-X EXTENDED-CTC-FR",
    "zugferd-comfort": "ZUGFeRD 2.0 COMFORT",
    "xrechnung": "XRechnung",
    "peppol": "Peppol BIS Billing 3.0",
    "unknown": "unknown profile",
}


class NotAnInvoice(Exception):
    pass


class NotAnInvoiceXml(NotAnInvoice):
    """Well-formed XML, but not a CII or UBL invoice."""


@dataclass
class Document:
    path: Path
    xml: bytes
    source: str  # "XML" or "PDF (factur-x.xml)"
    syntax: str  # "CII" or "UBL"
    profile: str  # a key of PROFILE_LABELS
    specification_id: str
    seller_country: str | None

    @property
    def from_pdf(self):
        return self.source.startswith("PDF")

    @property
    def facturx(self):
        """A Factur-X document: a PDF with embedded CII, or a CII whose BT-24 is a Factur-X profile id."""
        if self.profile in ("xrechnung", "peppol"):
            return False  # a PDF can carry an XRechnung (ZUGFeRD-XRechnung): label it by its profile
        return self.syntax == "CII" and (
            self.from_pdf or "factur-x" in self.specification_id or self.profile == "extended-ctc-fr"
        )

    @property
    def label(self):
        profile = PROFILE_LABELS[self.profile]
        if self.facturx and not profile.startswith("Factur-X"):
            profile = f"Factur-X {profile}"
        return f"{profile} · {self.syntax} · {self.source}"


def _xml_from_pdf(data):
    # pypdf decompresses an attachment only when it is read, so reading it can fail too: a damaged stream, or a
    # decompression bomb stopped by pypdf's limit (LimitReachedError). Both make the PDF unreadable, not a verdict.
    try:
        attachments = PdfReader(io.BytesIO(data)).attachments
        names = [n for n in EMBEDDED_NAMES if n in attachments] or [
            n for n in attachments if n.lower().endswith(".xml")
        ]
        if names:
            return attachments[names[0]][0], names[0]
    except Exception as e:
        raise NotAnInvoice(f"cannot read this PDF ({e})") from e
    raise NotAnInvoice("this PDF has no embedded invoice XML (not a Factur-X, ZUGFeRD or XRechnung PDF)")


def _profile(spec_id):
    if spec_id in PROFILES:
        return PROFILES[spec_id]
    for prefix, profile in PROFILE_PREFIXES.items():
        if spec_id.startswith(prefix):
            return profile
    return "unknown"


# Invoices (CII, UBL) never declare a DOCTYPE. One could point the XML tools at local files or at a URL (Saxon
# fetches an external DTD), so a file that declares one is refused before any rule runs. No entity is resolved,
# no DTD is loaded, nothing is fetched while parsing.
PARSER = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
DOCTYPE_REFUSED = (
    "declares a DOCTYPE: e-invoices never do, and lintvoice refuses it so that no file can make it "
    "read other files or reach the network"
)


def load(path):
    path = Path(path)
    data = path.read_bytes()
    source = "XML"
    if data[:5] == b"%PDF-":
        data, name = _xml_from_pdf(data)
        source = f"PDF ({name})"
    try:
        root = etree.fromstring(data.lstrip(b"\xef\xbb\xbf"), PARSER)
    except etree.XMLSyntaxError as e:
        raise NotAnInvoice(f"not well-formed XML ({e})") from e
    info = root.getroottree().docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        raise NotAnInvoice(DOCTYPE_REFUSED)
    ns = etree.QName(root).namespace
    if ns == CII_NS:
        syntax = "CII"
        spec = root.xpath(
            "string(rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID)", namespaces=NS
        )
        country = root.xpath(
            "string(//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID)",
            namespaces=NS,
        )
    elif ns in (UBL_INVOICE_NS, UBL_CREDIT_NOTE_NS):
        syntax = "UBL"
        spec = root.xpath("string(cbc:CustomizationID)", namespaces=NS)
        country = root.xpath(
            "string(cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode)",
            namespaces=NS,
        )
    else:
        raise NotAnInvoiceXml(f"not a CII or UBL invoice (root element {etree.QName(root).localname!r})")
    spec = spec.strip()
    return Document(
        path=path,
        xml=data,
        source=source,
        syntax=syntax,
        profile=_profile(spec),
        specification_id=spec,
        seller_country=country.strip() or None,
    )
