# ADR 0002 — Terraform state backend bootstrap

**Status:** Accepted
**Date:** 2026-08-12

## Context

Every environment configuration in `infra/envs/` needs remote Terraform state:
a shared, durable, lockable store so state is not trapped on one laptop and two
applies cannot race each other.

The natural place is an S3 bucket. That creates a circular dependency —
Terraform needs the bucket to store its state, but the bucket is itself a
resource Terraform should manage.

## Decision

A separate root module, `bootstrap/`, creates the state bucket. It is applied
once, by hand, before any environment exists.

On its **first** apply, `bootstrap/` had no `backend` block and wrote state to
a local file. Once the bucket existed, the backend block was added and the state
migrated into the bucket it had just created:

```
terraform init -migrate-state
```

`bootstrap/` now stores its own state at `bootstrap/terraform.tfstate` inside
the bucket it manages. Environments use the same bucket under `<env>/terraform.tfstate`.

## Locking

State locking uses **native S3 conditional writes** (`use_lockfile = true`),
which requires Terraform ≥ 1.10.

The older pattern provisioned a DynamoDB table purely to hold a lock row. That
is now unnecessary: S3 supports the conditional-write primitive directly. This
removes an entire resource, and — relevant here — removes a DynamoDB table that
would have consumed part of the 25 RCU/WCU always-free allowance that the
application's own table needs.

## Bucket configuration and why

| Setting | Reason |
|---|---|
| `prevent_destroy = true` | `terraform destroy` in an environment must never be able to remove the record of what exists. Removing it requires a deliberate code edit. |
| Versioning enabled | The real recovery mechanism for state corruption. A bad apply or truncated write can be rolled back to a previous object version. |
| SSE-S3 (AES256) | State stores resource attributes in plaintext. In `url-shortener`, gitleaks caught Log Analytics shared keys inside a state backup — that is what state files look like. SSE-KMS was rejected: a customer-managed key costs ~$1/month against a $0 budget, and AES256 still encrypts at rest. |
| All four public access blocks | A world-readable state file is a full inventory of the account. |
| Noncurrent versions expire at 30 days | Versioning otherwise retains every historical state forever, consuming free-tier storage for no benefit. |

## Consequences

- `bootstrap/` is a documented manual prerequisite, applied once. It is not part
  of any CI pipeline.
- If the bucket is ever deleted, `prevent_destroy` must be removed first, and
  all environment state is lost with it. Recovery would mean `terraform import`
  for every resource.
- The same reasoning as ADR 0001 applies, one layer up: **the thing that stores
  your state cannot itself be stored in that state until it exists.** Bootstrap
  problems are solved by running once out-of-band, then adopting the result.

## Verification

```
$ aws s3 ls s3://job-radar-tfstate-428625199448/ --recursive
2026-08-12 15:32:22   8759 bootstrap/terraform.tfstate

$ terraform plan -detailed-exitcode
No changes. Your infrastructure matches the configuration.

$ checkov -d bootstrap
Passed checks: 7, Failed checks: 0
```

## Related

- ADR 0001 — cost guardrails live outside Terraform
