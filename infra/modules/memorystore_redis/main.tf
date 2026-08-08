resource "google_redis_instance" "cache" {
  project        = var.project_id
  region         = var.region
  name           = var.instance_name
  tier           = var.tier
  memory_size_gb = var.memory_size_gb
  redis_version  = var.redis_version

  # PRIVATE_SERVICE_ACCESS reuses the VPC peering that Cloud SQL sets up,
  # so we don't need a separate service_networking_connection.
  authorized_network      = var.authorized_network
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  transit_encryption_mode = "DISABLED" # private VPC only; skip TLS overhead for staging
  auth_enabled            = false      # same reasoning — private network is the boundary
}
