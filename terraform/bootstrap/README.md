# Bootstrap module

One-time setup that prepares an AWS account for deploying the GovWin -> HubSpot -> AWS Partner Central integration with proper least-privilege IAM. Run this **once per environment** (e.g. once for dev, once for prod) before running anything in `terraform/`.

## Production MFA gate

The deployer role's trust policy requires MFA on assume by default. The bootstrap module enforces this with a Terraform `precondition`: apply fails if `environment = "prod"` is paired with `require_mfa_to_assume_deployer = false`.

### Why MFA on the assume call

The deployer role can update Lambda code, IAM policies, secrets, DynamoDB tables, and the public-facing webhook API for the entire integration. A leaked access key with `sts:AssumeRole` on the deployer ARN is a full account compromise vector. MFA on the assume converts a leaked-key incident from "attacker has a working session" into "attacker also needs the user's MFA device". This is the difference between a recoverable credential rotation and a forensics engagement.

It also satisfies compliance requirements that apply directly to Pandora Cloud's federal contracting work: NIST 800-53 IA-2(1) (multi-factor authentication for privileged accounts), CMMC L2 control IA.L2-3.5.3 (MFA for privileged access), and SOC 2 CC6.6. Without MFA on the deployer, those controls are not implemented for this account, and any audit will flag it.

### When you can flip it off

For an account that is genuinely sandbox-only (no real Partner Central submissions, no PII/CUI, just smoke testing), MFA on the assume call adds friction without protecting anything that matters. Two ways to disable it:

1. `require_mfa_to_assume_deployer = false` together with `environment` set to something other than `prod` (`dev`, `sandbox`, etc.). The precondition only fires when environment is exactly `prod`.
2. Keep `environment = "prod"` and explicitly set `acknowledge_no_mfa_for_sandbox_only = true`. This is the documented escape hatch for accounts where the resource naming has to look like prod (because a future flip to real production is planned in the same account) but real production data hasn't started flowing yet.

Both paths leave a record: the variable name itself documents the trade-off. Before any real Partner Central data lands in the account, flip both back so the MFA gate engages.

## What it creates

| Resource | Purpose |
|---|---|
| S3 bucket | Holds the main Terraform state file. Versioned, public-access blocked, encrypted with the AWS-managed `aws/s3` KMS key, native S3 lockfile (Terraform >= 1.10 `use_lockfile = true`). |
| IAM role | The **deployer role**. Day-to-day `terraform apply` assumes this role. Its inline policy is the project's least-privilege deploy manifest. |
| (no DynamoDB lock table) | Native S3 lockfile replaces it as of Terraform 1.10. |

## Who runs this

Two distinct identities are involved:

1. **Bootstrap operator** (one-time): an IAM user/role with the permissions in `policies/bootstrap-operator.json`. Your security team creates this temporarily, the deployer runs `terraform apply` in this directory once, then the security team deletes it.
2. **Day-to-day deployer principal** (every apply): a regular IAM user/role that has only `sts:AssumeRole` on the deployer role's ARN. Lists of allowed principals are passed in via `deployer_principal_arns`.

After bootstrap is done, no one needs the bootstrap-operator credentials again.

## How to run

### Step 1: Security team creates a temporary IAM user

```bash
# Create a user with no console access
aws iam create-user --user-name govwin-hubspot-bootstrap

# Attach the bootstrap-operator policy. The JSON is checked in at
# terraform/bootstrap/policies/bootstrap-operator.json so it can be
# audited and version-controlled.
aws iam put-user-policy \
  --user-name govwin-hubspot-bootstrap \
  --policy-name BootstrapOperator \
  --policy-document file://terraform/bootstrap/policies/bootstrap-operator.json

# Generate access keys, hand them to the deployer
aws iam create-access-key --user-name govwin-hubspot-bootstrap
```

### Step 2: Deployer runs the bootstrap

```bash
cd terraform/bootstrap

# Configure the bootstrap-operator credentials in your shell or a profile
export AWS_PROFILE=govwin-hubspot-bootstrap
# (or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY directly)

cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set deployer_principal_arns to the IAM users/roles
# that should be allowed to assume the deployer role for day-N applies.

terraform init
terraform plan
terraform apply
```

Outputs:

```
state_bucket_name        = "govwin-hubspot-prod-tfstate-<random>"
deployer_role_arn        = "arn:aws:iam::<account>:role/govwin-hubspot-prod-deployer"
deployer_assume_command  = "aws sts assume-role --role-arn ... --role-session-name ..."
```

### Step 3: Wire the outputs into the main Terraform

Copy the state bucket name into `terraform/backend.tf` (use `terraform/backend.tf.example` as a starting point):

```hcl
terraform {
  backend "s3" {
    bucket       = "govwin-hubspot-prod-tfstate-<random>"
    key          = "govwin-hubspot/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
    role_arn     = "arn:aws:iam::<account>:role/govwin-hubspot-prod-deployer"
  }
}
```

And set `deployer_role_arn` in `terraform/terraform.tfvars`. The provider block in `terraform/provider.tf` will assume that role for resource creation.

### Step 4: Security team deletes the bootstrap user

```bash
aws iam delete-access-key --user-name govwin-hubspot-bootstrap --access-key-id <id>
aws iam delete-user-policy --user-name govwin-hubspot-bootstrap --policy-name BootstrapOperator
aws iam delete-user --user-name govwin-hubspot-bootstrap
```

The bootstrap is done. Going forward, every `terraform apply` in `terraform/` (the main module) goes through the deployer role, with audit logs showing who-assumed-what.

## Migrating an existing Terraform state to the new bucket

If you already have a state file in another bucket and want to move it to the bootstrap-managed bucket:

```bash
cd terraform
# Update backend.tf to point at the new bucket
terraform init -migrate-state
```

Terraform copies the state into the new bucket and updates the local pointer.

## Why a bootstrap module instead of just instructions

Pandora Cloud is a security-and-compliance shop. The IAM policies in `policies/` are the project's actual permission model, version-controlled, code-reviewable, and reviewable by federal compliance auditors. A markdown blob of copy-pasted JSON is fragile: it drifts from what the code requires, and reviewers can't tell whether what's documented matches what's deployed. Code wins.

## Re-running bootstrap

The bootstrap is mostly idempotent: re-running with the same variables is a no-op. If you change `deployer_principal_arns` (e.g. add or remove a person from the deployer list), re-run bootstrap with the bootstrap-operator credentials to update the trust policy.
