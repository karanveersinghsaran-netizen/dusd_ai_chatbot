# One Secret Manager secret per entry in var.secret_ids. Real values are
# populated out-of-band via `gcloud secrets versions add` — Terraform manages
# the secret containers, a placeholder version, and IAM. Never real payloads.
resource "google_secret_manager_secret" "secret" {
  for_each  = toset(var.secret_ids)
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }
}

# Placeholder version so Cloud Run's secret_key_ref with version = "latest"
# has something to resolve at cold-bootstrap apply time. Without this the
# first `terraform apply` fails: Cloud Run rejects the service creation
# because the referenced secret has no versions yet, but the runbook can't
# populate values before the containers exist.
#
# `ignore_changes = [secret_data]` prevents Terraform from overwriting real
# values that `gcloud secrets versions add` layers on top later. Cloud Run
# picks up the highest-numbered version at request time, so real values
# supersede this placeholder without any redeploy.
resource "google_secret_manager_secret_version" "placeholder" {
  for_each    = google_secret_manager_secret.secret
  secret      = each.value.id
  secret_data = "REPLACE_ME_VIA_gcloud_secrets_versions_add"

  lifecycle {
    ignore_changes = [secret_data, enabled]
  }
}

# Grant the Cloud Run service account permission to read each secret at
# request time (Cloud Run reads secrets on cold start / every request when
# mounted as env vars with version = "latest").
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each  = google_secret_manager_secret.secret
  project   = each.value.project
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.accessor_service_account_email}"
}
