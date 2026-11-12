# lintvoice checks your e-invoices against official rules and standards

[Lire en français](README.fr.md)

It starts with the European standard, then adds each country's own rules. It works **offline**: your invoices are never sent anywhere. Today it runs:

- **EN 16931** (the European e-invoicing standard), for CII and UBL;
- **Factur-X 1.09.2** profile rules, for Factur-X PDFs;
- **BR-FR**, the French reform rules published by FNFE-MPE (France_RFE), when the seller is in France.

lintvoice reads CII XML, UBL XML (invoices and credit notes) and Factur-X / ZUGFeRD PDFs. Results are grouped by rule (e.g. one missing VAT number shows up once, not for every faulty invoice line).

> Status: 0.1.0, the first release. Options and the JSON output may still change before 1.0.

## Quick start

```sh
uvx lintvoice rules install      # once: downloads the pinned rule packs
uvx lintvoice check invoice.pdf
uvx lintvoice check invoices/ --format json
```

Or `pip install lintvoice` (Python 3.10 or later). Each release also ships its wheel and sdist on [GitHub Releases](https://github.com/lintvoice/lintvoice/releases), if PyPI is out of reach: `pip install lintvoice-<version>-py3-none-any.whl`.

In a container, with the rule packs inside the image:

```sh
docker build -t lintvoice .      # after `uv build`, from a checkout
docker run --rm -v "$PWD:/work" lintvoice check invoices/
```

The image runs as an unprivileged user (UID 10001).

```
✗ demo.pdf
  Factur-X EN 16931 · CII · PDF (factur-x.xml)
  BR-FR rules applied: the seller's country is FR.
  7 errors in 6 rules.

  error   BR-FR-16_BT-152  ×2
    BT-152: Le taux de TVA (BT-152) doit être exprimé en pourcentage … Taux fourni : "21".
    at /CrossIndustryInvoice/SupplyChainTradeTransaction/IncludedSupplyChainTradeLineItem/… (+1 more)
```

## Rule packs: what lintvoice downloads, and why

lintvoice ships no rule files. `lintvoice rules install` downloads each pack once, from its upstream source, at a pinned version:
- **What:** the official validation artefacts: Schematron sources, the XSLT compiled from them, and the XML schemas.
- **Why:** you get the exact official rules, under their own licences. lintvoice follows the official releases instead of rewriting rules.
- **When:**
  - only when you run `lintvoice rules install`;
  - never when the package is installed or imported, and never during a check;
  - after that, every check runs offline.
- **How it is checked:**
  - over https only;
  - the EN 16931 archives against their SHA-256;
  - France_RFE, which GitHub archives on the fly, against a SHA-256 of the 207 files kept;
  - a changed file, or an archive entry outside the pack folder, stops the install.
- **Not downloaded into the packs:** France_RFE's folders that hold AFNOR documents (`Z.notes_&_docs/`, `Z.example/`) are never extracted.
- **No other network use:** a checked file cannot make lintvoice fetch anything, since a file that declares a DOCTYPE is refused.

| Pack | Version | Source | Licence |
| --- | --- | --- | --- |
| EN 16931 validation artefacts | 1.3.17 | [ConnectingEurope/eInvoicing-EN16931](https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/tag/validation-1.3.17) (SHA-256 pinned) | EUPL-1.2 |
| France_RFE (BR-FR, Factur-X 1.09.2) | 1.4.0.04 | [fnfempe/France_RFE @ 97ba0f3](https://github.com/fnfempe/France_RFE/tree/97ba0f3d4ef2abed5780e9490d5c3a2be832ab1d) (content SHA-256 pinned) | Apache-2.0 (repository), EUPL (file headers) |

Packs go to `~/.cache/lintvoice/rules` (or `$XDG_CACHE_HOME`, `$LINTVOICE_RULES_DIR`, `--rules-dir`). `lintvoice rules list` shows what is installed.

## What runs on which file

| File | Schema | Rules |
| --- | --- | --- |
| Factur-X PDF, or CII with a Factur-X profile id | Factur-X 1.09.2 (BASIC WL, EN 16931, EXTENDED) | EN 16931 (except MINIMUM, BASIC WL), Factur-X profile rules, BR-FR (except MINIMUM) |
| CII XML with `urn:cen.eu:en16931:2017` | CII D22B | EN 16931, BR-FR |
| UBL invoice or credit note | UBL 2.1 | EN 16931, BR-FR |

- **BR-FR runs when the seller's country (BT-40) is FR.** `--rules en16931,factur-x,br-fr` forces it, `--rules en16931` limits the check to EN 16931.
- **A bare CII XML gets the Factur-X profile rules only when asked** (`--rules …,factur-x`), since `urn:cen.eu:en16931:2017` is also plain CII.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No errors (warnings do not change the exit code) |
| 1 | At least one file has errors |
| 2 | A file could not be read as an invoice, or no file was found |
| 3 | Rule packs are not installed |
| 4 | No errors found, but a rule set could not run on a file: its official rule file stopped with an error. The check is incomplete, so lintvoice does not say "no errors" |

## Not checked yet

- PDF/A-3 validation of Factur-X PDFs (needs veraPDF).
- XRechnung and Peppol BIS rules: those invoices get EN 16931 only, and the report says so.
- Factur-X MINIMUM and BASIC profile rules: France_RFE 1.4.0.04 does not ship them.
- Chorus Pro's own rules for its historic channels.
- BR-FR messages are in French, as FNFE-MPE writes them.

## Development

```sh
uv sync
uv run pytest            # functional tests; the first run downloads the packs into .rules-cache/
uv run pytest -m corpus  # only the official EN 16931 examples
```

The tests drive the command line on generated invoices (`tests/invoices.py`) and on the official examples. They check that:
- checks never touch the network;
- France_RFE's AFNOR documents are never installed.

## Licence

The code is under the [MIT licence](LICENSE). The rule packs keep their own licences (table above) and are not part of this package. The Docker image bundles third-party components: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
