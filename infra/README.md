# infra/

Terraform for the WMS chatbot's GCP infrastructure.

## Layout

```
infra/
├── Makefile                     # Wraps common terraform commands per env.
├── modules/                     # Reusable building blocks — no state of their own.
│   ├── artifact_registry/       # Docker registry for CI to push images into.
│   ├── cloud_run_service/       # Cloud Run service + its runtime service account.
│   ├── cloud_sql/               # Postgres 16 (private IP) + user + password → secret version.
│   ├── memorystore_redis/       # Redis in the VPC (BASIC tier, no auth on private net).
│   ├── network/                 # VPC + subnet + private services access + VPC connector.
│   └── secrets/                 # Secret Manager containers + IAM for the runtime SA.
└── envs/
    └── staging/                 # Root module for the staging environment.
        ├── backend.tf           # GCS remote state — bucket passed via -backend-config.
        ├── main.tf              # Wires the modules together.
        ├── variables.tf         # Env-level inputs.
        ├── outputs.tf           # URLs, DB connection, image base — consumed by CI.
        └── terraform.tfvars.example
```

Prod will be added later as a sibling of `envs/staging/`. Modules stay shared.

## First-time setup

See [`docs/deploy.md`](../docs/deploy.md) for the bootstrap runbook (create the GCP project, state bucket, and enable prerequisite APIs before the first `terraform apply`).

## Everyday commands

The Makefile is the shortest path — from `infra/`:

```bash
make init TF_STATE_BUCKET=wms-chatbot-staging-tfstate   # one-time
make plan
make up                                                  # apply
make down                                                # destroy — zero the bill
make output
```

`ENV` defaults to `staging` — later prod work will use `ENV=prod make up` against `envs/prod/`.

Raw terraform still works from `infra/envs/staging/` if you prefer:

```bash
terraform init -backend-config="bucket=<your-tf-state-bucket>"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## Sprint 1.7 scope

- **PR2 (merged)**: Artifact Registry, Cloud Run (placeholder image), Secret Manager containers.
- **PR3 (this)**: VPC network + Serverless VPC Access connector, Cloud SQL Postgres (private IP), MemoryStore Redis, wiring into Cloud Run. Makefile wrapper.
- **PR4 (next)**: GitHub Actions deploy workflow (build image → push to Artifact Registry → deploy Cloud Run revision).
- **PR5**: Monitoring dashboard, Sentry, Cloud Storage + CDN for embed JS.

## Cost note

Running the full staging stack (Cloud SQL db-f1-micro + MemoryStore BASIC 1GB + VPC connector 2× e2-micro) is ~$50/month even at zero traffic — those are provisioned resources, not pay-per-request like Cloud Run. Use `make down` when you're pausing work for a day or more.
