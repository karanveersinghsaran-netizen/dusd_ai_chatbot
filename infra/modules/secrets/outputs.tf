output "secret_ids" {
  description = "Map of logical name -> secret_id for consumption by Cloud Run env wiring."
  value       = { for id, s in google_secret_manager_secret.secret : id => s.secret_id }

  # Force consumers (Cloud Run) to wait for the placeholder version to exist,
  # otherwise the service creation races the version and fails with
  # "secret … versions/latest was not found".
  depends_on = [google_secret_manager_secret_version.placeholder]
}
