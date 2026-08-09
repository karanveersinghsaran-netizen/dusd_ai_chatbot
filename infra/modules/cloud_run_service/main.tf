resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.service_name}-runtime"
  display_name = "${var.service_name} Cloud Run runtime SA"
}

resource "google_cloud_run_v2_service" "app" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  deletion_protection = var.deletion_protection
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Route Cloud Run egress through a Serverless VPC Access connector when
    # one is provided — required for private-IP Cloud SQL and MemoryStore.
    # PRIVATE_RANGES_ONLY sends only RFC1918 traffic through the connector;
    # public traffic (Anthropic API, Twilio, GitHub, etc.) uses Cloud Run's
    # default direct egress to the internet. With ALL_TRAFFIC every outbound
    # call would hit the VPC edge, which has no Cloud NAT — the app then
    # times out on external HTTPS calls with "Connection error".
    dynamic "vpc_access" {
      for_each = var.vpc_connector_id == null ? [] : [1]
      content {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }
    }

    containers {
      image = var.image

      dynamic "env" {
        for_each = var.plain_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env_vars
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }

  lifecycle {
    ignore_changes = [
      # The image tag is owned by the CI/CD deploy pipeline (later PR);
      # Terraform only bootstraps the service with a placeholder. Without
      # this, every `terraform apply` would revert to var.image.
      template[0].containers[0].image,

      # Google provider v6 quirk: the API returns a top-level `scaling`
      # block populated with defaults (manual_instance_count=0,
      # min_instance_count=0), even when we only configure `template.scaling`.
      # Without ignoring it here, every `terraform plan` shows a spurious
      # in-place update trying to "remove" a block we never set. Real
      # autoscaling limits still live in `template.scaling` above.
      scaling,
    ]
  }
}

# Public HTTPS access — the chat endpoint needs to be reachable from browsers
# and Twilio. Auth is handled inside the app (session cookies, Twilio signature).
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = google_cloud_run_v2_service.app.project
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
