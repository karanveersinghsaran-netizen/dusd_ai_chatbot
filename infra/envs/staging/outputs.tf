output "cloud_run_url" {
  description = "HTTPS URL of the deployed Cloud Run service."
  value       = module.cloud_run.service_url
}

output "cloud_run_service_name" {
  description = "Cloud Run service name — consumed by the deploy workflow."
  value       = module.cloud_run.service_name
}

output "cloud_run_runtime_sa" {
  description = "Runtime service account email — grant DB/Redis access to this in later PRs."
  value       = module.cloud_run.runtime_service_account_email
}

output "artifact_registry_image_base" {
  description = "Base URI for pushing images — consumed by the deploy workflow."
  value       = module.artifact_registry.image_uri_base
}
