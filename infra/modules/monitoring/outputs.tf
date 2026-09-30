output "dashboard_url" {
  description = "Direct URL to the Cloud Monitoring dashboard. Bookmark this — it's the single page for ops + adoption at a glance."
  value       = "https://console.cloud.google.com/monitoring/dashboards/custom/${basename(google_monitoring_dashboard.wms_chatbot.id)}?project=${var.project_id}"
}

output "alert_policy_ids" {
  description = "IDs of the alert policies created by this module, for referencing in the console."
  value = {
    cloud_run_5xx_rate = google_monitoring_alert_policy.cloud_run_5xx_rate.id
    chat_latency_p95   = google_monitoring_alert_policy.chat_latency_p95.id
    cloud_sql_cpu      = google_monitoring_alert_policy.cloud_sql_cpu.id
  }
}

output "notification_channel_verification_note" {
  description = "Reminder printed on apply: if alert_email was set, the recipient must click the verification link in the email Google sends before alerts will actually deliver."
  value       = length(google_monitoring_notification_channel.email) > 0 ? "Notification channel created for ${var.alert_email}. Ask the recipient to verify by clicking the link in the Google-sent verification email — alerts stay silent until they do." : "No alert_email provided; alerts fire but do not notify. Add a notification channel via the console to receive them."
}
