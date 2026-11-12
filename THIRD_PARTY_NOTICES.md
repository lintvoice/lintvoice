# Third-party notices

lintvoice's own code is under the MIT licence (`LICENSE`). It ships no third-party code in its Python package: the
packages below are installed from PyPI as dependencies, and the rule packs are downloaded by `lintvoice rules install`.

The **Docker image** bundles all of them. Each keeps its own licence:

| Component | Version | Licence | Source | Licence text in the image |
| --- | --- | --- | --- | --- |
| lxml | ≥ 6.1 | BSD-3-Clause | https://pypi.org/project/lxml/ | its `*.dist-info` folder |
| pypdf | ≥ 6.21.4 | BSD-3-Clause | https://pypi.org/project/pypdf/ | its `*.dist-info` folder |
| saxonche (SaxonC-HE) | ≥ 13.1, < 14 | MPL-2.0 (some components Apache-2.0 or BSD); its wheel metadata carries no licence field | https://pypi.org/project/saxonche/ | `/usr/share/doc/lintvoice/MPL-2.0.txt` |
| EN 16931 validation artefacts | 1.3.17 | EUPL-1.2 | https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/tag/validation-1.3.17 | `/usr/share/doc/lintvoice/EUPL-1.2.txt` |
| France_RFE (BR-FR rules, Factur-X 1.09.2 schemas and rules) | 1.4.0.04 (`97ba0f3`) | Apache-2.0 (repository); the Schematron file headers say EUPL | https://github.com/fnfempe/France_RFE/tree/97ba0f3d4ef2abed5780e9490d5c3a2be832ab1d | `LICENSE` inside the pack, and `/usr/share/doc/lintvoice/EUPL-1.2.txt` |

**The rule packs are unmodified.** Their Schematron sources (`.sch`) ship with the compiled XSLT, inside each pack folder.
France_RFE's folders that hold AFNOR documents (`Z.notes_&_docs/`, `Z.example/`) are never downloaded into the packs.

Licence texts in `third_party/licenses/` (copied to `/usr/share/doc/lintvoice/` in the image) come from the SPDX License List data, release v3.29.0
(https://github.com/spdx/license-list-data/tree/v3.29.0/text).
