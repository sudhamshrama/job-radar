# job-radar

An event-driven job-posting pipeline on AWS, defined entirely in Terraform.

Scheduled ingestion from public job-board APIs → queue → normalize → store →
notify on matches, with a static dashboard over a read API. Built to run inside
the AWS always-free tier.

> **Status: Stage 1 of 9 complete.** This README describes what exists today and
> grows as stages land. Deployed so far: cost budgets and the Terraform state
> backend. No application resources yet.

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
| 2 | Ingest logic, local, with tests | |
| 3 | First deploy — schedule → Lambda → DynamoDB | |
| 4 | Decouple with SQS + DLQ, idempotent writes | |
| 5 | Read path — HTTP API + query Lambda | |
| 6 | Dashboard on S3 + CloudFront | |
| 7 | Observability — structured logs, X-Ray, alarms | |
| 8 | CI/CD — OIDC, plan-on-PR, apply-on-merge, checkov | |
| 9 | Cost review, destroy/rebuild drill, write-up | |
