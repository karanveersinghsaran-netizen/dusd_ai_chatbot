output "secret_ids" {
  description = "Map of logical name -> secret_id for consumption by Cloud Run env wiring."
  value       = { for id, s in google_secret_manager_secret.secret : id => s.secret_id }
}
