# State bucket is created out-of-band during bootstrap — see docs/deploy.md.
# `terraform init -backend-config=bucket=<name>` lets the same config be reused
# for future envs without editing this file.
terraform {
  backend "gcs" {
    prefix = "wms-chatbot/staging"
  }
}
