# ADR 0005 — Reserved concurrency is impossible on this account

**Status:** Accepted (constraint, not preference)
**Date:** 2026-08-12

## Context

`checkov` raised **CKV_AWS_115**: Lambda functions should set a function-level
concurrency limit. That is a good finding here, and not only for the security
reason checkov gives it — reserved concurrency is a **cost** control. Without a
cap, a misconfigured trigger or a retry storm can invoke a function thousands of
times in parallel and consume the free-tier allowance in minutes.

So `reserved_concurrent_executions = 2` was added. `terraform validate` passed.
`terraform plan` was clean: **13 to add, 0 to change, 0 to destroy.**

## What happened

The apply failed partway through, after the IAM role, the SNS topic, the log
group and the DynamoDB table had already been created:

```
Error: setting Lambda Function (job-radar-dev-ingest) concurrency:
InvalidParameterValueException: Specified ReservedConcurrentExecutions for
function decreases account's UnreservedConcurrentExecution below its minimum
value of [10].
```

Investigating the account:

```
$ aws lambda get-account-settings --query 'AccountLimit.ConcurrentExecutions'
10

$ aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384
Concurrent executions   Value: 10.0   Adjustable: true
```

The default account concurrency limit is normally 1000. New accounts start far
below that — this one is at **10**.

AWS requires at least **10 unreserved** concurrent executions account-wide. The
account total is 10. Therefore reserving *any* amount, even 1, drops unreserved
to 9 and is rejected.

**The intersection of "allowed reservations" and "possible reservations" is
empty.** No value of this setting can succeed.

## Decision

`reserved_concurrency` defaults to `-1` (unreserved), with the reason recorded
in the variable description and a `checkov:skip=CKV_AWS_115` carrying the same
explanation. It is a module variable rather than a hardcoded value, so it can
be set to a real number the moment the quota is raised.

## Why this is acceptable rather than merely unavoidable

The control checkov asked for still exists — at a different scope. The
account-wide limit of 10 concurrent executions *is* the runaway-invocation
guardrail a per-function reservation would have provided. On an account with a
1000 limit, one function could consume everything; here the blast radius is
capped at 10 by the account itself.

The quota is adjustable via a support request. That is deferred: the protection
is already effectively present, and the current limit is comfortably above what
a single scheduled function needs.

## The lesson

This is the same lesson as `url-shortener`'s AKS failure, in a different
service:

> **`terraform plan` validates configuration, not authorization.**

A green plan is not a promise the apply will work. Policy, service quotas and
account limits are evaluated by the resource provider at **create** time, not at
plan time. Terraform cannot know your account's concurrency quota by reading
your configuration.

Two practical consequences:

1. **A green plan in CI does not mean a deploy will succeed.** Any pipeline that
   treats `plan` as a gate must still handle apply-time rejection.
2. **Partial applies are normal.** This one left four resources created and the
   fifth failed. Terraform state correctly recorded what existed, and the
   corrected re-apply reported `5 added, 0 changed, 1 destroyed` rather than
   trying to recreate everything. That is remote state doing its job.

## Related

- ADR 0002 — Terraform state backend
- `url-shortener` ADR 0002 — AKS blocked by student quota (same lesson, Azure)
