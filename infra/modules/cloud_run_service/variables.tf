variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Cloud Run service."
  type        = string
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
}

variable "image" {
  description = "Initial container image. Overwritten by the deploy pipeline; Terraform ignores subsequent changes."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "min_instances" {
  description = "Minimum instances (0 lets the service scale to zero on staging)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum instances."
  type        = number
  default     = 3
}

variable "cpu" {
  description = "CPU limit per instance."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory limit per instance."
  type        = string
  default     = "512Mi"
}

variable "plain_env_vars" {
  description = "Env vars set as literal values."
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Env vars sourced from Secret Manager. Map of ENV_NAME -> secret_id."
  type        = map(string)
  default     = {}
}

variable "allow_unauthenticated" {
  description = "Whether to bind roles/run.invoker to allUsers (public HTTPS)."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Whether Terraform should refuse to delete the service."
  type        = bool
  default     = false
}
