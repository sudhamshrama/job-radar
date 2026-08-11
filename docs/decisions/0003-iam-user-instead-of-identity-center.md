# ADR 0003 — Local auth uses an IAM user, not Identity Center

**Status:** Accepted
**Date:** 2026-08-11

## Context

AWS's own guidance is to avoid long-lived IAM access keys and use IAM Identity
Center, which issues short-lived credentials via `aws configure sso`. That was
the intended approach for this project.

This account is on the credit-based **AWS Free Plan** introduced in 2025:
$100 of credits, expiring 2027-02-10, after which AWS *suspends service* rather
than charging. That suspension behaviour is the reason the plan is viable for a
project with a hard $0 budget.

Enabling IAM Identity Center requires an AWS Organization. The enable screen
states plainly:

> Creating an organization automatically upgrades your account from a free plan
> to a paid plan with a pay-as-you-go pricing and your free tier credits expire
> immediately.

Separately, the default multi-Region instance provisions a customer-managed KMS
key, which carries its own recurring charge (~$1/month).

## Decision

Local developer access uses an **IAM user (`sudhamsh-admin`)** with
`AdministratorAccess`, MFA enabled, and a long-lived access key configured
through `aws configure`.

IAM Identity Center and AWS Organizations are **not** enabled on this account.

## Rationale

The security best practice and the cost constraint are in direct conflict here,
and the cost constraint is load-bearing: enabling SSO would have terminated the
free plan on the spot, converted the account to pay-as-you-go, and put real
charges on a personal card. A more secure credential mechanism is not worth
much if the project cannot afford to exist.

This is a constraint-driven decision, not an endorsement of access keys.

## Mitigations

1. **CI never uses this key.** GitHub Actions authenticates via OIDC role
   assumption, which does not require Organizations. The pipeline holds no
   AWS credentials at all.
2. MFA is enabled on the IAM user.
3. The key is scoped to one human on one machine, and is rotatable.
4. Possible hardening (Stage 8): reduce the IAM user's own policy to
   `sts:AssumeRole` only, with an MFA condition, so the standing key is useless
   without an explicit role assumption.

## Consequences

- A long-lived credential exists on the development laptop. This is the
  accepted risk.
- If this account ever moves to a paid plan for other reasons, the decision
  should be revisited — the blocker is purely the free-plan interaction.
- The general lesson, and the one worth stating out loud: **security guidance is
  written for the unconstrained case.** Knowing why you deviated, and what you
  did to compensate, is the actual skill.

## Related

- ADR 0001 — cost guardrails live outside Terraform
