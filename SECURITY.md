# Security Policy

## Reporting a vulnerability

This is a public repository of the ActiveInferenceInstitute org. If you find a
security issue (credential leak, injection, XSS in the web interface, unsafe
download behavior, etc.):

- **Do not open a public issue** for exploitable vulnerabilities.
- Report privately via [GitHub Security Advisories](https://github.com/ActiveInferenceInstitute/Journal_Utilities/security/advisories/new)
  ("Report a vulnerability"), or by contacting the maintainers through the
  Active Inference Institute.
- Include a description, the affected version/commit, and reproduction steps.

We aim to acknowledge reports within a week and to ship a fix promptly.

## Credentials and secrets

This repo has had a credential leak in the past (a `cookies.txt` with live Google
session cookies), which was purged from history. To keep it from recurring:

- `cookies.txt`, `.env`, and private-video state are gitignored and must never be
  committed.
- The downloader runs **cookie-free by default**; authenticated download must
  never write cookies into a tracked path (`--cookies-from-browser` into a
  tracked output path is forbidden).
- `.env.example` contains only placeholders; committed config files
  (`config.ini`, `Makefile`, CI) must contain no credentials and no private
  machine paths.
- PRs that add secrets or private paths will be rejected.

## Data handling

- Runtime state (e.g. the private-video registry) is written under `data/`, never
  into the source tree.
- The journal `main` branch carries no audio and no credentials by policy,
  enforced by the read-only `scripts/validate_journal.py` gate.

## Supported versions

The `main` branch is the supported surface; fixes land there and are backported
on request.
