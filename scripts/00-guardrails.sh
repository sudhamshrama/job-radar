#!/usr/bin/env bash
#
# Stage 0 — cost guardrails. Run this ONCE, before any Terraform exists.
# See docs/decisions/0001-guardrails-live-outside-terraform.md for why this is
# not Terraform.
#
# Idempotent: safe to re-run. There is no state file, so it checks AWS directly.
#
#   ./scripts/00-guardrails.sh
#   ALERT_EMAIL=someone@example.com ./scripts/00-guardrails.sh
#
set -euo pipefail

ALERT_EMAIL="${ALERT_EMAIL:-sudhamshrama03@gmail.com}"
TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT

# --- Identity check -----------------------------------------------------------
echo "==> Checking AWS identity"
if ! IDENTITY="$(aws sts get-caller-identity --output json 2>&1)"; then
  echo "ERROR: aws sts get-caller-identity failed. Configure credentials first:" >&2
  echo "  aws configure   (or aws configure sso)" >&2
  echo "$IDENTITY" >&2
  exit 1
fi

ACCOUNT_ID="$(echo "$IDENTITY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Account"])')"
ARN="$(echo "$IDENTITY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Arn"])')"

echo "    account: $ACCOUNT_ID"
echo "    arn:     $ARN"

# Root has an ARN of the form arn:aws:iam::123456789012:root
if [[ "$ARN" == *":root" ]]; then
  echo "ERROR: These are ROOT credentials. Root should have MFA and then never" >&2
  echo "       be used again. Create an IAM/Identity Center admin user and" >&2
  echo "       re-run with those credentials." >&2
  exit 1
fi

# --- Budgets ------------------------------------------------------------------
# Threshold is a PERCENTAGE of the budget limit.
#   $0.01 budget, ACTUAL > 100%   -> "you have spent literally anything"
#   $1.00 budget, FORECASTED>100% -> "AWS predicts you will exceed $1 this month"
#                 ACTUAL     > 80% -> "you are nearly there right now"

create_or_update_budget() {
  local name="$1" amount="$2" notifications_json="$3"

  cat >"$TMPDIR_LOCAL/budget.json" <<EOF
{
  "BudgetName": "$name",
  "BudgetLimit": { "Amount": "$amount", "Unit": "USD" },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostTypes": {
    "IncludeTax": true,
    "IncludeSubscription": true,
    "UseBlended": false,
    "IncludeRefund": false,
    "IncludeCredit": false,
    "IncludeUpfront": true,
    "IncludeRecurring": true,
    "IncludeOtherSubscription": true,
    "IncludeSupport": true,
    "IncludeDiscount": true,
    "UseAmortized": false
  }
}
EOF
  echo "$notifications_json" >"$TMPDIR_LOCAL/notifications.json"

  if aws budgets describe-budget \
        --account-id "$ACCOUNT_ID" --budget-name "$name" >/dev/null 2>&1; then
    echo "==> Budget '$name' exists, updating limit to \$$amount"
    aws budgets update-budget \
      --account-id "$ACCOUNT_ID" \
      --new-budget "file://$TMPDIR_LOCAL/budget.json" >/dev/null
  else
    echo "==> Creating budget '$name' at \$$amount"
    aws budgets create-budget \
      --account-id "$ACCOUNT_ID" \
      --budget "file://$TMPDIR_LOCAL/budget.json" \
      --notifications-with-subscribers "file://$TMPDIR_LOCAL/notifications.json" >/dev/null
  fi
}

# NOTE on IncludeCredit=false: Azure-for-Students-style credits would otherwise
# mask real spend. We want to know what this project actually costs, not what it
# costs after credits are applied.

create_or_update_budget "job-radar-any-spend" "0.01" "$(cat <<EOF
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" }
    ]
  }
]
EOF
)"

create_or_update_budget "job-radar-one-dollar" "1.00" "$(cat <<EOF
[
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" }
    ]
  }
]
EOF
)"

# --- Verify -------------------------------------------------------------------
echo
echo "==> Budgets now on account $ACCOUNT_ID:"
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit.Amount,Unit:BudgetLimit.Unit}' \
  --output table

echo
echo "Done. Alerts go to: $ALERT_EMAIL"
echo "Budget alerts are best-effort and lag billing by hours. They are a smoke"
echo "detector, not a spending cap. Check Cost Explorer weekly regardless."
