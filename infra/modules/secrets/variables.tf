variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "secret_ids" {
  description = "IDs of the Secret Manager secrets to create (values are populated out-of-band)."
  type        = list(string)
}
