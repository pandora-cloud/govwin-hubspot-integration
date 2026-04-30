output "state_bucket_name" {
  description = "Name of the S3 bucket created for Terraform state. Paste into terraform/backend.tf."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_region" {
  description = "Region of the state bucket"
  value       = local.current_region
}

output "deployer_role_arn" {
  description = "ARN of the deployer role. Paste into terraform/backend.tf (role_arn) and terraform/terraform.tfvars (deployer_role_arn)."
  value       = aws_iam_role.deployer.arn
}

output "deployer_role_name" {
  value = aws_iam_role.deployer.name
}

output "next_steps" {
  description = "Copy-pasteable instructions for the deployer to wire up the main module"
  value       = <<-EOT

    Bootstrap complete. Next steps:

    1. Copy these values into terraform/backend.tf (use terraform/backend.tf.example as a starting point):

         bucket   = "${aws_s3_bucket.state.id}"
         role_arn = "${aws_iam_role.deployer.arn}"

    2. Add to terraform/terraform.tfvars:

         deployer_role_arn = "${aws_iam_role.deployer.arn}"

    3. From terraform/, run:

         terraform init    # picks up the new backend
         terraform plan
         terraform apply

    4. Have the security team delete the bootstrap-operator IAM user that
       was used to run this bootstrap. Day-to-day deployments now go through
       sts:AssumeRole on ${aws_iam_role.deployer.arn}.

  EOT
}
