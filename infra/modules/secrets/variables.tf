variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "secret_ids" {
  description = "IDs of the Secret Manager secrets to create (values are populated out-of-band)."
  type        = list(string)
}

variable "accessor_service_account_email" {
  description = "Service account email that will be granted secretAccessor on every secret."
  type        = string
}
