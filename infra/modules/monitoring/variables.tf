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

variable "self_hosted_redis_vm_name" {
  description = "Compute Engine VM name running self-hosted Redis. Empty string skips creating the VM-uptime alert (module still works standalone). When set, an alert fires if the VM's uptime metric stops reporting for 5 min — covers VM crash, GCE maintenance reboot, and Ops Agent failure."
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Email address that receives alert notifications. If empty, alert policies are still created but no notification channel is attached, so alerts silently fire until an operator adds a channel via the console. Set to an operator's email to get 5xx/latency/DB pages."
  type        = string
  default     = ""
}
