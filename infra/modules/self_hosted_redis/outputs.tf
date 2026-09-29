output "host" {
  description = "Reserved internal IP that Redis is reachable at. Stable across VM recreation."
  value       = google_compute_address.redis.address
}

output "port" {
  description = "Redis port. 6379 is the default and what the app expects."
  value       = 6379
}

output "redis_url" {
  description = "Assembled redis:// URL for REDIS_URL env var, including the AUTH password. Same shape as the MemoryStore module's output so the Cloud Run wiring is a one-line swap. Sensitive because it embeds the password — Cloud Run env vars carry it, same pattern as DATABASE_URL."
  value       = "redis://:${random_password.redis.result}@${google_compute_address.redis.address}:6379/0"
  sensitive   = true
}

output "password_secret_id" {
  description = "Secret Manager ID storing the Redis AUTH password. Useful for consumers that want to read the password directly (secret_env_vars) rather than through the pre-assembled redis_url."
  value       = google_secret_manager_secret.redis_password.secret_id
}

output "instance_name" {
  description = "VM name — used by monitoring alert filters as the compute-instance label."
  value       = google_compute_instance.redis.name
}

output "vm_service_account_email" {
  description = "Service account the VM runs as. Reveal only where useful (e.g. granting the SA access to additional buckets)."
  value       = google_service_account.vm.email
}

output "snapshot_bucket" {
  description = "Name of the GCS bucket that receives periodic Redis RDB snapshots. Grab a snapshot with `gsutil cp gs://<bucket>/dump-<YYYY-MM-DD>-<HHMMSS>.rdb .`"
  value       = google_storage_bucket.snapshots.name
}
