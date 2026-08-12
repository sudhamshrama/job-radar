# Runbook

Operational procedures for `job-radar`. Written to be followed at 2am.

---

## Quick reference

| What | Where |
|---|---|
| Dashboard | https://d18zgxdvd2esd3.cloudfront.net |
| API | https://4uex57qv6c.execute-api.us-east-1.amazonaws.com/jobs |
| CloudWatch dashboard | `job-radar-dev` (us-east-1) |
| Account | `428625199448`, **us-east-1** |
| State bucket | `job-radar-tfstate-428625199448` |
| Alerts | SNS `job-radar-dev-alerts` → sudhamshrama03@gmail.com |

**The console defaults to whichever region you last used. Everything here is
in us-east-1.** An empty-looking account is almost always the wrong region.

---

## Credentials

Credentials are temporary and expire. When AWS calls start failing with auth
errors:

```bash
aws login
```

Check what you got — the first `aws login` of a session frequently picks up a
**root** console session:

```bash
aws sts get-caller-identity     # want .../user/sudhamsh-admin, NOT :root
```

`scripts/00-guardrails.sh` refuses to run as root by design.

---

## Force an ingest run

Ingest runs every 6 hours. To run it now:

```bash
aws lambda invoke --function-name job-radar-dev-ingest \
  --cli-read-timeout 700 /dev/stdout
```

Healthy output:

```json
{"sources_total": 94, "sources_failed": 0,
 "jobs_before_us_filter": 478, "jobs_written": 270, "failures": []}
```

`sources_failed` being non-zero is **normal**. Companies retire job boards
without notice. Only a total failure raises and alarms.

---

## Alarms and what to do

| Alarm | Means | Action |
|---|---|---|
| `ingest-total-failure` | **Every** source failed — systemic | Check network/permissions, not a board. Invoke manually and read the error. |
| `ingest-not-running` | No invocations in 24h | The schedule stopped firing. Check `aws scheduler get-schedule --name job-radar-dev-ingest`. |
| `notify-dlq-not-empty` | Records failed processing 3× | See below. Ingest is fine; notifications are silently broken. |

### Investigating a failed source

Structured JSON logging is what makes this queryable:

```bash
aws logs tail /aws/lambda/job-radar-dev-ingest --since 6h --format short \
  | grep 'source failed'
```

A single board 404ing means the company moved ATS. Remove it from
`src/config/sources.json` — board tokens are config, not code.

### Draining the notify DLQ

```bash
# How many, and what?
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name job-radar-dev-notify-dlq --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages

# After fixing the handler bug, redrive:
aws sqs start-message-move-task --source-arn <dlq-arn>
```

Messages expire after 14 days. That is the window to act, not a suggestion.

---

## Changing the filters

Keywords, job boards and the US-only toggle all live in
`src/config/sources.json`. Editing them requires a deploy (the file is bundled
into the Lambda zip), but not a code change.

**A filter change does NOT clean existing data.** Filters apply at write time,
so rows written under the old rules stay until their 90-day TTL expires. After
tightening a filter, purge and re-ingest:

```bash
python3 - <<'PY'
import boto3
t = boto3.resource("dynamodb", region_name="us-east-1").Table("job-radar-dev-jobs")
n = 0
with t.batch_writer() as b:
    resp = t.scan(ProjectionExpression="pk,sk")
    while True:
        for i in resp["Items"]:
            b.delete_item(Key={"pk": i["pk"], "sk": i["sk"]}); n += 1
        if "LastEvaluatedKey" not in resp: break
        resp = t.scan(ProjectionExpression="pk,sk", ExclusiveStartKey=resp["LastEvaluatedKey"])
print("deleted", n)
PY
```

Then force an ingest run. This was learned the hard way — 103 pre-filter rows
sat in the table looking like filter bugs.

> `boto3` in the local venv needs `pip install "botocore[crt]"` to read
> `aws login` credentials. The AWS CLI bundles it; a plain pip install does not.

---

## Cost checks

```bash
aws budgets describe-budgets --account-id 428625199448 \
  --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit.Amount}' --output table

aws ce get-cost-and-usage --time-period Start=2026-08-01,End=2026-09-01 \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE --output json
```

Spend as of 2026-08-12: **$0.00**.

Do this weekly. Budget alerts lag billing by hours and are a smoke detector,
not a spending cap.

**Free plan expires 2027-02-10.** AWS suspends service rather than billing.
The dashboard URL will go dark then — the README screenshots and recorded demo
exist so the project still reads afterwards.

---

## Teardown and rebuild

### Before you run destroy — read this

**A full `terraform destroy` of `envs/dev` will fail partway.**

`aws_iam_openid_connect_provider.github` carries `prevent_destroy = true`.
Terraform will delete other resources first and then refuse on that one,
leaving the environment half-destroyed.

This is a **design flaw in this repo, honestly recorded**: the OIDC provider is
an *account-level* resource (one per AWS account, shared by every workflow)
that was put in an *environment* configuration. It belongs in a separate
`infra/shared/` root module alongside the state backend. It is not moved
because doing so requires a state migration, and the correct fix is worth more
as a documented lesson than as a rushed change.

**The general lesson:** account-scoped resources do not belong in per-environment
configurations. If two environments existed, the second would fail to create
the provider because it already exists.

### Destroying anyway

```bash
cd infra/envs/dev

# 1. Remove the account-level resource from state (it survives, unmanaged).
terraform state rm aws_iam_openid_connect_provider.github

# 2. Destroy the rest.
terraform destroy -auto-approve

# 3. The state bucket is NOT touched — it also has prevent_destroy (ADR 0002).
```

CloudFront takes ~15 minutes to delete. **The CloudFront domain is not
recoverable** — a rebuild produces a new `*.cloudfront.net` name, so every link
to the dashboard breaks. That is why a full teardown drill has not been run
against this environment: the URL is a portfolio artifact.

### Rebuilding from nothing

```bash
./scripts/00-guardrails.sh                       # budgets first, always
cd bootstrap && terraform init && terraform apply # state backend
cd ../infra/envs/dev && terraform init && terraform apply
aws lambda invoke --function-name job-radar-dev-ingest --cli-read-timeout 700 /dev/stdout
```

Then update the dashboard URL in `README.md` and `docs/RUNBOOK.md`.

**Verified:** `terraform plan -destroy` enumerates **45 resources** with no
orphans, so the configuration accounts for everything that exists.
