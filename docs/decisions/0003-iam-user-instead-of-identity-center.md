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
`AdministratorAccess` and MFA enabled.

**No long-lived access key exists.** Credentials are obtained with `aws login`,
which exchanges the browser console session for temporary session credentials.
Nothing is written to `~/.aws/credentials`; the session expires and is
re-established on demand.

IAM Identity Center and AWS Organizations are **not** enabled on this account.

## Rationale

The security best practice and the cost constraint are in direct conflict here,
and the cost constraint is load-bearing: enabling SSO would have terminated the
free plan on the spot, converted the account to pay-as-you-go, and put real
charges on a personal card. A more secure credential mechanism is not worth
much if the project cannot afford to exist.

This is a constraint-driven decision, not an endorsement of access keys.

**The accepted risk then disappeared.** The plan was an IAM user with a
long-lived access key. Before creating one, the AWS CLI itself surfaced
`aws login`, which brokers short-lived session credentials from the console
session — the property Identity Center was wanted for, without the Organization
that would have destroyed the free plan.

So the outcome is better than the decision that was made: short-lived
credentials, no Organization, no expired credits.

## Mitigations

1. **CI never uses this key.** GitHub Actions authenticates via OIDC role
   assumption, which does not require Organizations. The pipeline holds no
   AWS credentials at all.
2. MFA is enabled on the IAM user.
3. Local credentials are **short-lived session credentials**, not a stored key.
   There is no static secret on the laptop to leak or rotate.

A further hardening was considered and **rejected as unnecessary**: restricting
the IAM user to `sts:AssumeRole` with an MFA condition, so that a standing key
would be useless on its own. That control exists to neutralise a long-lived
key. There is no long-lived key here, so it would add a role-assumption step
and defend against nothing.

## Consequences

- No credential is stored on the development laptop. Sessions expire, which
  means re-authenticating during long working sessions.
- `aws login` reads whichever console session is active. It picked up **root**
  on the first attempt and had to be redirected to `sudhamsh-admin`, which is
  why `scripts/00-guardrails.sh` refuses to run as root.
- If this account ever moves to a paid plan for other reasons, Identity Center
  becomes available and should be revisited — the blocker is purely the
  free-plan interaction.
- The general lesson: **security guidance is written for the unconstrained
  case.** Recording why a deviation was necessary, and what compensates for it,
  is the part that matters.

## Related

- ADR 0001 — cost guardrails live outside Terraform
