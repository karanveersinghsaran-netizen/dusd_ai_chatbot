variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Artifact Registry repository."
  type        = string
}

variable "repository_id" {
  description = "Repository ID (e.g. \"wms-chatbot\")."
  type        = string
}
