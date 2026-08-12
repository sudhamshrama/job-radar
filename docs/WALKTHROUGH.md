# job-radar — What We Did and Why

A plain-English record of every decision, trap, and mistake in this project, in
the order they happened. Written so you can defend this work out loud.

Covers: **Stage 0 (account guardrails)**, **Stage 1 (Terraform state backend)**,
and **Stage 2 (source selection)** — everything through 2026-08-12.

---

## Table of contents

1. [Why this project exists](#1-why-this-project-exists)
2. [The architecture we're building](#2-the-architecture-were-building)
3. [Stage 0 — guardrails before resources](#3-stage-0--guardrails-before-resources)
4. [Stage 1 — the Terraform state backend](#4-stage-1--the-terraform-state-backend)
5. [Stage 2 — picking job sources](#5-stage-2--picking-job-sources)
6. [Every mistake made, and what it taught](#6-every-mistake-made-and-what-it-taught)
7. [Glossary](#7-glossary)
8. [Interview questions this project answers](#8-interview-questions-this-project-answers)

---

## 1. Why this project exists

This is **project 2 of 4** in your DevOps portfolio.

Project 1 (`url-shortener`) already covers: Docker, Kubernetes, Kustomize,
ArgoCD/GitOps, GitHub Actions, Prometheus, Grafana, Loki, Jaeger, Trivy,
gitleaks, Terraform, Azure.

What it did **not** cover, ranked by how often it appears in DevOps job postings:

| Gap | Why it matters |
|---|---|
| **AWS** | Most postings say AWS. You had zero. |
| **IAM** | The thing AWS interviewers actually probe. |
| **Serverless / event-driven** | A different architecture, not the same app twice. |
| **Remote Terraform state** | Project 1 used local state. |
| **Terraform modules, multi-env** | Real IaC structure, not one flat file. |
| **A live clickable URL** | Project 1 ran on your laptop. |

`job-radar` covers all six. Crucially it shares almost no surface with project 1
— different cloud, no Kubernetes, no containers as the point, event-driven
instead of request/response. On a resume, two projects that look different beat
one project split in half.

**Why job postings as the subject:** you're job hunting right now. You'll run
this daily, which means you'll find real bugs. Project 1's genuine interview
value came from things that broke when it ran, not from the architecture diagram.

---

## 2. The architecture we're building

```
EventBridge Scheduler (cron)
        │
        ▼
  ingest Lambda ──► SQS ──► normalize Lambda ──► DynamoDB
        │            │                              │
  public board      DLQ                      DynamoDB Streams
     APIs                                           │
                                                    ▼
                                            notify Lambda ──► SNS ──► email

  CloudFront ──► S3 (static dashboard)
       └──────► API Gateway (HTTP API) ──► query Lambda ──► DynamoDB
```

**Everything sits in an AWS always-free tier**, with two tracked exceptions
(API Gateway and S3 are free for 12 months, not forever).

**Deliberately avoided:** EKS (~$73/mo just for the control plane), NAT Gateway
(~$32/mo), Route 53 hosted zone ($0.50/mo). Any one of these would blow a $0
budget while looking like a normal architectural choice.

---

## 3. Stage 0 — guardrails before resources

### The principle

Nothing in Stage 0 is impressive. All of it is why the project survives.

The order is deliberate:

```
account exists → root gets MFA → root is never used again
    → a non-root identity for daily work → budget alarms → THEN first resource
```

**Why budgets come before resources:** AWS billing data lags by hours. An alarm
created *after* a mistake reports the bill you already owe. An alarm is a smoke
detector — you install it before you start cooking, not after the kitchen fills
with smoke.

### Trap 1 — the AWS free tier is not what tutorials describe

AWS restructured the free tier in 2025. Your account is on the new
**credit-based Free Plan**:

- $100 in credits
- Expires **2027-02-10** (185 days from signup)
- When credits run out or the period ends, **AWS suspends service rather than billing you**

That suspension is the *good* failure mode for a $0 budget — you get switched
off instead of charged. But it has a consequence for a portfolio:

> **Your live dashboard URL will go dark in February 2027.**

If you're still interviewing then, a dead link on a resume is worse than no
link. Stage 9 therefore ships screenshots and a recorded demo so the project
still reads when the URL stops working.

### Trap 2 — enabling IAM Identity Center would have destroyed the free plan

**This was the most expensive near-miss in the project.**

AWS's own best-practice guidance says: don't use long-lived access keys, use
**IAM Identity Center**, which issues short-lived credentials.

So we went to enable it. The enable screen said:

> Creating an organization automatically upgrades your account from a free plan
> to a paid plan with a pay-as-you-go pricing and **your free tier credits expire
> immediately.**

IAM Identity Center requires an AWS **Organization**. Creating an Organization
converts the account to pay-as-you-go and burns the $100 credits on the spot.
Real charges would then land on a personal card.

A second cost was on the same screen: the default multi-Region instance
provisions a **customer-managed KMS key**, ~$1/month on its own.

**We did not click Enable.** Recorded in
[ADR 0003](decisions/0003-iam-user-instead-of-identity-center.md).

**The lesson, and it recurs three times in this project:** *security best
practice is written for the unconstrained case.* The "recommended" button often
has a price tag. Knowing why you deviated, and what you did to compensate, is
the actual skill.

### Trap 3 — "IAM access to billing" hides on a different page

Non-root users can't see billing data unless root enables it first. The setting
is **not** in the Billing console, despite the name. It's on the **Account**
page:

```
https://us-east-1.console.aws.amazon.com/billing/home#/account
```

For newer accounts it's on by default. It's also self-verifying — if it were
off, the guardrails script would fail with `AccessDenied`, so it wasn't worth
hunting for.

### Trap 4 — `aws login` vs `aws configure`

Having ruled out Identity Center, the plan was an IAM user with a long-lived
access key. Then the AWS CLI printed this on its own:

```
Tip: You can deliver temporary credentials to the AWS CLI using your AWS
Console session by running the command 'aws login'.
```

`aws login` brokers **temporary session credentials** from your browser console
session. No access key is written to disk at all.

This is what Identity Center was supposed to provide, without the Organization
requirement and without touching the free plan. It made ADR 0003's accepted risk
disappear entirely.

Check the flow it opens:

```
redirect_uri=http://127.0.0.1:51166/oauth/callback
```

The callback is **localhost**. Credentials go from AWS straight to the CLI
process on your machine — they never pass through a third-party server. That's
the correct design for this kind of handoff, and worth recognizing when you see it.

### Trap 5 — `aws login` grabbed the root session

The first `aws login` printed:

```
Updated profile default to use arn:aws:iam::428625199448:root credentials.
```

It picked up whichever console session existed — and that was **root**. Only
after signing into the console as `sudhamsh-admin` and answering `y` to an
overwrite prompt did the profile become:

```
arn:aws:iam::428625199448:user/sudhamsh-admin
```

This is exactly why `scripts/00-guardrails.sh` refuses to run as root:

```bash
if [[ "$ARN" == *":root" ]]; then
  echo "ERROR: These are ROOT credentials..." >&2
  exit 1
fi
```

The check didn't have to fire, because the problem was caught first. But the
near-miss is the point: **a tool that silently uses the wrong identity is worse
than one that fails loudly.**

### What Stage 0 produced

Two budgets, verified independently:

| Budget | Limit | Alert |
|---|---|---|
| `job-radar-any-spend` | $0.01 | ACTUAL > 100% — "you spent literally anything" |
| `job-radar-one-dollar` | $1.00 | FORECASTED > 100% — "AWS predicts you'll exceed $1" and ACTUAL > 80% |

**Why a forecasted alert matters:** an actual-spend alarm tells you what already
happened. A forecast alarm warns you while there's still time to act.

**Why `IncludeCredit: false`:** with credits included, $100 of real spend shows
as $0 and every budget stays silent until the money is gone. With credits
excluded, the budget fires on the first cent of *real* cost even though credits
absorb it — which is the early warning that you've drifted off the free path.

### Why the guardrails are not Terraform

Recorded in [ADR 0001](decisions/0001-guardrails-live-outside-terraform.md).

1. **A safety net can't depend on the thing it's catching.** If Terraform state
   is corrupted or destroyed, Terraform-managed budgets go with it — exactly
   when they're most needed.
2. **Ordering.** Guardrails must exist before the first resource. Terraform
   can't be first because it needs a state backend, which is itself a resource.
3. **`terraform destroy` must never remove them.** Tearing down to zero is
   routine here. The budgets have to survive it.

> **Guardrails belong outside the system they guard.**

---

## 4. Stage 1 — the Terraform state backend

### What Terraform state is, and why remote state matters

Terraform records what it created in a **state file** — a JSON map from your
config to real resource IDs. Without it, Terraform has no idea that
`aws_s3_bucket.tfstate` in your code is the bucket that already exists, and
would try to create it again.

Local state has three problems:
- It lives on one laptop. Lose the laptop, lose the map.
- Two people (or you and CI) can apply simultaneously and corrupt it.
- It can't be shared.

Remote state in S3 fixes all three.

### The chicken-and-egg problem

Terraform needs the S3 bucket to store state. The bucket is itself a resource
Terraform should manage. Which comes first?

**Solution:** a separate root module, `bootstrap/`, applied once by hand.

1. First apply: **no** `backend` block. State is written locally.
2. The bucket now exists.
3. Add the `backend` block pointing at that bucket.
4. `terraform init -migrate-state` moves the local state *into the bucket it
   just created*.

Verified:

```
$ aws s3 ls s3://job-radar-tfstate-428625199448/ --recursive
2026-08-12 15:32:22   8759 bootstrap/terraform.tfstate

$ terraform plan -detailed-exitcode
No changes. Your infrastructure matches the configuration.
```

Bootstrap now manages its own backend. Same shape as ADR 0001, one layer up:
**bootstrap problems are solved by running once out-of-band, then adopting the
result.**

### Native S3 locking — the thing every tutorial gets outdated on

**Locking** stops two applies running at once. Terraform takes a lock, applies,
releases.

Every older tutorial provisions a **DynamoDB table** purely to hold a lock row.
Terraform 1.10+ doesn't need it — S3 supports conditional writes directly:

```hcl
backend "s3" {
  bucket       = "job-radar-tfstate-428625199448"
  key          = "bootstrap/terraform.tfstate"
  region       = "us-east-1"
  encrypt      = true
  use_lockfile = true      # native S3 locking, no DynamoDB table
}
```

Two benefits, and the second is specific to us:

1. One less resource to manage.
2. **It preserves free-tier capacity.** DynamoDB's always-free allowance is
   25 RCU + 25 WCU *for the whole account*. A lock table would eat part of the
   budget the application's own table needs.

### Bucket settings and the reasoning for each

| Setting | Why |
|---|---|
| `prevent_destroy = true` | `terraform destroy` in an environment must never remove the record of what exists. Removing it requires a deliberate code edit. |
| Versioning enabled | The actual recovery mechanism for state corruption — roll back to a previous object version. |
| **SSE-S3 (AES256), not SSE-KMS** | State files hold resource attributes in plaintext. In project 1, gitleaks caught Log Analytics shared keys inside a state backup — that's what state files look like. A customer-managed KMS key costs ~$1/mo; AES256 is free and still encrypts at rest. |
| All four public-access blocks | A world-readable state file is a complete inventory of your account. |
| Noncurrent versions expire at 30d | Versioning otherwise keeps every historical state forever, consuming free-tier storage for nothing. |

Note the KMS decision is the **third** time in this project that "more secure"
carried a price tag (after Organizations and the multi-Region KMS key).

### Verified, not assumed

```
$ checkov -d bootstrap
Passed checks: 7, Failed checks: 0

$ aws s3api get-bucket-versioning  --bucket ...   → Status: Enabled
$ aws s3api get-bucket-encryption  --bucket ...   → AES256, BucketKeyEnabled
$ aws s3api get-public-access-block --bucket ...  → all four true
```

Reading the apply output is not verification. Asking AWS what actually exists is.

### One more thing that got fixed here

The `.gitignore` ignores **both** `*.tfplan` and a bare `tfplan`:

```gitignore
*.tfplan
tfplan
tfplan.*
```

In project 1, a file literally named `tfplan` (no extension) slipped past a
`*.tfplan` rule and got committed. Plan files embed resolved values and can leak
secrets. Confirmed working — `git status --ignored` shows `bootstrap.tfplan` and
both state files as ignored, while `.terraform.lock.hcl` is correctly **tracked**
(it pins provider hashes for reproducible builds).

---

## 5. Stage 2 — picking job sources

### Tested, not guessed

24 endpoints were called before anything went into config. Result:

| Source | Verdict | Evidence |
|---|---|---|
| **Greenhouse** | accepted | 12 of 16 boards live |
| **RemoteOK** | accepted | 101 items; requires a `User-Agent` header |
| **HN Who Is Hiring** (Algolia) | accepted | responds |
| **Lever** | **rejected** | 6 of 7 companies 404; `plaid` returned an empty array |

Greenhouse board tokens are **not** derivable from company names. `hashicorp`,
`confluent`, `snowflake`, and `doordash` all 404 while `grafanalabs`,
`circleci`, and `pagerduty` work. Writing a plausible-looking list into a config
file would have produced a pipeline that silently ingested nothing.

Lever was dropped **on evidence**. A source returning nothing still costs a code
path, a failure mode, and a test.

### The premise, validated with real data

Filtering live boards for DevOps-relevant titles:

```
grafanalabs   20 / 146      mongodb       22 / 416
elastic       14 / 252      datadog        9 / 441
databricks     6 / 807      reddit         5 / 154
gitlab         3 / 197      fastly         3 /  53
stripe         1 / 565

83 matching roles across live boards
```

### Why three sources that disagree with each other

This is the most deliberate design choice in the project.

- **Greenhouse** → an object with a `jobs` array of clean structured fields.
- **RemoteOK** → a bare array whose **first element is a legal notice, not a
  job.** Assume every element is a posting and you silently corrupt your dataset.
- **Hacker News** → *comments*. Unstructured prose. No fields at all.

Normalizing three genuinely different shapes into one record schema is the
actual engineering. One well-behaved source would have made this a
data-copying exercise.

It also forces a real design decision downstream: sources break without warning
when companies switch ATS vendors. Ingest must treat a dead source as a
**partial failure** — logged and alarmed, never a reason to fail the whole run.
That's what motivates SQS + a dead-letter queue in the next stage, rather than
bolting them on because the tutorial said to.

---

## 6. Every mistake made, and what it taught

Kept deliberately, because this is the most useful section for interviews.

### `brew install awscli checkov tflint` installed nothing

`tflint` isn't a core Homebrew formula. Brew rejected the **entire** command on
the unknown name — one bad argument, zero packages installed.

**And the exit code was 0.** The command was piped to `tail`, and a shell
pipeline reports the *last* command's status. `tail` succeeded, so the failure
was invisible.

> **Lesson:** in a pipeline, `$?` is the last command's status. Use
> `set -o pipefail`, or check the raw output. This is the same class of error as
> project 1's Loki incident, where a `curl` missing `-G` produced a misleading
> result that got blamed on the system.

### Guessing at install paths twice

The guessed tap `terraform-linters/homebrew-tflint` doesn't exist either.

**Correct response:** stop guessing and re-scope. `tflint` isn't needed until
Stage 8, and there it runs as a GitHub Action requiring no local install. The
task was deferred rather than forced.

> **Lesson:** two failed guesses is the signal to question the requirement, not
> to make a third guess.

### Telling you Organizations was "expected, automatic, and free"

It wasn't. It would have expired $100 of credits and converted the account to
pay-as-you-go. The console banner said so plainly.

> **Lesson:** the screen in front of you outranks anyone's recollection,
> including a confident one. You caught this by reading rather than clicking.

### Commands typed into a live prompt

`aws configure` was open and waiting. The next commands went **into the
prompts**, so `~/.aws/credentials` ended up containing:

```
aws_access_key_id     = aws configure set region us-east-1 && ...
aws_secret_access_key = aws login
```

`aws login` then refused to run:

```
Profile 'default' is already configured with Access Key credentials.
You may run 'aws login --profile new-profile-name' ...
```

> **Lesson, and it's about tool design:** the CLI *refused to overwrite* an
> existing credential and named the exact conflict plus the workaround. The
> failure mode of "helpfully replaced your working credentials" would have been
> far worse. Notice what good tooling does with an ambiguous situation.

---

## 7. Glossary

Terms used above, in plain language.

| Term | Meaning |
|---|---|
| **IAM** | AWS's permission system. Who can do what to which resource. |
| **Root user** | The account's original login. Unlimited power, cannot be restricted. Give it MFA, then never use it. |
| **IAM user** | A normal identity with a scoped policy. `sudhamsh-admin` here. |
| **MFA** | Second factor beyond a password. |
| **ARN** | Amazon Resource Name — a globally unique ID. `arn:aws:iam::428625199448:user/sudhamsh-admin`. |
| **Terraform state** | JSON file mapping your config to real resource IDs. Terraform's memory. |
| **Backend** | Where state is stored. Ours is S3. |
| **State locking** | Prevents two applies at once. |
| **`terraform plan`** | Shows what *would* change. **Validates configuration, not authorization** — project 1's central lesson. |
| **`terraform apply`** | Actually makes the changes. |
| **Idempotent** | Safe to run repeatedly with the same result. |
| **ADR** | Architecture Decision Record — a short doc capturing a decision and its reasoning. |
| **Always-free tier** | AWS services free forever within limits (as opposed to 12-month trials). |
| **SSE-S3 / SSE-KMS** | S3 encryption at rest. SSE-S3 (AES256) is free; SSE-KMS with a customer key costs ~$1/mo. |
| **DLQ** | Dead-letter queue — where messages go after repeated processing failures, so one bad message can't block a queue forever. |
| **OIDC** | Lets GitHub Actions get short-lived AWS credentials without stored secrets. Stage 8. |
| **checkov** | Scans Terraform for insecure configuration before apply. |

---

## 8. Interview questions this project answers

Practise saying these out loud. The answers are yours — you made these calls.

**"Why isn't everything in Terraform?"**
> Cost guardrails are deliberately outside it. A safety net can't depend on the
> thing it's catching — if state is lost or corrupted, Terraform-managed budgets
> go with it, exactly when they're needed. And they must survive
> `terraform destroy`.

**"How do you bootstrap remote state?"**
> Separate root module with no backend block, applied once to local state. Then
> add the backend block and `terraform init -migrate-state` to move state into
> the bucket it just created.

**"How do you handle state locking?"**
> Native S3 conditional writes, `use_lockfile = true`, Terraform 1.10+. The
> older DynamoDB lock table is unnecessary — and on this account it would have
> consumed part of the 25 RCU/WCU always-free allowance the app's table needs.

**"How do you manage AWS credentials on a laptop?"**
> `aws login` brokers temporary session credentials from the console session —
> nothing on disk. I'd have used Identity Center, but it requires an
> Organization, and creating one would have expired this account's free-tier
> credits. CI never uses these credentials at all; GitHub Actions uses OIDC.

**"Why SSE-S3 instead of KMS on your state bucket?"**
> A customer-managed KMS key is ~$1/month against a $0 budget. AES256 still
> encrypts at rest. Managed keys would be right on a funded account.

**"How do you keep serverless costs from surprising you?"**
> Budgets before any resource existed, with credits *excluded* so alerts fire on
> real cost rather than post-credit cost, and a forecast alert so I hear about it
> before the money is gone.

**"Tell me about something that broke."**
> Pick from section 6. The `brew` pipeline exit code is the strongest — a
> command that installed nothing and reported success, because `$?` in a
> pipeline is the last command's status, not the failing one.

---

*Stages 0–2 complete. Next: the ingest Lambda, normalization across three source
shapes, pytest with `moto`, then Terraform for the schedule and DynamoDB table.*
