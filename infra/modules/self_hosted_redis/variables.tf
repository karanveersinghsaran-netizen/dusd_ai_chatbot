variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the VM + GCS snapshot bucket. Should match the Cloud Run region for lowest latency + zero egress cost."
  type        = string
}

variable "zone" {
  description = "Zone the VM lives in. Any zone inside `region` works; single-zone is fine since we run one VM."
  type        = string
  default     = "us-west1-a"
}

variable "instance_name" {
  description = "Name of the Compute Engine VM."
  type        = string
  default     = "wms-chatbot-redis"
}

variable "machine_type" {
  description = "VM machine type. e2-micro is $0.25/day for the workload of ~200 Redis commands/day. e2-small if you outgrow it."
  type        = string
  default     = "e2-micro"
}

variable "network_id" {
  description = "Full VPC network ID the VM attaches to. Same VPC that Cloud Run's VPC connector uses."
  type        = string
}

variable "subnetwork_id" {
  description = "Full subnet ID the VM's NIC lives in. Same subnet as the VPC connector so the firewall CIDR match is trivial."
  type        = string
}

variable "connector_cidr" {
  description = "CIDR of the Cloud Run VPC access connector. Traffic from this range to the VM's :6379 is what the firewall rule allows — everything else is denied."
  type        = string
}

variable "redis_maxmemory" {
  description = "Redis maxmemory setting. 512mb leaves room on a 1 GB e2-micro for the OS + Redis overhead."
  type        = string
  default     = "512mb"
}

variable "snapshot_interval" {
  description = "How often the systemd timer copies dump.rdb to the GCS snapshot bucket. 6h keeps GCS storage minimal while capping worst-case data loss at that window."
  type        = string
  default     = "6h"
}

variable "snapshot_retention_count" {
  description = "How many past snapshots to keep in the GCS bucket. Older snapshots get pruned by the timer. 20 * 6h = ~5 days of history."
  type        = number
  default     = 20
}
