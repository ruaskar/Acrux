# Security Policy

keymd is a local proxy that sits on the path between your AI coding agent and your
model provider. It forwards your API key to your chosen upstream and can read and
(via `keymd_edit`) modify files inside your project. Because of that position, we
take security reports seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's **[Report a vulnerability](https://github.com/ruaskar/Acrux/security/advisories/new)**
button (Security → Advisories). This opens a private channel with the maintainers.

Please include:
- the version (`keymd --version`) and OS,
- a description and, ideally, a minimal reproduction,
- the impact you observed.

We aim to acknowledge a report within a few days and to ship a fix or mitigation
for confirmed, high-impact issues as quickly as is practical for a small project.
Coordinated disclosure is appreciated — we'll credit you in the release notes unless
you prefer otherwise.

## Scope / threat model

In scope:
- The proxy mishandling, logging, or leaking the forwarded API key.
- Reads or edits escaping the project root (`keymd_read_full` / `keymd_read_range` /
  `keymd_read_symbol` / `keymd_edit` are confined to the indexed repository).
- A scanned secret being surfaced in a `.key.md` summary, the index, or the model
  context (keymd redacts secret-shaped values — report misses).
- Integrity of the install / self-update path (`install.sh`, `install.ps1`,
  `keymd update` verify the binary against the release's `SHA256SUMS`).

Known limitations (not vulnerabilities, but good to know):
- The released binaries are **not yet code-signed / notarized**; integrity rests on
  the published `SHA256SUMS`. macOS/Windows may warn on a browser-downloaded binary —
  prefer the one-line installer, which verifies the checksum.
- The local proxy listens on `127.0.0.1` only and should not be exposed to other
  hosts; do not bind it to `0.0.0.0` on an untrusted network.
- First run fetches dependency wheels from PyPI over the network.

## Supported versions

Only the latest release receives fixes. Upgrade with `keymd update`.
