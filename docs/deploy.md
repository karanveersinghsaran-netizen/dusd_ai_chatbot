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

terraform init -backend-config="bucket=${TF_STATE_BUCKET}"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Expected outputs: `cloud_run_url`, `cloud_run_service_name`, `cloud_run_runtime_sa`, `artifact_registry_image_base`.

## 6. Populate secret values

Terraform creates the Secret Manager *containers* but never the values (values must not appear in git or state). Populate each one via `gcloud`:

```bash
printf '%s' "$ANTHROPIC_API_KEY" | \
  gcloud secrets versions add ANTHROPIC_API_KEY --data-file=-

python -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets versions add SESSION_SIGNING_KEY --data-file=-

printf '%s' "$TWILIO_ACCOUNT_SID" | \
  gcloud secrets versions add TWILIO_ACCOUNT_SID --data-file=-

printf '%s' "$TWILIO_AUTH_TOKEN" | \
  gcloud secrets versions add TWILIO_AUTH_TOKEN --data-file=-

# DB_PASSWORD is populated as part of the Cloud SQL PR (later).
```

Cloud Run reads secrets at request time with `version = "latest"`, so no service redeploy is needed after `versions add`.

## 7. Verify

```bash
curl -sS "$(terraform output -raw cloud_run_url)/"
```

The placeholder `hello` image responds with a Cloud Run welcome page today; once the deploy pipeline lands (later PR), this becomes the WMS chatbot's `/` health response.

## What's still missing

- **Cloud SQL Postgres + MemoryStore Redis + VPC connector** — next PR. Until it lands, the real app image will fail at startup (needs a DB); the placeholder is what runs.
- **GitHub Actions deploy workflow** — after that. Currently images are pushed manually.
- **Monitoring dashboard + Sentry + CDN for embed JS** — last PR.
