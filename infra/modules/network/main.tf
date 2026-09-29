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

# Cloud Run's project-level Service Agent (Google-managed, distinct from any
# runtime SA we create) needs roles/vpcaccess.user to actually attach a
# service to a VPC connector. Without this, the first Cloud Run revision
# using the connector fails with:
#   Error waiting for Creating Service: Revision '…' is not ready and cannot
#   serve traffic. Failed to prepare VPC connector. Please try again later
# The "try again later" phrasing is misleading — it's a permissions gap,
# not a transient one.
#
# Declared BEFORE the connector resource so the depends_on graph enforces
# "IAM in place before connector is created" — otherwise Google can put the
# connector in a permanent ERROR state that only a destroy+recreate fixes.
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_iam_member" "cloud_run_vpc_user" {
  project = var.project_id
  role    = "roles/vpcaccess.user"
  member  = "serviceAccount:service-${data.google_project.current.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

# Cloud Router + Cloud NAT — gives private VMs (self-hosted Redis) internet
# egress without assigning them public IPs, so `apt-get install` and other
# outbound calls work even though the VM has no external IP. Cost: ~$1-2/mo
# (NAT gateway per-hour + processed bytes; our egress is tiny).
#
# Google APIs (Secret Manager, GCS, Cloud Monitoring, Logging) still go
# through Private Google Access on the subnet — NAT is only used for
# non-Google destinations like deb.debian.org, dl.google.com/cloudagents, etc.
resource "google_compute_router" "nat" {
  count   = var.enable_nat ? 1 : 0
  project = var.project_id
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  count                              = var.enable_nat ? 1 : 0
  project                            = var.project_id
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.nat[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = false
    filter = "ERRORS_ONLY"
  }
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

  # Ensure the Cloud Run Service Agent has vpcaccess.user BEFORE the connector
  # is created. Without this ordering, a fresh apply can produce a connector
  # in permanent ERROR state that only a `terraform apply -replace=…` fixes.
  depends_on = [google_project_iam_member.cloud_run_vpc_user]
}
