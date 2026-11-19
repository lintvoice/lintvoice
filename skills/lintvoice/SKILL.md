---
name: lintvoice
description: Use this skill to check e-invoices against the official rules with the lintvoice command line tool, offline, and to explain any failing rule. Use it when the user wants to check or validate an e-invoice of any country (Factur-X, ZUGFeRD, XRechnung, Peppol BIS; CII or UBL XML, invoice or credit note, or a PDF that carries its XML); when an invoice was rejected with a business rule code (such as BR-FR-10, BR-CO-15 or BR-S-08) or with the message a validator or platform returned; when code that generates e-invoices needs tests against EN 16931 or a country's rules; or when the user needs valid and invalid example invoices. Use it even if the user does not name lintvoice and only pastes an error code.
license: MIT
compatibility: Needs a shell with uv, or Python 3.10 or later with pip. Network access once, to install the tool and download the official rule packs; checks then run offline.
---

# Check e-invoices with lintvoice

lintvoice is an open-source command line tool that checks e-invoices against the official rule files: the European
standard EN 16931, then each country's own rules (the French reform's BR-FR rules first). It reads CII XML, UBL XML
(invoices and credit notes) and PDFs that carry their XML (Factur-X, ZUGFeRD). It runs on the user's machine: the
invoice is never sent anywhere.

What it runs today is never written here, so that this file stays true as rules are added:

- `uvx lintvoice rules list` shows the rule sets installed, with their versions and sources;
- every report starts with the rule sets it ran and their versions, for example
  `lintvoice 0.5.0 · EN 16931 1.3.17 (CII), BR-FR 1.4.0.04 (CII)`;
- the README says which file gets which rules, and what is not checked yet:
  https://github.com/lintvoice/lintvoice#readme

## Run a check

Install the rule packs once. They are downloaded from their official sources, at pinned versions, and checked:

```sh
uvx lintvoice rules install
```

Then check a file, several files, or a folder (every `.xml` and `.pdf` inside):

```sh
uvx lintvoice check invoice.pdf
uvx lintvoice check invoices/ --format json
```

- Without uv: `pip install lintvoice`, then the same commands without `uvx`.
- By default, lintvoice picks the rule sets from the invoice itself (a country's rules when the seller is in that
  country). `--rules` chooses them by hand: `lintvoice check --help` lists the names.
- `-v` shows the full messages and every location.
- Options and the JSON output may change before version 1.0: `lintvoice check --help` shows the current ones.

When the user asks about one rule, ask lintvoice about that rule (`--rule` may be given several times):

```sh
uvx lintvoice check --rule BR-FR-10 invoice.xml
```

The answer is `fails`, `warns`, `no-error`, `does-not-apply` (with its reason), or `not-checked`. The other rules'
errors are summed up in one line. A rule that none of the installed rule files holds stops the check with "no rule …
in the official rule files": tell the user that lintvoice does not run it yet, and explain the rule from its page if
there is one (next sections).

## Read the result

| Exit code | Meaning | What to do |
| --- | --- | --- |
| 0 | No errors (warnings do not change it) | Report the warnings, if any |
| 1 | At least one file has errors | Explain each failing rule (next section) |
| 2 | A file could not be read as an invoice, no file was found, or a rule asked with `--rule` is not in the rule files | Check the path, the file's format or the rule's code |
| 3 | The rule packs are not installed | Run `uvx lintvoice rules install` |
| 4 | No errors found, but a rule set could not run on a file | Say the check is incomplete; never report it as passing |

With `--rule`, 1 means one of the rules asked fails, and 4 that one of them could not be checked.

- Errors are grouped by rule: one entry per rule, with its count (`×2`) and where it is in the file.
- An error code may carry a suffix: `BR-FR-16_BT-152` and `BR-FR-32-GLOBALID` belong to the rules `BR-FR-16` and
  `BR-FR-32`. Use the rule without the suffix for `--rule` and for its page.
- For a rule that checks an amount (totals, VAT), lintvoice shows the computation with the invoice's own values and
  the gap. Quote it: it shows which amount is off.
- Official messages keep the language their publisher wrote them in (the BR-FR messages are in French). Translate
  them when the user writes in another language.
- In JSON, each file carries `values` (the business terms read from the invoice); a failing totals or VAT rule
  carries `computation` (`parts`, `expected`, `stated`, `gap`); with `--rule`, `rules` gives each rule's `answer`
  and `reason`.

## Explain a rule and fix it

Each explained rule has a page: what the rule checks, why it matters, how to fix it, the common causes, technical
details and the official text.

- English: `https://lintvoice.com/rules/<RULE>/`, for example https://lintvoice.com/rules/BR-FR-10/
- French: `https://lintvoice.com/fr/regles/<RULE>/`
- Every rule with a page, by subject and country: https://lintvoice.com/rules/

Read the page before you explain a rule, and give its link in your answer; give the page in the user's language when
the site has it. New pages appear as rules are explained: when an address answers 404, say so, and explain from the
error message and the official rule. The same texts are in Markdown in https://github.com/lintvoice/invoice-rules
(`rules/<RULE>/`, one file per language).

When the fix belongs in code that generates invoices:

- The message names the business term at fault (`BT-…`). Where each business term sits in CII and in UBL is in
  https://github.com/lintvoice/lintvoice/blob/main/src/lintvoice/terms.json
- Test invoices are in https://github.com/lintvoice/invoice-examples, in the public domain (CC0). Each target has
  its folder under `examples/` (for example `examples/fr/`): a valid invoice that passes every rule its README
  lists, and under `invalid/` the same invoice with one thing wrong for each rule (`examples/fr/invalid/BR-FR-10.xml`:
  the seller's SIREN is missing). The README lists the targets and the rules covered. Comparing an invalid file with
  the valid one shows what breaks the rule.

## What to tell the user

- lintvoice runs the official rules and reports what they find. When it finds no errors, say that the invoice
  passes the rules lintvoice ran, and name them from the report's first line. Do not say that it is compliant,
  certified or sure to be accepted: a platform may run checks of its own.
- What lintvoice does not check yet is in its README (https://github.com/lintvoice/lintvoice#not-checked-yet), and
  the report says when a file gets fewer rules than its format could have (for example, EN 16931 only).
- An invoice holds the user's clients' data. Check it locally rather than pasting it into a web service. Without a
  shell, the page https://lintvoice.com/check/ runs the official rules in the browser: the file does not leave the
  computer.
