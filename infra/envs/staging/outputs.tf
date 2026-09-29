output "project_id" {
  description = "GCP project ID — echoed from input so `make deploy` can read it without parsing tfvars."
  value       = var.project_id
}

output "region" {
  description = "GCP region — echoed from input so `make deploy` can read it without parsing tfvars."
  value       = var.region
}

output "cloud_run_url" {
  description = "HTTPS URL of the deployed Cloud Run service."
  value       = module.cloud_run.service_url
}

output "cloud_run_service_name" {
  description = "Cloud Run service name — consumed by the deploy workflow."
  value       = module.cloud_run.service_name
}

output "cloud_run_runtime_sa" {
  description = "Runtime service account email — grant DB/Redis access to this in later PRs."
  value       = module.cloud_run.runtime_service_account_email
}

output "artifact_registry_image_base" {
  description = "Base URI for pushing images — consumed by the deploy workflow."
  value       = module.artifact_registry.image_uri_base
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance) — for Cloud SQL Auth Proxy or migrations from CI."
  value       = module.cloud_sql.connection_name
}

output "cloud_sql_private_ip" {
  description = "Private IP of the Cloud SQL instance."
  value       = module.cloud_sql.private_ip_address
}

output "redis_host" {
  description = "Private IP MemoryStore Redis is reachable at."
  value       = module.redis.host
}

output "self_hosted_redis_url" {
  description = "REDIS_URL for the self-hosted VM. Present alongside the MemoryStore output during migration; consumers still read redis_host until cutover. Sensitive because it embeds the AUTH password."
  value       = module.self_hosted_redis.redis_url
  sensitive   = true
}

output "self_hosted_redis_snapshot_bucket" {
  description = "GCS bucket that receives RDB snapshots from the self-hosted Redis VM."
  value       = module.self_hosted_redis.snapshot_bucket
}

output "vpc_network_name" {
  description = "Custom VPC network name."
  value       = module.network.network_name
}

output "monitoring_dashboard_url" {
  description = "Direct URL to the Cloud Monitoring dashboard for the wms-chatbot service. Bookmark this — it's the single page for ops + adoption at a glance."
  value       = module.monitoring.dashboard_url
}

output "monitoring_notification_note" {
  description = "One-line reminder about verifying the alert notification channel."
  value       = module.monitoring.notification_channel_verification_note
}
