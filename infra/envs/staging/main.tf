provider "google" {
  project = var.project_id
  region  = var.region
}

# APIs required by the resources managed here. Bootstrap docs explain how to
# enable the ones needed to *reach* this state (billing, IAM) — this block
# handles the rest so a fresh project reaches a green apply in one pass.
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id    = var.project_id
  region        = var.region
  repository_id = var.artifact_repository_id

  depends_on = [google_project_service.required]
}

module "cloud_run" {
  source = "../../modules/cloud_run_service"

  project_id   = var.project_id
  region       = var.region
  service_name = var.service_name

  plain_env_vars = {
    ALLOWED_ORIGINS = var.allowed_origins
  }

  secret_env_vars = {
    for env_name, secret_id in module.secrets.secret_ids : env_name => secret_id
  }

  depends_on = [google_project_service.required]
}

module "secrets" {
  source = "../../modules/secrets"

  project_id = var.project_id

  # Secret IDs are chosen to match the env var names the app reads, so the
  # cloud_run module can wire them without a translation table.
  secret_ids = [
    "ANTHROPIC_API_KEY",
    "SESSION_SIGNING_KEY",
    "DB_PASSWORD",
  ]

  accessor_service_account_email = module.cloud_run.runtime_service_account_email

  depends_on = [google_project_service.required]
}
