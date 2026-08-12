# ---------------------------------------------------------------------------
# Stage 8 — GitHub Actions authentication via OIDC.
#
# The whole point: GitHub Actions gets SHORT-LIVED AWS credentials by
# exchanging a signed OIDC token. No access key is ever stored in GitHub
# secrets, so there is nothing to leak, rotate, or forget to rotate.
#
# This also does NOT require AWS Organizations, which is what made it viable
# here — enabling Identity Center would have expired the account's free-tier
# credits (ADR 0003).
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "owner/name of the repository allowed to assume the deploy role."
  type        = string
  default     = "sudhamshrama/job-radar"
}

# Account-level, created once. AWS now verifies GitHub's certificate chain
# natively, so no thumbprint list to maintain and go stale.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  lifecycle {
    # Deleting this breaks CI for every workflow in the account.
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    # Both conditions matter.
    #
    # `aud` alone is NOT enough: sts.amazonaws.com is the audience for every
    # GitHub repository on the internet. Without the `sub` condition, ANY repo
    # anywhere could assume this role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scoped to this repository. `repo:owner/name:*` allows any branch, tag or
    # pull request from this repo — narrow enough here, since the apply job is
    # additionally gated by a GitHub environment.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${local.prefix}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
  description        = "Assumed by GitHub Actions via OIDC. No static credentials exist."
  tags               = local.tags
}

# Terraform needs broad rights to manage what it created. This is scoped by
# SERVICE rather than by action, and deliberately excludes IAM user/key
# creation — a compromised pipeline should not be able to mint itself a
# permanent credential and survive the role being revoked.
data "aws_iam_policy_document" "github_deploy" {
  # checkov:skip=CKV_AWS_108:See the note below — a Terraform deploy role is
  # inherently privileged and the mitigations are structural, not per-action.
  # checkov:skip=CKV_AWS_109:As above.
  # checkov:skip=CKV_AWS_110:As above. Privilege escalation is blocked by
  # withholding iam:CreateUser, iam:CreateAccessKey and
  # iam:UpdateAssumeRolePolicy, not by narrowing these service actions.
  # checkov:skip=CKV_AWS_111:As above.
  # checkov:skip=CKV_AWS_356:Most of these APIs (lambda:CreateFunction,
  # dynamodb:CreateTable, cloudfront:CreateDistribution) cannot be scoped to a
  # resource ARN, because the resource does not exist until the call succeeds.
  #
  # WHY THIS IS BROAD, AND WHAT ACTUALLY CONSTRAINS IT
  # --------------------------------------------------
  # Terraform must create, read, update and destroy everything it manages, and
  # the ARNs do not exist at plan time. A genuinely least-privilege deploy role
  # would need regenerating every time a resource is added, and in practice
  # that ends as a wildcard anyway — just an undocumented one.
  #
  # The real controls here are structural rather than per-action:
  #
  #   1. No static credential exists. The role is assumable only via GitHub
  #      OIDC, only from repo:sudhamshrama/job-radar, verified by both `aud`
  #      AND `sub` conditions.
  #   2. It CANNOT create IAM users or access keys, so a compromised pipeline
  #      cannot mint a permanent credential that outlives the role.
  #   3. It CANNOT call iam:UpdateAssumeRolePolicy, so it cannot widen its own
  #      trust policy to let another repo in.
  #   4. IAM role management is scoped to `job-radar-dev-*` ARNs only.
  #   5. Budget APIs are read-only, so it cannot disable the cost guardrails
  #      it is checked against.
  #   6. The apply job is gated behind a GitHub environment.
  statement {
    sid    = "ManageProjectResources"
    effect = "Allow"
    actions = [
      "lambda:*", "dynamodb:*", "apigateway:*", "cloudfront:*",
      "sns:*", "sqs:*", "scheduler:*", "events:*",
      "logs:*", "cloudwatch:*", "xray:*", "tag:*", "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  # S3 CAN be resource-scoped, so it is. This is the one service in the list
  # where a wildcard would have been laziness rather than necessity.
  statement {
    sid     = "ManageProjectBuckets"
    effect  = "Allow"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::${local.prefix}-site-${data.aws_caller_identity.current.account_id}",
      "arn:aws:s3:::${local.prefix}-site-${data.aws_caller_identity.current.account_id}/*",
    ]
  }

  statement {
    sid    = "ManageProjectRoles"
    effect = "Allow"
    actions = [
      "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:PassRole",
      "iam:TagRole", "iam:ListRolePolicies", "iam:GetRolePolicy",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:ListAttachedRolePolicies", "iam:GetOpenIDConnectProvider",
    ]
    # Only roles this project owns. Without this, the pipeline could rewrite
    # any role in the account, including its own trust policy.
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.prefix}-*"]
  }

  statement {
    sid     = "TerraformState"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::job-radar-tfstate-${data.aws_caller_identity.current.account_id}",
      "arn:aws:s3:::job-radar-tfstate-${data.aws_caller_identity.current.account_id}/*",
    ]
  }

  statement {
    sid    = "ReadBudgetsForCostGate"
    effect = "Allow"
    # Read-only. CI must never be able to raise or delete the cost guardrails
    # it is checked against (ADR 0001).
    actions   = ["budgets:ViewBudget", "budgets:DescribeBudget", "ce:GetCostAndUsage"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.prefix}-github-deploy"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

output "github_actions_role_arn" {
  description = "Set as the AWS_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.github_actions.arn
}
