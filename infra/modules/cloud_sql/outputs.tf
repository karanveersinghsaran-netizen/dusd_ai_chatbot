output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.main.name
}

output "connection_name" {
  description = "Cloud SQL connection name (project:region:instance) — used by Cloud SQL Auth Proxy or --add-cloudsql-instances."
  value       = google_sql_database_instance.main.connection_name
}

output "private_ip_address" {
  description = "Private IP of the Cloud SQL instance."
  value       = google_sql_database_instance.main.private_ip_address
}

output "database_name" {
  description = "App database name."
  value       = google_sql_database.app.name
}

output "database_user" {
  description = "App database user."
  value       = google_sql_user.app.name
}

output "database_url" {
  description = "Assembled Postgres URL (contains password — treat as sensitive)."
  value       = "postgresql://${google_sql_user.app.name}:${random_password.db.result}@${google_sql_database_instance.main.private_ip_address}:5432/${google_sql_database.app.name}"
  sensitive   = true
}
