# job-radar

An event-driven job-posting pipeline on AWS, defined entirely in Terraform.

Scheduled ingestion from public job-board APIs → normalize → store → serve,
with a static dashboard over a read API. Runs inside the AWS always-free tier.

### 🔗 Live: **https://d18zgxdvd2esd3.cloudfront.net**

> **Status: complete.** Ingest runs every 6 hours across **94 sources** and
> holds **~270 US DevOps roles**. Total AWS spend: **$0.00**.

```
$ aws lambda invoke --function-name job-radar-dev-ingest /dev/stdout
{ "sources_total": 94, "sources_failed": 0, "jobs_before_us_filter": 478,
  "jobs_found": 270, "jobs_written": 270, "failures": [] }
```

## Why this exists

I was applying to a few hundred DevOps roles and wanted one place that pulled
postings from the boards I cared about. It also happens to be the shape of
problem that exercises the parts of AWS that interviews actually probe: IAM,
event-driven decoupling, retries and dead letters, and DynamoDB key design.

## Planned architecture

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

Sources are documented public JSON APIs — Greenhouse job boards, Lever postings,
Hacker News "Who is Hiring" via Algolia, and RemoteOK. No scraping.

## Cost posture

The account budget for this project is **$0**. Every component sits in an AWS
always-free tier, with two exceptions that are tracked explicitly:

| Service | Free allowance | Notes |
|---|---|---|
| Lambda | 1M req + 400k GB-s/mo | always free |
| SQS | 1M req/mo | always free |
| DynamoDB | 25 GB + 25 RCU/WCU | always free — **provisioned mode only** |
| SNS | 1,000 email notifications/mo | always free |
| CloudFront | 1 TB + 10M req/mo | always free |
| X-Ray | 100k traces/mo | always free |
| API Gateway (HTTP) | 1M req/mo | ⚠️ **12 months only** |
| S3 | 5 GB | ⚠️ **12 months only** |

Deliberately avoided: EKS (~$73/mo control plane), NAT Gateway (~$32/mo),
Route 53 hosted zones ($0.50/mo).

Guardrails are created before any resource exists — see
[ADR 0001](docs/decisions/0001-guardrails-live-outside-terraform.md).

## Repository layout

```
bootstrap/        Terraform state backend (run once, separately)
infra/modules/    reusable Terraform modules
infra/envs/       dev and prod compositions
src/handlers/     Lambda entry points
src/common/       shared code
tests/            pytest, AWS mocked with moto
scripts/          one-time operational scripts
docs/decisions/   ADRs
docs/screenshots/ evidence for each stage
```

## Setup

Requires: AWS account, `aws` CLI v2, Terraform ≥ 1.15, Python 3, `checkov`.

```bash
aws configure          # non-root credentials
./scripts/00-guardrails.sh
```

The guardrails script refuses to run with root credentials and is idempotent.

## Stages

| # | Stage | Status |
|---|---|---|
| 0 | Account guardrails and tooling | ✅ done |
| 1 | Terraform state backend bootstrap | ✅ done |
| 2 | Ingest logic, local, with tests | ✅ done |
| 3 | First deploy — schedule → Lambda → DynamoDB | ✅ done |
| 4 | Idempotent writes; DLQ deferred to the notify path (see below) | ✅ done |
| 5 | Read path — HTTP API + query Lambda | ✅ done |
| 6 | Dashboard on S3 + CloudFront | ✅ done |
| 7 | Observability — structured logs, X-Ray, dashboard, alarms | ✅ done |
| 8 | CI/CD — OIDC, plan-on-PR, apply-on-merge, checkov | ✅ done |
| 9 | Cost review, teardown runbook, write-up | ✅ done |

**All nine stages complete.** Full plain-English write-up of every decision and
every bug: **[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)**. Operations:
[docs/RUNBOOK.md](docs/RUNBOOK.md).

## A queue I chose not to build

The original design put SQS between ingest and normalize. It isn't there.

Normalization is in-process and CPU-trivial — parsing JSON and matching
keywords. A queue between those two steps would add a component, an IAM policy,
a retry configuration and a failure mode, while removing none. That is
infrastructure existing because a diagram called for it.

Partial failure, the real problem a queue would have addressed here, is handled
directly: each of the 14 sources is isolated, and one dead board is logged
rather than failing the run. The handler raises only when *every* source fails,
which is the difference between "a company retired its board" and "the network
is gone" — and it is what makes the alarm worth keeping unmuted.

SQS is planned where it genuinely earns its place: as a dead-letter queue on
the DynamoDB Streams notify consumer, where a poison record otherwise blocks a
shard indefinitely.
