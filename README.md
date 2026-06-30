# JobAgent V2

Local-only job application queue and packet-generation system.

This repository is currently verified through Phase 5. It contains a local
capture-to-packet workflow with deterministic intake, scoring, promotion, and
canonical CV packet generation. Optional live LLM semantic evidence is supported
only when explicitly enabled; the default checks are offline and deterministic.

The committed truth banks are generic starter content. Replace them with
reviewed personal canonical CV families before using generated packets for real
applications.

Authoritative active state and handoff instructions live in:

```text
project/current.md
project/roadmap.md
project/history.md
AGENTS.md
```

## Layout

```text
backend/     Python package and backend tests
frontend/    Placeholder frontend build
extension/   Placeholder Chrome extension structure
docs/        Build reports and project documentation
scripts/     Repository checks
```

## Check

Run the complete repository check from this directory:

```bash
python3 scripts/check.py
```

## Local API

Run the local API server:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.server
```

Endpoint documentation is in `docs/phase_1_api.md`. The filename is historical;
the document covers the current local API through packet-generation endpoints.

Packet PDF generation requires `pdflatex` on `PATH`. If the LaTeX toolchain is
missing, packet generation fails visibly and remains retryable.

## Canonical Truth Banks

The bundled truth banks are starter fixtures for deterministic development and
tests. Real application packets require user-approved canonical CV content.
The registration contract is documented in `docs/truth_bank_registration.md`.

## Approved Master CVs

Fixed user-approved master CVs live in `master-cvs/`. Their registration and
immutability rules are documented in `docs/master_cv_registration.md`.

## Approved Project Blocks

Whole-project block registry and bounded tailoring policy are documented in
`docs/project_block_registry.md`.

## One-Block Tailoring

Packet generation can now perform bounded one-block project tailoring for
eligible jobs. The production policy, thresholds, audit records, one-page
validation, fallback behavior, and immutable-content guarantees are documented
in `docs/bounded_tailoring.md`.

## Calibration

The labelled classifier/tailoring evaluation dataset, deterministic calibration
command, metrics, and promotion gates are documented in `docs/calibration.md`.

## Review API

Classification and tailoring decisions that require review can be inspected and
resolved through the local review API documented in `docs/review_api.md`.
