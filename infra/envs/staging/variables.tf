variable "project_id" {
  description = "GCP project ID for the staging environment (create manually — see docs/deploy.md)."
  type        = string
}

variable "region" {
  description = "GCP region. Dublin, CA is on the west coast; us-west1 is a low-latency default."
  type        = string
  default     = "us-west1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "wms-chatbot"
}

variable "artifact_repository_id" {
  description = "Artifact Registry repository ID for container images."
  type        = string
  default     = "wms-chatbot"
}

variable "allowed_origins" {
  description = "Comma-separated origins passed to the app via ALLOWED_ORIGINS (CORS)."
  type        = string
  default     = "https://wms.dublinusd.org"
}

variable "public_base_url" {
  description = "Public origin this Cloud Run service is reachable at (its *.run.app URL, or a custom domain once one is mapped). Passed to the app via PUBLIC_BASE_URL — used to build absolute links (e.g. the campus map image) that get echoed into chat replies."
  type        = string
  default     = ""
}
