# ADR 0001 — Cost guardrails live outside Terraform

**Status:** Accepted
**Date:** 2026-08-10

## Context

This project runs on an AWS account with a hard $0 budget. The primary risk is
not that the architecture is wrong — it is that a misconfigured resource quietly
accrues charges for days before anyone notices.

The obvious instinct is to define AWS Budgets in Terraform alongside everything
else, so the whole account is reproducible from one `terraform apply`.

## Decision

Budgets and billing notifications are created **once, by hand, via the AWS CLI**
(`scripts/00-guardrails.sh`) before any Terraform configuration exists. They are
not managed by Terraform and are not in any state file.

## Rationale

1. **A safety net cannot depend on the thing it is catching.** If Terraform
   state is corrupted, locked, or destroyed, Terraform-managed budgets go with
   it — precisely when they are most needed.
2. **Ordering.** Guardrails must exist before the first resource does. AWS
   billing data lags by hours, so an alarm created after a mistake reports the
   bill rather than preventing it. Terraform cannot be the first thing to run
   because it needs a remote state backend, which is itself a resource
   (see ADR 0002).
3. **`terraform destroy` should never remove the guardrails.** Tearing the
   project down to zero is a routine operation here. The budgets must survive it.

## Consequences

- The account is not 100% reproducible from Terraform alone. `scripts/00-guardrails.sh`
  is a documented manual prerequisite, not a gap.
- The script must be idempotent, since there is no state file to tell it what
  already exists.
- The general principle: **guardrails belong outside the system they guard.**
  The same reasoning is why the Terraform state backend is bootstrapped
  separately.

## Related

- ADR 0002 — Terraform state backend bootstrap (the same chicken-and-egg)
