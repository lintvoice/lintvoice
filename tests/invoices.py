"""Test fixtures: build a Factur-X EN 16931 (CII) invoice from a dict of settings, as XML or as a PDF.

Totals and VAT breakdowns are computed from the lines and allowances, so a
mutation that changes a price or a rate stays arithmetically consistent.
All identifiers are fictitious but pass their check digits (Luhn, IBAN, VAT key). The SIRENs start
with 0, a range with no company in the SIRENE directory (recherche-entreprises.api.gouv.fr, checked
2026-11-05). The IBAN has a real bank code (30004) and an all-zero branch and account.
"""

import copy
import io
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree
from pypdf import PdfWriter

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
CENT = Decimal("0.01")


def luhn_ok(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def luhn_complete(prefix):
    """Append the digit that makes prefix pass the Luhn check."""
    return next(prefix + str(d) for d in range(10) if luhn_ok(prefix + str(d)))


def vat_fr(siren):
    return f"FR{(12 + 3 * (int(siren) % 97)) % 97:02d}{siren}"


def iban_fr(bank, branch, account):
    rib_key = 97 - (89 * int(bank) + 15 * int(branch) + 3 * int(account)) % 97
    bban = f"{bank}{branch}{account}{rib_key:02d}"
    check = 98 - int(bban + "152700") % 97  # "FR00" moved to the end, F=15 R=27
    return f"FR{check:02d}{bban}", bban


SELLER_SIREN = luhn_complete("01234567")
SELLER_SIRET = luhn_complete(SELLER_SIREN + "0001")
BUYER_SIREN = luhn_complete("07654321")
BUYER_SIRET = luhn_complete(BUYER_SIREN + "0002")
IBAN, RIB = iban_fr("30004", "00000", "00000000000")

# A French invoice that passes EN 16931, the Factur-X EN 16931 profile and BR-FR.
FRENCH = {
    "profile": "urn:cen.eu:en16931:2017",
    "billing_frame": "S1",  # BT-23, BR-FR-08 list
    "number": "F2026-0042",  # BT-1
    "type_code": "380",  # BT-3
    "issue_date": "20261020",  # BT-2
    "issue_date_format": "102",
    "notes": [
        ("PMT", "Indemnité forfaitaire pour frais de recouvrement : 40 EUR."),
        ("PMD", "Pénalités de retard : trois fois le taux d'intérêt légal."),
        ("AAB", "Pas d'escompte pour paiement anticipé."),
    ],
    "buyer_reference": "FACTURES_PUBLIQUES",  # BT-10, Chorus Pro code service
    "seller": {
        "name": "Atelier Exemple SAS",
        "global_id": (SELLER_SIRET, "0009"),  # BT-29
        "legal_id": (SELLER_SIREN, "0002"),  # BT-30
        "address": ("75011", "10 rue de l'Exemple", "Paris", "FR"),
        "endpoint": (SELLER_SIREN, "0225"),  # BT-34
        "vat": vat_fr(SELLER_SIREN),  # BT-31
    },
    "buyer": {
        "name": "Commune d'Exemple",
        "global_id": (BUYER_SIRET, "0009"),  # BT-46
        "legal_id": (BUYER_SIREN, "0002"),  # BT-47
        "address": ("69001", "1 place de la Mairie", "Lyon", "FR"),
        "endpoint": (BUYER_SIREN, "0225"),  # BT-49
        "department": None,  # Chorus Pro "nom du service" (OCA puts it here)
    },
    "invoicee": None,  # Chorus Pro "valideur" (InvoiceeTradeParty)
    "order_reference": "1234567890",  # BT-13, Chorus Pro numéro d'engagement
    "delivery_date": "20261015",
    "currency": "EUR",  # BT-5
    "tax_currency": None,  # BT-6
    "payment_code": "30",  # BT-81
    "iban": IBAN,  # BT-84
    "proprietary_account": None,  # BT-84 when not an IBAN
    "bic": "BNPAFRPPXXX",  # BT-86
    "due_date": "20261119",
    "due_date_type": "5",  # BT-8
    "tax_type": "VAT",
    "lines": [
        # name, quantity, unit price, VAT category, VAT rate
        ("Atelier de formation", "2", "450.00", "S", "20"),
        ("Support de cours", "10", "12.50", "S", "20"),
    ],
    "allowances": [],  # (amount, reason code, reason, category, rate)
}


def amt(value):
    return f"{Decimal(value).quantize(CENT, ROUND_HALF_UP)}"


def el(parent, tag, text=None, **attrs):
    prefix, name = tag.split(":")
    node = etree.SubElement(parent, f"{{{NS[prefix]}}}{name}", {k.replace("_", ""): v for k, v in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


def date(parent, tag, value, fmt="102", ns="udt"):
    el(el(parent, tag), f"{ns}:DateTimeString", value, format=fmt)


def party(parent, tag, p):
    node = el(parent, tag)
    if p.get("global_id"):
        el(node, "ram:GlobalID", p["global_id"][0], schemeID=p["global_id"][1])
    el(node, "ram:Name", p["name"])
    if p.get("legal_id"):
        el(el(node, "ram:SpecifiedLegalOrganization"), "ram:ID", p["legal_id"][0], schemeID=p["legal_id"][1])
    if p.get("department"):
        el(el(node, "ram:DefinedTradeContact"), "ram:DepartmentName", p["department"])
    addr = el(node, "ram:PostalTradeAddress")
    postcode, line, city, country = p["address"]
    el(addr, "ram:PostcodeCode", postcode)
    el(addr, "ram:LineOne", line)
    el(addr, "ram:CityName", city)
    el(addr, "ram:CountryID", country)
    if p.get("endpoint"):
        el(el(node, "ram:URIUniversalCommunication"), "ram:URIID", p["endpoint"][0], schemeID=p["endpoint"][1])
    if p.get("vat"):
        el(el(node, "ram:SpecifiedTaxRegistration"), "ram:ID", p["vat"], schemeID="VA")
    return node


def build(c):
    """Return the invoice as an lxml element tree root."""
    root = etree.Element(f"{{{NS['rsm']}}}CrossIndustryInvoice", nsmap=NS)
    ctx = el(root, "rsm:ExchangedDocumentContext")
    if c["billing_frame"] is not None:
        el(el(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter"), "ram:ID", c["billing_frame"])
    el(el(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", c["profile"])

    doc = el(root, "rsm:ExchangedDocument")
    el(doc, "ram:ID", c["number"])
    el(doc, "ram:TypeCode", c["type_code"])
    date(doc, "ram:IssueDateTime", c["issue_date"], c["issue_date_format"])
    for subject, content in c["notes"]:
        note = el(doc, "ram:IncludedNote")
        el(note, "ram:Content", content)
        el(note, "ram:SubjectCode", subject)

    tx = el(root, "rsm:SupplyChainTradeTransaction")
    groups = OrderedDict()  # (category, rate) -> basis
    line_total = Decimal(0)
    for i, (name, qty, price, cat, rate) in enumerate(c["lines"], 1):
        net = (Decimal(qty) * Decimal(price)).quantize(CENT, ROUND_HALF_UP)
        line_total += net
        groups[(cat, rate)] = groups.get((cat, rate), Decimal(0)) + net
        item = el(tx, "ram:IncludedSupplyChainTradeLineItem")
        el(el(item, "ram:AssociatedDocumentLineDocument"), "ram:LineID", i)
        el(el(item, "ram:SpecifiedTradeProduct"), "ram:Name", name)
        el(el(el(item, "ram:SpecifiedLineTradeAgreement"), "ram:NetPriceProductTradePrice"), "ram:ChargeAmount", price)
        el(el(item, "ram:SpecifiedLineTradeDelivery"), "ram:BilledQuantity", qty, unitCode="C62")
        settle = el(item, "ram:SpecifiedLineTradeSettlement")
        tax = el(settle, "ram:ApplicableTradeTax")
        el(tax, "ram:TypeCode", c["tax_type"])
        el(tax, "ram:CategoryCode", cat)
        el(tax, "ram:RateApplicablePercent", rate)
        el(el(settle, "ram:SpecifiedTradeSettlementLineMonetarySummation"), "ram:LineTotalAmount", amt(net))

    agree = el(tx, "ram:ApplicableHeaderTradeAgreement")
    if c["buyer_reference"] is not None:
        el(agree, "ram:BuyerReference", c["buyer_reference"])
    party(agree, "ram:SellerTradeParty", c["seller"])
    party(agree, "ram:BuyerTradeParty", c["buyer"])
    if c["order_reference"] is not None:
        el(el(agree, "ram:BuyerOrderReferencedDocument"), "ram:IssuerAssignedID", c["order_reference"])

    delivery = el(tx, "ram:ApplicableHeaderTradeDelivery")
    event = el(delivery, "ram:ActualDeliverySupplyChainEvent")
    date(event, "ram:OccurrenceDateTime", c["delivery_date"])

    settle = el(tx, "ram:ApplicableHeaderTradeSettlement")
    if c["tax_currency"]:
        el(settle, "ram:TaxCurrencyCode", c["tax_currency"][0])
    el(settle, "ram:InvoiceCurrencyCode", c["currency"])
    if c["invoicee"]:
        party(settle, "ram:InvoiceeTradeParty", c["invoicee"])
    means = el(settle, "ram:SpecifiedTradeSettlementPaymentMeans")
    el(means, "ram:TypeCode", c["payment_code"])
    if c["iban"] or c["proprietary_account"]:
        account = el(means, "ram:PayeePartyCreditorFinancialAccount")
        if c["iban"]:
            el(account, "ram:IBANID", c["iban"])
        if c["proprietary_account"]:
            el(account, "ram:ProprietaryID", c["proprietary_account"])
    if c["bic"]:
        el(el(means, "ram:PayeeSpecifiedCreditorFinancialInstitution"), "ram:BICID", c["bic"])

    allowance_total = Decimal(0)
    for amount, _code, _reason, cat, rate in c["allowances"]:
        allowance_total += Decimal(amount)
        groups[(cat, rate)] = groups.get((cat, rate), Decimal(0)) - Decimal(amount)
    tax_total = Decimal(0)
    for (cat, rate), basis in groups.items():
        vat = (basis * Decimal(rate) / 100).quantize(CENT, ROUND_HALF_UP)
        tax_total += vat
        tax = el(settle, "ram:ApplicableTradeTax")
        el(tax, "ram:CalculatedAmount", amt(vat))
        el(tax, "ram:TypeCode", c["tax_type"])
        if cat in ("E", "AE", "K", "G", "O"):
            el(tax, "ram:ExemptionReason", "Exonération de TVA")
        el(tax, "ram:BasisAmount", amt(basis))
        el(tax, "ram:CategoryCode", cat)
        if c["due_date_type"]:
            el(tax, "ram:DueDateTypeCode", c["due_date_type"])
        el(tax, "ram:RateApplicablePercent", rate)
    for amount, code, reason, cat, rate in c["allowances"]:
        ac = el(settle, "ram:SpecifiedTradeAllowanceCharge")
        el(el(ac, "ram:ChargeIndicator"), "udt:Indicator", "false")
        el(ac, "ram:ActualAmount", amt(amount))
        el(ac, "ram:ReasonCode", code)
        el(ac, "ram:Reason", reason)
        tax = el(ac, "ram:CategoryTradeTax")
        el(tax, "ram:TypeCode", c["tax_type"])
        el(tax, "ram:CategoryCode", cat)
        el(tax, "ram:RateApplicablePercent", rate)
    terms = el(settle, "ram:SpecifiedTradePaymentTerms")
    el(terms, "ram:Description", "Paiement à 30 jours par virement.")
    date(terms, "ram:DueDateDateTime", c["due_date"])

    basis_total = line_total - allowance_total
    grand = basis_total + tax_total
    sums = el(settle, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    el(sums, "ram:LineTotalAmount", amt(line_total))
    if c["allowances"]:
        el(sums, "ram:AllowanceTotalAmount", amt(allowance_total))
    el(sums, "ram:TaxBasisTotalAmount", amt(basis_total))
    el(sums, "ram:TaxTotalAmount", amt(tax_total), currencyID=c["currency"])
    if c["tax_currency"]:
        code, factor = c["tax_currency"]
        el(sums, "ram:TaxTotalAmount", amt(tax_total * Decimal(factor)), currencyID=code)
    el(sums, "ram:GrandTotalAmount", amt(grand))
    el(sums, "ram:DuePayableAmount", amt(grand))
    return root


def to_bytes(root):
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def french(**changes):
    """A copy of FRENCH with top-level keys replaced, e.g. french(number="X1")."""
    conf = copy.deepcopy(FRENCH)
    conf.update(changes)
    return conf


def xml(conf=None, edit=None):
    """The invoice as bytes; edit(root) may change the tree before serialisation."""
    root = build(conf or FRENCH)
    if edit:
        edit(root)
    return to_bytes(root)


def facturx_pdf(xml_bytes, name="factur-x.xml"):
    """A one-page PDF with the XML embedded, as Factur-X does (not PDF/A-3: lintvoice does not check PDF/A)."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    if xml_bytes is not None:
        writer.add_attachment(name, xml_bytes)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def remove(xpath):
    """An edit that removes every node matching xpath."""

    def edit(root):
        for node in root.xpath(xpath, namespaces=NS):
            node.getparent().remove(node)

    return edit
