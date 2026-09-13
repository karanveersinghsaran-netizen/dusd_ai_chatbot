output "instance_name" {
  description = "Redis instance short name (e.g. wms-chatbot-redis) — the value monitoring resource filters use as instance_id."
  value       = google_redis_instance.cache.name
}

output "host" {
  description = "Private IP host that Redis is reachable at."
  value       = google_redis_instance.cache.host
}

output "port" {
  description = "Redis port (usually 6379)."
  value       = google_redis_instance.cache.port
}

output "redis_url" {
  description = "Assembled redis:// URL for REDIS_URL env var."
  value       = "redis://${google_redis_instance.cache.host}:${google_redis_instance.cache.port}/0"
}
