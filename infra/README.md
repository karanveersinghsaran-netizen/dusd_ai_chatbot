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
│   ├── self_hosted_redis/       # Redis on a GCE e2-micro + persistent disk + GCS snapshots.
│   ├── network/                 # VPC + subnet + private services access + VPC connector.
│   └── secrets/                 # Secret Manager containers (IAM binding lives in envs/).
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
make apply                                               # provision infra
make deploy                                              # build image + push + Cloud Run deploy
make destroy                                             # zero the bill — preserves secret values
make destroy-all                                         # nuke everything including secret containers
make output
```

`ENV` defaults to `staging` — later prod work will use `ENV=prod make apply` against `envs/prod/`. `make deploy` uses git short SHA as the tag; override with `TAG=my-tag make deploy` for ad-hoc pushes.

`make destroy` uses `-target` to skip `module.secrets` and the `google_project_service.required` block — so real secret values (populated via `gcloud secrets versions add`) survive destroy/apply cycles, and the next `make apply` doesn't wait to re-enable APIs. Use `make destroy-all` only for permanent project teardown; it deletes the secret containers too, so your `ANTHROPIC_API_KEY` / `SESSION_SIGNING_KEY` values are lost.

Raw terraform still works from `infra/envs/staging/` if you prefer:

```bash
terraform init -backend-config="bucket=<your-tf-state-bucket>"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## Sprint 1.7 scope

- **PR2 (merged)**: Artifact Registry, Cloud Run (placeholder image), Secret Manager containers.
- **PR3 (merged)**: VPC network + Serverless VPC Access connector, Cloud SQL Postgres (private IP), MemoryStore Redis, wiring into Cloud Run. Makefile wrapper.
- **PR3.5 (merged)**: `make deploy` target — manual build + push + Cloud Run deploy.
- **PR3.6 (this)**: Rename `up` / `down` → `apply` / `destroy`, add `destroy-all`. `make destroy` now preserves Secret Manager containers so real values survive teardown.
- **PR4 (next)**: GitHub Actions deploy workflow (build image → push to Artifact Registry → deploy Cloud Run revision on merge to master).
- **PR5**: Monitoring dashboard, Sentry, Cloud Storage + CDN for embed JS.

## Cost note

Running the full staging stack (Cloud SQL db-f1-micro + MemoryStore BASIC 1GB + VPC connector 2× e2-micro) is ~$50/month even at zero traffic — those are provisioned resources, not pay-per-request like Cloud Run. Use `make destroy` when you're pausing work for a day or more.
