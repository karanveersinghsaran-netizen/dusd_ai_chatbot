output "host" {
  description = "Reserved internal IP that Redis is reachable at. Stable across VM recreation."
  value       = google_compute_address.redis.address
}

output "port" {
  description = "Redis port. 6379 is the default and what the app expects."
  value       = 6379
}

output "redis_url" {
  description = "Assembled redis:// URL for REDIS_URL env var. Same shape as the MemoryStore module's output so the Cloud Run wiring is a one-line swap."
  value       = "redis://${google_compute_address.redis.address}:6379/0"
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
