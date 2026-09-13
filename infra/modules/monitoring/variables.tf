variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "service_name" {
  description = "Cloud Run service name to monitor. Filters the dashboard + alerts to this service."
  type        = string
}

variable "region" {
  description = "GCP region the Cloud Run service runs in — used to filter Cloud SQL and Redis metrics to the same region."
  type        = string
}

variable "cloud_sql_instance_id" {
  description = "Cloud SQL instance id (short name, not the full connection name). Used to filter Cloud SQL metrics on the dashboard + CPU alert."
  type        = string
}

variable "redis_instance_id" {
  description = "MemoryStore Redis instance id (short name). Used to filter Redis metrics."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives alert notifications. If empty, alert policies are still created but no notification channel is attached, so alerts silently fire until an operator adds a channel via the console. Set to an operator's email to get 5xx/latency/DB pages."
  type        = string
  default     = ""
}
