output "repository_name" {
  description = "Full resource name of the repository."
  value       = google_artifact_registry_repository.images.name
}

output "image_uri_base" {
  description = "Base URI for pushing images (append :tag)."
  value       = "${google_artifact_registry_repository.images.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
