variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the subnet and VPC access connector."
  type        = string
}

variable "network_name" {
  description = "Name of the VPC network."
  type        = string
  default     = "wms-chatbot-vpc"
}

variable "primary_subnet_cidr" {
  description = "CIDR for the primary subnet in the given region. Room for future workloads."
  type        = string
  default     = "10.10.0.0/24"
}

variable "private_services_prefix_length" {
  description = "Prefix length of the reserved range for Cloud SQL private services access. /20 leaves ample room."
  type        = number
  default     = 20
}

variable "connector_name" {
  description = "Name of the Serverless VPC Access connector (max 25 chars)."
  type        = string
  default     = "wms-chatbot-conn"
}

variable "connector_cidr" {
  description = "CIDR for the VPC access connector. Must be /28 and not overlap with the primary subnet."
  type        = string
  default     = "10.11.0.0/28"
}

variable "enable_nat" {
  description = "When true, provision a Cloud Router + Cloud NAT so private VMs (self-hosted Redis) can reach the public internet for package installs and OS/agent updates. When false, VMs can only reach Google APIs via Private Google Access — apt-get to deb.debian.org will fail. Toggled ergonomically by `make nat-on` / `make nat-off`. Default true keeps `make apply` idempotent — regular applies won't accidentally destroy NAT."
  type        = bool
  default     = true
}
