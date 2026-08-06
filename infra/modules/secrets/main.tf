# One Secret Manager secret per entry in var.secret_ids. Values are populated
# out-of-band via `gcloud secrets versions add` — Terraform manages the secret
# containers and IAM, never the payloads.
resource "google_secret_manager_secret" "secret" {
  for_each  = toset(var.secret_ids)
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
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
