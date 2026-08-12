# ADR 0006 — GitHub OIDC subject claims contain immutable IDs

**Status:** Accepted
**Date:** 2026-08-12

## Context

CI authenticates to AWS via GitHub OIDC (ADR 0003 explains why Identity Center
was unavailable). The trust policy was written from the documented form of the
subject claim:

```hcl
condition {
  test     = "StringLike"
  variable = "token.actions.githubusercontent.com:sub"
  values   = ["repo:sudhamshrama/job-radar:*"]
}
```

The OIDC provider existed, the role existed, the policy read correctly, and the
workflow had `id-token: write`. Every job failed:

```
Could not assume role with OIDC:
Not authorized to perform sts:AssumeRoleWithWebIdentity
```

## Investigation

The error names no claim and no condition, so there was nothing to fix by
reading it. The token GitHub actually presented is recorded in CloudTrail:

```
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity
```

```
sub: repo:sudhamshrama@68714390/job-radar@1332426770:ref:refs/heads/main
```

Not the documented `repo:owner/name:ref:...`. GitHub embeds **immutable numeric
IDs** for the owner and the repository.

Confirmed independently rather than inferred from the error:

```
$ gh api repos/sudhamshrama/job-radar --jq '{owner: .owner.id, repo: .id}'
{"owner": 68714390, "repo": 1332426770}
```

## Decision

The trust policy accepts both forms. A `StringLike` value list is an OR:

```hcl
values = [
  "repo:sudhamshrama/job-radar:*",
  "repo:sudhamshrama@68714390/job-radar@1332426770:*",
]
```

## Why this is stricter, not a workaround

The instinct is to treat the ID form as an annoyance and match it with
wildcards. It is the opposite — it is a **security improvement**, and pinning
the IDs is tighter than the name-based policy it replaces.

Repository and account **names are mutable**. A repo can be renamed,
transferred, or deleted and the name re-registered by someone else. A
name-based trust policy follows the name to whoever holds it next, so a
deleted-and-squatted repo could assume a role that was never meant for it.
Numeric IDs are never reassigned.

## Consequences

- The immutable ID must be looked up for each new repository. `gh api repos/<owner>/<repo>`
  gives it directly; there is no way to derive it from the name.
- The legacy pattern is kept because the older format still appears in some
  contexts, and losing CI to a format change is worse than a slightly broader
  policy. Both are scoped to this one repository.
- **The general lesson:** when a request is rejected on a claim you cannot see,
  stop reading the config and go find the actual token. CloudTrail records the
  presented claims. Two hours of re-reading a correct trust policy would not
  have revealed a subject format nobody documented.

## Related

- ADR 0003 — IAM user instead of Identity Center (why OIDC, and why not SSO)
- ADR 0005 — plan validates configuration, not authorization
