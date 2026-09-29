output "network_id" {
  description = "Full resource ID of the VPC network."
  value       = google_compute_network.vpc.id
}

output "network_name" {
  description = "Name of the VPC network — MemoryStore takes name, Cloud SQL takes ID."
  value       = google_compute_network.vpc.name
}

output "primary_subnet_id" {
  description = "Full resource ID of the primary subnet — used by Compute Engine VMs (self-hosted Redis) that need a subnet to attach a NIC to."
  value       = google_compute_subnetwork.primary.id
}

output "connector_cidr" {
  description = "CIDR of the Serverless VPC access connector. Firewall rules that need to accept Cloud Run traffic (self-hosted Redis) source-match on this range."
  value       = var.connector_cidr
}

output "vpc_connector_id" {
  description = "ID of the Serverless VPC Access connector — consumed by Cloud Run."
  value       = google_vpc_access_connector.connector.id
}

output "private_services_connection" {
  description = "The service_networking_connection resource — consumers must depend on it before creating Cloud SQL private-IP instances."
  value       = google_service_networking_connection.private_services
}
