variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Cloud SQL instance."
  type        = string
}

variable "instance_name" {
  description = "Cloud SQL instance name."
  type        = string
  default     = "wms-chatbot-db"
}

variable "database_version" {
  description = "Postgres major version."
  type        = string
  default     = "POSTGRES_16"
}

variable "tier" {
  description = "Machine tier. db-f1-micro is the cheapest option for staging."
  type        = string
  default     = "db-f1-micro"
}

variable "disk_size_gb" {
  description = "Persistent disk size in GB (SSD)."
  type        = number
  default     = 10
}

variable "deletion_protection" {
  description = "Whether Cloud SQL and Terraform should refuse to delete the instance. False on staging so `make down` works."
  type        = bool
  default     = false
}

variable "network_id" {
  description = "VPC network ID that the instance's private IP is allocated from."
  type        = string
}

variable "database_name" {
  description = "Name of the app database within the instance."
  type        = string
  default     = "wms"
}

variable "database_user" {
  description = "Name of the app database user."
  type        = string
  default     = "wms"
}

variable "db_password_secret_id" {
  description = "Secret ID of an existing Secret Manager container to receive the generated password (a new version is added)."
  type        = string
  default     = "DB_PASSWORD"
}
