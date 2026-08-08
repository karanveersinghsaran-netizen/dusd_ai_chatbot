resource "random_password" "db" {
  length  = 32
  special = false # keep it URL-safe so DATABASE_URL doesn't need shell-escaping
}

# Postgres instance with private IP only — reachable from Cloud Run via the
# Serverless VPC Access connector, not from the public internet.
resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = var.instance_name
  region              = var.region
  database_version    = var.database_version
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.tier
    disk_size         = var.disk_size_gb
    disk_type         = "PD_SSD"
    availability_type = "ZONAL" # single-zone; cheapest tier for staging

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false # PITR costs extra WAL storage
      start_time                     = "03:00"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
      }
    }

    ip_configuration {
      ipv4_enabled                                  = false # no public IP
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
    }

    deletion_protection_enabled = var.deletion_protection
  }
}

resource "google_sql_database" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = var.database_name
}

resource "google_sql_user" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = var.database_user
  password = random_password.db.result
}

# Publish the generated password into the DB_PASSWORD Secret Manager container
# (created by module.secrets in PR2 with a placeholder version). This adds
# version 2 — Cloud Run's secret_key_ref uses "latest", so it picks the real
# value from here going forward. The placeholder version stays with its own
# ignore_changes lifecycle, so this doesn't conflict.
resource "google_secret_manager_secret_version" "db_password" {
  secret      = "projects/${var.project_id}/secrets/${var.db_password_secret_id}"
  secret_data = random_password.db.result
}
