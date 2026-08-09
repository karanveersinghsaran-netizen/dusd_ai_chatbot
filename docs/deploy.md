# Deploy runbook

First-time GCP bootstrap for the WMS chatbot. Everything the runtime app needs is Terraform-managed; the steps here are the one-time chicken-and-egg pieces (create the project, create the state bucket, create the SA Terraform runs as) that must exist before `terraform apply` can be run.

Sprint 1.7 lands infra incrementally — see the PR sequence in issue #10. Staging is the only environment provisioned today; prod follows once staging is stable.

## Prerequisites

- `gcloud` CLI, authenticated as an account with Organization Admin or Project Creator on the target billing account.
- `terraform` >= 1.6.
- A billing account ID to attach the new project to.

## 1. Create the GCP project

```bash
export PROJECT_ID=wms-chatbot-staging
export BILLING_ACCOUNT=<XXXXXX-XXXXXX-XXXXXX>
export REGION=us-west1

gcloud projects create "$PROJECT_ID" --name="WMS Chatbot (staging)"
gcloud beta billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
gcloud config set project "$PROJECT_ID"
```

## 2. Enable bootstrap APIs

Terraform enables the runtime APIs itself (`google_project_service` in `envs/staging/main.tf`); this step covers only the APIs required to run Terraform at all.

```bash
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  serviceusage.googleapis.com \
  iamcredentials.googleapis.com
```

## 3. Create the Terraform state bucket

Remote state lives in GCS. The bucket name must be globally unique — the pattern below embeds the project ID.

```bash
export TF_STATE_BUCKET="${PROJECT_ID}-tfstate"

gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention

# Versioning gives us recovery from an accidental `terraform destroy` /
# state corruption. Cheap and standard for TF state buckets.
gcloud storage buckets update "gs://${TF_STATE_BUCKET}" --versioning
```

## 4. Create the Terraform service account (for local applies)

For local `terraform apply`, either (a) use your user credentials via
`gcloud auth application-default login`, or (b) create a dedicated SA. CI/CD
gets its own SA via Workload Identity Federation in a later PR.

Simplest — user creds:

```bash
gcloud auth application-default login
```

## 5. First `terraform apply`

```bash
cd infra/envs/staging
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars — set project_id, region, allowed_origins

# From infra/ using the Makefile:
make init TF_STATE_BUCKET="${TF_STATE_BUCKET}"
make plan
make apply

# Or raw terraform from infra/envs/staging/:
terraform init -backend-config="bucket=${TF_STATE_BUCKET}"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Expected outputs after PR3: `cloud_run_url`, `cloud_run_service_name`, `cloud_run_runtime_sa`, `artifact_registry_image_base`, `cloud_sql_connection_name`, `cloud_sql_private_ip`, `redis_host`, `vpc_network_name`.

First apply takes 15-20 minutes — Cloud SQL creation is the long pole (~8-10 min), then MemoryStore (~3-5 min), then Cloud Run.

## 6. Populate secret values

To break the chicken-and-egg (Cloud Run's `version = "latest"` refs would fail on cold apply otherwise), Terraform creates each secret with a placeholder version whose payload is literally `REPLACE_ME_VIA_gcloud_secrets_versions_add`. That placeholder is what the freshly-created Cloud Run service reads today.

**Replace every placeholder with a real value before pointing real traffic at the service** — otherwise the app boots with `REPLACE_ME…` as its API key. Cloud Run reads `latest` at request time, so no redeploy is needed once you add a real version.

```bash
printf '%s' "$ANTHROPIC_API_KEY" | \
  gcloud secrets versions add ANTHROPIC_API_KEY --data-file=-

python -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets versions add SESSION_SIGNING_KEY --data-file=-
```

**`DB_PASSWORD` is handled automatically by Terraform** from PR3 onwards — the `cloud_sql` module generates a random password via `random_password`, creates the Cloud SQL user with it, and writes it to a new version of the `DB_PASSWORD` secret. No manual `gcloud secrets versions add DB_PASSWORD` required. If you ever need to see the password, `terraform output -raw` on `database_url` (marked sensitive) will print it.

Terraform's `lifecycle { ignore_changes = [secret_data] }` on the placeholder version means the real values you add above aren't reverted on the next `terraform apply`.

## 7. Verify

```bash
curl -sS "$(terraform output -raw cloud_run_url)/"
```

The placeholder `cloudrun/hello` image still responds with Google's welcome page — Cloud Run is up but not yet running our chatbot.

## 8. First real image deploy (`make deploy`)

Once `terraform apply` is green and the operator-managed secrets are populated, push the actual app image:

```bash
cd infra && make deploy
```

Under the hood: reads `region` / `cloud_run_service_name` / `artifact_registry_image_base` from terraform outputs, tags the image with the git short SHA (`TAG=... make deploy` to override), builds `--platform linux/amd64`, pushes to Artifact Registry, and runs `gcloud run deploy`. On success it curls `/` and prints the health response.

This is the manual loop while PR4's GitHub Actions deploy workflow is being built. Once PR4 lands, every push to `master` will do the same thing automatically.

## Tear-down (stop the billing)

Cloud SQL + MemoryStore + VPC connector run ~$50/month even at zero traffic. When pausing work for more than a day:

```bash
cd infra && make destroy
```

`make destroy` uses `-target` to preserve several things:
- **Secret Manager containers** (`module.secrets`) — real values from `gcloud secrets versions add` including `ANTHROPIC_API_KEY` and `SESSION_SIGNING_KEY` survive. `DB_PASSWORD` regenerates automatically on next apply.
- **Enabled APIs** (`google_project_service.required`) — saves minutes by not re-toggling on re-apply.
- **VPC network, subnet, peering, IAM** (most of `module.network`) — these are free anyway, and destroying the VPC peering hits Google's "producer services still using this" error because Cloud SQL / MemoryStore have residual backend state for several minutes after their Terraform destroy completes. Only the VPC Access connector (the ~$5-10/mo piece) is torn down.

Rebuild anytime with `make apply` — takes ~15-20 min again because Cloud SQL is slow to provision.

For permanent project retirement, `make destroy-all` removes everything including the secret containers. Real values are lost at that point.

## What's still missing

- **GitHub Actions deploy workflow** — next PR. Currently images are pushed manually.
- **Monitoring dashboard + Sentry + CDN for embed JS** — last PR.
