variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Redis instance."
  type        = string
}

variable "instance_name" {
  description = "Redis instance name."
  type        = string
  default     = "wms-chatbot-redis"
}

variable "tier" {
  description = "Service tier. BASIC = single node, no HA (cheapest). STANDARD_HA doubles cost for a replica."
  type        = string
  default     = "BASIC"
}

variable "memory_size_gb" {
  description = "Memory size in GB. 1 is the minimum for BASIC tier."
  type        = number
  default     = 1
}

variable "redis_version" {
  description = "Redis major version."
  type        = string
  default     = "REDIS_7_2"
}

variable "authorized_network" {
  description = "Full VPC network ID or self_link that this instance is reachable from."
  type        = string
}
