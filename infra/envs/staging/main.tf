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
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "sqladmin.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    # storage.googleapis.com powers the GCS bucket that receives the
    # self-hosted Redis VM's periodic RDB snapshots.
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

module "network" {
  source = "../../modules/network"

  project_id = var.project_id
  region     = var.region
  enable_nat = var.enable_nat

  depends_on = [google_project_service.required]
}

module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id    = var.project_id
  region        = var.region
  repository_id = var.artifact_repository_id

  depends_on = [google_project_service.required]
}

module "cloud_sql" {
  source = "../../modules/cloud_sql"

  project_id = var.project_id
  region     = var.region
  network_id = module.network.network_id

  # Password gets published to the existing DB_PASSWORD secret container
  # (created by module.secrets) as version 2, superseding the placeholder.
  db_password_secret_id = "DB_PASSWORD"

  # Cloud SQL private-IP creation requires the VPC peering to exist first.
  depends_on = [
    google_project_service.required,
    module.network,
    module.secrets,
  ]
}

# Self-hosted Redis on a Compute Engine e2-micro VM (replaced MemoryStore,
# which used to sit alongside this block — see PR history for the cutover).
# Data lives on a separate persistent disk (see modules/self_hosted_redis)
# so a VM crash or replacement keeps the dataset intact; GCS snapshots are
# the second layer of insurance.
module "self_hosted_redis" {
  source = "../../modules/self_hosted_redis"

  project_id     = var.project_id
  region         = var.region
  network_id     = module.network.network_id
  subnetwork_id  = module.network.primary_subnet_id
  connector_cidr = module.network.connector_cidr

  depends_on = [
    google_project_service.required,
    module.network,
  ]
}

module "cloud_run" {
  source = "../../modules/cloud_run_service"

  project_id   = var.project_id
  region       = var.region
  service_name = var.service_name

  # Real families now reach this via the flyer link — a cold start on their
  # first (only?) visit is a worse impression than the small always-on
  # cost. Was 0 (scale-to-zero) since this is nominally "staging"; keeping
  # one instance warm removes cold starts entirely.
  min_instances = 1

  vpc_connector_id = module.network.vpc_connector_id

  plain_env_vars = {
    ALLOWED_ORIGINS = var.allowed_origins
    DATABASE_URL    = module.cloud_sql.database_url
    REDIS_URL       = module.self_hosted_redis.redis_url
    PUBLIC_BASE_URL = var.public_base_url
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
    "CHATBOX_TOKEN_SIGNING_KEY",
    "DB_PASSWORD",
  ]

  depends_on = [google_project_service.required]
}

module "monitoring" {
  source = "../../modules/monitoring"

  project_id                = var.project_id
  region                    = var.region
  service_name              = var.service_name
  cloud_sql_instance_id     = module.cloud_sql.instance_name
  self_hosted_redis_vm_name = module.self_hosted_redis.instance_name
  alert_email               = var.alert_email

  # Monitoring depends on the resources it's monitoring, otherwise a fresh
  # apply can create alert policies before Cloud SQL / Redis exist — the
  # console shows them as "no data" until the resources come up, which is
  # harmless but confusing.
  depends_on = [
    google_project_service.required,
    module.cloud_run,
    module.cloud_sql,
    module.self_hosted_redis,
  ]
}

# IAM binding lives OUTSIDE modules/secrets so `make destroy` can target it
# (along with the ephemeral Cloud Run SA) without touching the secret
# containers themselves. Preserving containers across destroy/apply cycles
# is what keeps real values populated via `gcloud secrets versions add`
# from being wiped every time the datastore layer is torn down.
resource "google_secret_manager_secret_iam_member" "cloud_run_access" {
  for_each  = module.secrets.secret_ids
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${module.cloud_run.runtime_service_account_email}"
}
