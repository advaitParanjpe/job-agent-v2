# Review API

Phase F adds a local review workflow for persisted family-classification and
bounded-tailoring decisions. Reviews let a user approve or correct already
audited choices without rewriting CV content.

## Review Queue

Pending review items are created for:

- `close_match`, `hybrid_match`, and `low_confidence` classifications;
- any classification with `requires_review: true`;
- tailoring decisions with `requires_review: true`;
- tailoring statuses `review_required`, `fallback_to_master`, or
  `tailoring_rejected`.

Clear `master_unchanged` decisions do not enter the default queue.
Duplicate pending review items for the same job and review type are suppressed.
Clear decisions can still be manually added to the queue when a user reports a
wrong family or unwanted automated outcome.

## Statuses

Review items use these statuses:

- `pending`
- `approved`
- `overridden`
- `rejected`
- `deferred`
- `resolved_with_fallback`
- `regeneration_failed`

Resolution history is append-only. The original classifier and tailoring audit
records are never overwritten.

## Allowed Actions

Classification actions:

- `approve_classification`
- `override_family`
- `mark_out_of_scope`
- `defer`

Tailoring actions:

- `approve_tailoring`
- `use_master_unchanged`
- `select_approved_replacement`
- `approve_order`
- `reject_tailoring`
- `defer`

Family overrides are limited to `digital_ic`, `verification`, `software`, and
`ml`, plus `mark_out_of_scope`. Project replacement choices must pass the
existing approved project-block registry, compatibility policy,
one-substitution limit, and duplicate-project checks. Free-form CV text and
arbitrary block IDs are rejected.

## Packet Regeneration

Actions that change the resolved family or resolved project block set record
`regeneration_status: queued`. Phase H adds a local SQLite-backed worker that
claims queued review-regeneration jobs and writes a new linked packet version.
The original automated packet remains retrievable.

Lifecycle:

- `queued`: a packet-changing review resolution has a durable regeneration job.
- `processing`: a worker has atomically claimed the job lease.
- `complete`: a reviewed packet artifact was generated and linked on the
  resolution.
- `failed`: the reviewed packet could not be generated; the prior valid packet
  remains available.
- `not_required`: no packet should be generated, including deferred review and
  out-of-scope decisions.

The worker is local-only and can be run once with:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.regeneration_worker --once
```

or through the local API:

```http
POST /api/workers/regeneration/run-once
```

Queue claiming uses the same repository-supported SQLite lease pattern as Q2:
a queued row is updated to `processing` with a lease owner, lease expiry, and
incremented attempt count in one transaction. Stale processing jobs can be
recovered and retried until `max_attempts` is reached.

Idempotency uses a stable key derived from the review resolution ID, reviewed
family, reviewed project-block order, policy/registry versions, and packet
generator version. If a successful equivalent reviewed packet already exists,
the worker reuses it instead of producing duplicate artifacts.

The default retry policy is:

```json
{
  "max_attempts": 3,
  "stale_processing_seconds": 900,
  "retryable_errors": [
    "temporary_artifact_write_failure",
    "worker_interrupted"
  ]
}
```

Policy, version-drift, invalid family/block, multi-page PDF, unreadable PDF,
and immutable-section failures are reported as safe non-retryable failures.
Failure reasons are concise and do not expose stack traces or local filesystem
paths.

For master-unchanged outcomes the worker copies the selected approved master
`.tex` and `.pdf` into a new packet artifact directory. For reviewed tailored
outcomes it starts from the selected canonical master `.tex`, replaces only the
Projects section with registered immutable blocks, compiles in an isolated
candidate directory, validates exactly one page and immutable sections, then
promotes artifacts only after checks pass. The worker never mutates
`master-cvs/`.

## Ownership

The local API scopes review requests with `X-JobAgent-Owner`. If omitted, the
owner defaults to `local` for compatibility with existing local workflows.
Review listing, retrieval, resolution, feedback export, and packet artifact
serving enforce this owner scope.

## Endpoints

List pending reviews:

```http
GET /api/reviews
X-JobAgent-Owner: local
```

Optional filters include `status`, `review_type`, `family`, and `job_id`:

```http
GET /api/reviews?status=pending&review_type=classification&family=digital_ic
```

Inspect one review:

```http
GET /api/reviews/{review_id}
```

Create a manual review for a job decision:

```http
POST /api/jobs/{job_id}/reviews
Content-Type: application/json

{
  "review_type": "classification",
  "reason": "wrong_family_reported"
}
```

Approve the selected family:

```http
POST /api/reviews/{review_id}/resolve
Content-Type: application/json

{
  "action": "approve_classification",
  "reviewer_id": "local-user",
  "review_note": "Classification looks correct."
}
```

Override the family:

```http
POST /api/reviews/{review_id}/resolve
Content-Type: application/json

{
  "action": "override_family",
  "resolved_family": "verification",
  "reviewer_id": "local-user",
  "review_note": "Role is verification infrastructure."
}
```

Use the approved master unchanged:

```http
POST /api/reviews/{review_id}/resolve
Content-Type: application/json

{
  "action": "use_master_unchanged",
  "resolved_family": "digital_ic",
  "reviewer_id": "local-user"
}
```

Approve the proposed substitution:

```http
POST /api/reviews/{review_id}/resolve
Content-Type: application/json

{
  "action": "approve_tailoring",
  "reviewer_id": "local-user"
}
```

Select another compatible approved block:

```http
POST /api/reviews/{review_id}/resolve
Content-Type: application/json

{
  "action": "select_approved_replacement",
  "resolved_family": "digital_ic",
  "removed_block": "sparrow_cluster_digital_ic_v1",
  "inserted_block": "sparrowml_ml_v1",
  "reviewer_id": "local-user"
}
```

Export reviewed outcomes for later calibration:

```http
GET /api/reviews/feedback
```

The export includes original family, reviewed family, original decision, review
action, original and reviewed block IDs, note, and calibration eligibility. It
does not mutate classifier or tailoring configuration.

## Dashboard Review Workflow

The local dashboard includes a Review queue section above the job table. It can
list pending or resolved reviews, filter by status, review type, and family,
and open a compact detail view for each item.

The detail view separates:

- automated classification scores and evidence;
- automated tailoring status, block choices, replacement gain, and fallback
  reason;
- immutable-content guarantees;
- allowed backend-validated review actions;
- resolution history after a review is resolved.

Family score bars show all four families and identify selected and secondary
families. These scores classify the type of role; they do not represent overall
candidate fit for the position.

Project replacement controls are populated from backend-provided approved
replacement options. The dashboard submits stable block IDs but displays human
readable project names and read-only previews. It does not expose arbitrary
block-ID entry or bullet-editing controls.

Packet-changing resolutions display regeneration state. Phase F/G currently
records these as durable regeneration jobs. The dashboard shows queued,
processing, complete, and failed states, links the reviewed packet when
available, and keeps the previous valid packet visible when regeneration fails.

On scored jobs, the job table includes `Review family selection`. This creates
or opens a pending classification review through `POST /api/jobs/{job_id}/reviews`,
including for clear-match decisions that do not normally enter the default
review queue.

## Immutable Content Guarantees

Reviews may choose approved families and approved whole-project block
combinations only. They cannot edit header/contact information, education,
experience, skills, coursework, or project-block wording. Canonical master CV
files remain unchanged.
