"""Rule packs: the official validation artefacts, pinned and installed locally.

lintvoice ships no rule files. `lintvoice rules install` downloads each pack once, from its
upstream source, at a pinned version, and checks it. After that, every check runs offline.

The packs keep their own licences: EN 16931 is EUPL-1.2; France_RFE has an Apache-2.0
repository licence and EUPL headers in its Schematron files.
"""

import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


class RulesNotInstalled(Exception):
    pass


@dataclass(frozen=True)
class Download:
    url: str
    sha256: str | None  # of the downloaded bytes; None when they may change (a GitHub archive generated on the fly)
    into: str = ""
    keep: tuple[str, ...] = ()  # path prefixes to extract (after the archive's top folder); () = all
    strip_top: bool = False
    content_sha256: str | None = None  # of the kept files (content_digest): stable even if the archive bytes change


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    version: str
    source: str
    licence: str
    downloads: tuple[Download, ...] = field(default=())

    @property
    def folder(self):
        return f"{self.id}-{self.version}"


EN16931_RELEASE = "https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/download/validation-1.3.17"
FRANCE_RFE_COMMIT = "97ba0f3d4ef2abed5780e9490d5c3a2be832ab1d"

PACKS = {
    "en16931": Pack(
        id="en16931",
        name="EN 16931 validation artefacts",
        version="1.3.17",
        source="https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/tag/validation-1.3.17",
        licence="EUPL-1.2",
        downloads=(
            Download(
                f"{EN16931_RELEASE}/en16931-cii-1.3.17.zip",
                "e5f3235824b6b38454b1d54cf3f14e01efb5b33971fbefc4e64997d0ef619e89",
                into="cii",
            ),
            Download(
                f"{EN16931_RELEASE}/en16931-ubl-1.3.17.zip",
                "bf02a0e3f6cbe692a4a28e70be7bdcaded5612b4169b543e13d6cb4f33c29e92",
                into="ubl",
            ),
        ),
    ),
    "france-rfe": Pack(
        id="france-rfe",
        name="FNFE-MPE France_RFE (BR-FR rules, Factur-X 1.09.2)",
        version="1.4.0.04",
        source=f"https://github.com/fnfempe/France_RFE/tree/{FRANCE_RFE_COMMIT}",
        licence="Apache-2.0 (repository); EUPL (Schematron file headers)",
        downloads=(
            # Only the rule folders: the repository's Z.notes_&_docs/ and Z.example/ hold AFNOR documents.
            Download(
                f"https://github.com/fnfempe/France_RFE/archive/{FRANCE_RFE_COMMIT}.zip",
                None,
                keep=(
                    "FNFE_RFE_INVOICE/CII/",
                    "FNFE_RFE_INVOICE/UBL/",
                    "FNFE_RFE_INVOICE/Factur-X/",
                    "LICENSE",
                    "README.md",
                ),
                strip_top=True,
                # GitHub generates this archive on the fly, so its bytes may change: the files are pinned instead.
                content_sha256="8892563149e4a7ef303a4c4943a930deb1ebeff812934164e259fb1f8e546ea8",
            ),
        ),
    ),
}


def rules_dir(override=None):
    """Where packs live: --rules-dir, then $LINTVOICE_RULES_DIR, then the user cache."""
    if override:
        return Path(override)
    if os.environ.get("LINTVOICE_RULES_DIR"):
        return Path(os.environ["LINTVOICE_RULES_DIR"])
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "lintvoice" / "rules"


def pack_path(pack, root):
    return Path(root) / pack.folder


def is_installed(pack, root):
    return (pack_path(pack, root) / ".installed.json").exists()


def require(root, pack_ids=PACKS):
    missing = [p for p in pack_ids if not is_installed(PACKS[p], root)]
    if missing:
        raise RulesNotInstalled(
            f"rule packs not installed: {', '.join(missing)} (looked in {root}). Run: lintvoice rules install"
        )


def content_digest(files):
    """SHA-256 over (path, SHA-256 of the bytes) for each file, in path order: the content of a pack, whatever
    archive carried it."""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(f"{rel}\0{hashlib.sha256(files[rel]).hexdigest()}\n".encode())
    return h.hexdigest()


def _safe(rel):
    """An archive entry must stay inside the pack folder (no zip slip)."""
    parts = Path(rel).parts
    if not rel or Path(rel).is_absolute() or ".." in parts or rel.startswith(("/", "\\")):
        raise ValueError(f"refusing archive entry {rel!r}: it would be written outside the pack folder")
    return rel


def _fetch(url):
    if not url.startswith("https://"):  # the pack URLs are constants; never file:// or another scheme
        raise ValueError(f"refusing to download from {url!r}: only https:// is allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "lintvoice"})  # noqa: S310 (https only, checked above)
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return response.read()


def install(pack, root, force=False, fetch=_fetch):
    """Download, check and unpack one pack. Returns the number of files written."""
    target = pack_path(pack, root)
    if is_installed(pack, root) and not force:
        return 0
    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    count = 0
    for d in pack.downloads:
        data = fetch(d.url)
        if d.sha256 and hashlib.sha256(data).hexdigest() != d.sha256:
            raise ValueError(f"checksum mismatch for {d.url}: the download is not the pinned version")
        archive = zipfile.ZipFile(io.BytesIO(data))
        files = {}
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            rel = name.split("/", 1)[1] if d.strip_top else name
            if d.keep and not rel.startswith(d.keep):
                continue
            files[_safe(rel)] = archive.read(name)
        if d.content_sha256 and content_digest(files) != d.content_sha256:
            raise ValueError(f"content mismatch for {d.url}: the files are not the pinned version")
        for rel, content in files.items():
            out = staging / d.into / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(content)
            count += 1
    (staging / ".installed.json").write_text(
        json.dumps(
            {
                "id": pack.id,
                "version": pack.version,
                "source": pack.source,
                "files": count,
                "installed": date.today().isoformat(),
            },
            indent=1,
        )
    )
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return count
