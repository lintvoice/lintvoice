"""Command line: lintvoice check FILE..., lintvoice rules list|install.

Exit codes: 0 no errors, 1 errors found, 2 a file could not be read as an invoice, 3 rule packs missing,
4 no errors found but a rule set could not run on a file (an error inside the official rule file).
XML files found while walking a directory are skipped when they are not invoices (a build.xml, a config file);
a file named on the command line must be an invoice.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, document, engine, report, rulepacks

EXIT_OK, EXIT_ERRORS, EXIT_UNREADABLE, EXIT_NO_RULES, EXIT_INCOMPLETE = 0, 1, 2, 3, 4
INVOICE_SUFFIXES = {".xml", ".pdf"}


def _files(paths):
    """Yield (path, named): directories expand into their .xml and .pdf files, sorted (named=False);
    files are kept as given (named=True)."""
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in INVOICE_SUFFIXES):
                yield f, False
        else:
            yield p, True


def _rules_option(value):
    if value == "auto":
        return "auto"
    chosen = {v.strip() for v in value.split(",") if v.strip()}
    unknown = chosen - set(engine.RULE_CHOICES)
    if unknown or not chosen:
        raise argparse.ArgumentTypeError(
            f"unknown rule set {', '.join(sorted(unknown)) or '(empty)'}; choose auto or a list of: "
            + ", ".join(engine.RULE_CHOICES)
        )
    return chosen


_ENGINES = {}


def _engine(root):
    """One engine per rules folder and process: each rule set is compiled once, then reused."""
    key = str(Path(root).resolve())
    if key not in _ENGINES:
        _ENGINES[key] = engine.Engine(root)
    return _ENGINES[key]


def _use_color(stream, choice):
    if choice != "auto":
        return choice == "always"
    return stream.isatty() and "NO_COLOR" not in os.environ


def cmd_check(args, out):
    root = rulepacks.rules_dir(args.rules_dir)
    style = report.Style(_use_color(out, args.color) and args.format == "text")
    try:
        rulepacks.require(root)
    except rulepacks.RulesNotInstalled as e:
        print(f"lintvoice: {e}", file=sys.stderr)
        return EXIT_NO_RULES
    eng = _engine(root)
    results, failures, skipped, blocks = [], [], [], []
    for path, named in _files(args.paths):
        try:
            doc = document.load(path)
            result = eng.check(doc, args.rules)
        except document.NotAnInvoiceXml as e:
            if named:
                failures.append((path, str(e)))
                blocks.append(report.text_error(path, str(e), style))
            else:
                skipped.append(path)
            continue
        except FileNotFoundError:
            failures.append((path, "file not found"))
            blocks.append(report.text_error(path, "file not found", style))
            continue
        except (document.NotAnInvoice, IsADirectoryError, PermissionError) as e:
            failures.append((path, str(e)))
            blocks.append(report.text_error(path, str(e), style))
            continue
        results.append(result)
        if not (args.quiet and not result.errors and not result.not_run):
            blocks.append(report.text_result(result, style, verbose=args.verbose))
    if not results and not failures:
        what = f"only {len(skipped)} XML file(s) that are not invoices" if skipped else "no .xml or .pdf file"
        print(f"lintvoice: {what} found in the given paths", file=sys.stderr)
        return EXIT_UNREADABLE
    code = (
        EXIT_UNREADABLE
        if failures
        else EXIT_ERRORS
        if any(r.errors for r in results)
        else EXIT_INCOMPLETE
        if any(r.not_run for r in results)
        else EXIT_OK
    )
    if args.format == "json":
        print(report.json_report(results, failures, code, skipped), file=out)
    else:
        used = [rs for r in results for rs in r.rule_sets]
        print(report.header(used, style), file=out)
        for b in blocks:
            print("", file=out)
            print(b, file=out)
        print("", file=out)
        if skipped:
            names = ", ".join(str(s) for s in skipped[:3]) + (
                f" and {len(skipped) - 3} more" if len(skipped) > 3 else ""
            )
            print(
                style.dim(
                    f"Skipped {len(skipped)} XML file{'s' * (len(skipped) != 1)} that {'are' if len(skipped) != 1 else 'is'} not an invoice: {names}"
                ),
                file=out,
            )
        print(report.footer(results, failures, style), file=out)
    return code


def cmd_rules_list(args, out):
    root = rulepacks.rules_dir(args.rules_dir)
    print(f"Rule packs in {root}", file=out)
    for pack in rulepacks.PACKS.values():
        state = "installed" if rulepacks.is_installed(pack, root) else "not installed"
        print(f"  {pack.id:<11} {pack.version:<9} {state:<14} {pack.name}", file=out)
        print(f"  {'':<11} licence: {pack.licence}", file=out)
        print(f"  {'':<11} source:  {pack.source}", file=out)
    return EXIT_OK


def cmd_rules_install(args, out):
    root = rulepacks.rules_dir(args.rules_dir)
    for pack in rulepacks.PACKS.values():
        if rulepacks.is_installed(pack, root) and not args.force:
            print(f"{pack.id} {pack.version}: already installed", file=out)
            continue
        print(f"{pack.id} {pack.version}: downloading from {pack.source}", file=out)
        try:
            count = rulepacks.install(pack, root, force=args.force)
        except Exception as e:
            print(f"lintvoice: could not install {pack.id}: {e}", file=sys.stderr)
            return EXIT_NO_RULES
        print(f"{pack.id} {pack.version}: {count} files installed in {rulepacks.pack_path(pack, root)}", file=out)
    return EXIT_OK


def parser():
    p = argparse.ArgumentParser(prog="lintvoice", description="Offline e-invoice validator: EN 16931, Factur-X, BR-FR.")
    p.add_argument("--version", action="version", version=f"lintvoice {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check invoice files (CII or UBL XML, Factur-X PDF)")
    check.add_argument("paths", nargs="+", help="files or directories (directories: every .xml and .pdf inside)")
    check.add_argument(
        "--rules",
        type=_rules_option,
        default="auto",
        help="auto (default: EN 16931, Factur-X profile rules, BR-FR when the seller is in France) "
        "or a comma list of: " + ", ".join(engine.RULE_CHOICES),
    )
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("-v", "--verbose", action="store_true", help="full messages and every location")
    check.add_argument("-q", "--quiet", action="store_true", help="only list files with errors or an incomplete check")
    check.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    check.add_argument("--rules-dir", help="where the rule packs are installed")
    check.set_defaults(func=cmd_check)

    rules = sub.add_parser("rules", help="list or install the rule packs")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    lst = rules_sub.add_parser("list", help="show the pinned rule packs and whether they are installed")
    lst.add_argument("--rules-dir")
    lst.set_defaults(func=cmd_rules_list)
    inst = rules_sub.add_parser("install", help="download the pinned rule packs (once; checks are offline after)")
    inst.add_argument("--rules-dir")
    inst.add_argument("--force", action="store_true", help="download again even if installed")
    inst.set_defaults(func=cmd_rules_install)
    return p


def main(argv=None, out=None):
    args = parser().parse_args(argv)
    return args.func(args, out or sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
