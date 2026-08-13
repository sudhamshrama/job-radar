# Screenshots

Nobody reading this repo is going to stand up the AWS account to see it work.
These images are how the running system is seen.

Capture on macOS with `Cmd+Shift+4`, save with the exact filenames below so the
README embeds resolve.

| Filename | What to capture | Why it earns its place |
|---|---|---|
| `dashboard-live.png` | The live CloudFront dashboard with roles listed | ✅ captured — the clickable artifact |
| `cloudwatch-dashboard.png` | CloudWatch → Dashboards → `job-radar-dev` | Invocations, duration against the 600s timeout, DynamoDB capacity, DLQ depth |
| `ci-oidc.png` | An Actions run, "Configure AWS credentials via OIDC" step expanded | Proof the pipeline holds no AWS keys |
| `budgets.png` | Billing → Budgets, both budgets listed | The $0.01 and $1 guardrails that exist before any resource does |
| `cost-explorer.png` | Cost Explorer, month to date | $0.00 — the claim the whole project rests on |

Region is **us-east-1**. The console remembers the last region used, so an empty
account view usually means the wrong one is selected.
