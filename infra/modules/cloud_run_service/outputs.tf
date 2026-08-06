output "service_url" {
  description = "Cloud Run service URL (HTTPS)."
  value       = google_cloud_run_v2_service.app.uri
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.app.name
}

output "runtime_service_account_email" {
  description = "Email of the runtime service account (grant Secret Manager and DB access to this)."
  value       = google_service_account.runtime.email
}
