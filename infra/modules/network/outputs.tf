output "network_id" {
  description = "Full resource ID of the VPC network."
  value       = google_compute_network.vpc.id
}

output "network_name" {
  description = "Name of the VPC network — MemoryStore takes name, Cloud SQL takes ID."
  value       = google_compute_network.vpc.name
}

output "vpc_connector_id" {
  description = "ID of the Serverless VPC Access connector — consumed by Cloud Run."
  value       = google_vpc_access_connector.connector.id
}

output "private_services_connection" {
  description = "The service_networking_connection resource — consumers must depend on it before creating Cloud SQL private-IP instances."
  value       = google_service_networking_connection.private_services
}
