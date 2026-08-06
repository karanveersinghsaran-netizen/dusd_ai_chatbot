resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "Container images for the WMS chatbot"
  format        = "DOCKER"

  # Reap untagged images after 30 days so we don't pay to store CI churn.
  cleanup_policies {
    id     = "delete-untagged-after-30d"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "2592000s"
    }
  }
}
