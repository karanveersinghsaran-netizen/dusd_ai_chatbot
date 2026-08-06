# infra/

Terraform for the WMS chatbot's GCP infrastructure.

## Layout

```
infra/
├── modules/                     # Reusable building blocks — no state of their own.
│   ├── artifact_registry/       # Docker registry for CI to push images into.
│   ├── cloud_run_service/       # Cloud Run service + its runtime service account.
│   └── secrets/                 # Secret Manager containers + IAM for the runtime SA.
└── envs/
    └── staging/                 # Root module for the staging environment.
        ├── backend.tf           # GCS remote state — bucket passed via -backend-config.
        ├── main.tf              # Wires the modules together.
        ├── variables.tf         # Env-level inputs.
        ├── outputs.tf           # URL, service name, image base — consumed by CI.
        └── terraform.tfvars.example
```

Prod will be added later as a sibling of `envs/staging/`. Modules stay shared.

## First-time setup

See [`docs/deploy.md`](../docs/deploy.md) for the bootstrap runbook (create the GCP project, state bucket, and Terraform service account before the first `terraform apply`).

## Everyday commands

From `infra/envs/staging/`:

```bash
terraform init \
  -backend-config="bucket=<your-tf-state-bucket>"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## Sprint 1.7 scope

This PR (#10 PR2 of 5) lands only Artifact Registry, Cloud Run (placeholder image), and Secret Manager. Cloud SQL / MemoryStore / VPC connector arrive in the next PR, followed by the deploy workflow and monitoring.
