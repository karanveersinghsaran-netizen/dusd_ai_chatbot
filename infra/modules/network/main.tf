# Custom VPC so Cloud Run can reach Cloud SQL (private IP) and MemoryStore
# without touching the auto-generated `default` VPC. One VPC per environment
# gives clean per-env network isolation.
resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "primary" {
  project                  = var.project_id
  name                     = "${var.network_name}-primary"
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = var.primary_subnet_cidr
  private_ip_google_access = true
}

# Reserved IP range for Cloud SQL private services access. Cloud SQL will
# allocate IPs from within this range when we ask for a private-IP instance.
resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${var.network_name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_services_prefix_length
  network       = google_compute_network.vpc.id
}

# VPC peering with Google's services network — Cloud SQL uses this to expose
# its instance in our VPC via the reserved range above.
resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# Serverless VPC Access connector — the bridge that lets Cloud Run reach
# resources on the VPC (Cloud SQL private IP, MemoryStore).
resource "google_vpc_access_connector" "connector" {
  project = var.project_id
  region  = var.region
  name    = var.connector_name

  # Connector needs its own /28. Must NOT overlap with the primary subnet
  # or the private services range.
  ip_cidr_range = var.connector_cidr
  network       = google_compute_network.vpc.name

  # Cheapest tier — e2-micro machines, 2-3 replicas. Enough for staging.
  # min_instances/max_instances are mutually exclusive with min/max_throughput
  # in the google provider v6; pick the instance-count knob for cost predictability.
  machine_type  = "e2-micro"
  min_instances = 2
  max_instances = 3
}

# Cloud Run's project-level Service Agent (Google-managed, distinct from any
# runtime SA we create) needs roles/vpcaccess.user to actually attach a
# service to a VPC connector. Without this, the first Cloud Run revision
# using the connector fails with:
#   Error waiting for Creating Service: Revision '…' is not ready and cannot
#   serve traffic. Failed to prepare VPC connector. Please try again later
# The "try again later" phrasing is misleading — it's a permissions gap,
# not a transient one.
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_iam_member" "cloud_run_vpc_user" {
  project = var.project_id
  role    = "roles/vpcaccess.user"
  member  = "serviceAccount:service-${data.google_project.current.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
