# Self-hosted Redis on a single e2-micro VM in the same VPC as Cloud Run's
# VPC connector. Replaces the managed MemoryStore instance (~$36/mo) with a
# ~$5/mo VM + GCS snapshots for durability. Trade-off: no HA — a VM crash or
# maintenance event takes Redis down for the few minutes it takes GCE to
# reboot. Given actual usage (~200 commands/day, conversation history that
# already resets on token expiry), the ops burden is acceptable for the
# ~85% cost cut.
#
# Not a drop-in replacement for MemoryStore's Terraform interface — the
# consumer wires REDIS_URL from this module's `redis_url` output the same
# way it did before.

# ── Redis AUTH password ────────────────────────────────────────────────────
# Defense-in-depth on top of the VPC + firewall. Randomly generated once,
# lives in Secret Manager; the VM fetches it at every boot so a password
# rotation is "add new secret version, reboot VM, rotate REDIS_URL secret,
# make deploy". Never in metadata (invisible to compute.instances.get) and
# never in the startup script text (invisible to instance-view).
resource "random_password" "redis" {
  length  = 32
  special = false # Redis handles it fine, but URL-encoding + shell-escaping trip on ! $ etc — alphanumeric is safer for the redis://:pass@host URL form.
}

resource "google_secret_manager_secret" "redis_password" {
  project   = var.project_id
  secret_id = "${var.instance_name}-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "redis_password" {
  secret      = google_secret_manager_secret.redis_password.id
  secret_data = random_password.redis.result
}

resource "google_secret_manager_secret_iam_member" "vm_reads_password" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.redis_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vm.email}"
}

# ── GCS bucket for periodic RDB snapshots ──────────────────────────────────
# Random suffix so a make destroy-all + reapply doesn't collide with a
# still-being-deleted bucket (GCS bucket names have a soft delete window).
resource "random_id" "snapshot_bucket_suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "snapshots" {
  project                     = var.project_id
  name                        = "${var.instance_name}-snapshots-${random_id.snapshot_bucket_suffix.hex}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = true

  # Belt-and-suspenders: the systemd timer also prunes to the retention
  # count, but a lifecycle rule guarantees old snapshots eventually go away
  # even if the timer fails. 30 days is well past any reasonable recovery
  # window for a chat app that already TTLs conversations at 30d.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# ── VM service account ─────────────────────────────────────────────────────
# Dedicated SA so the VM has exactly the permissions it needs (write
# snapshots to its GCS bucket, write metrics/logs to Cloud Monitoring +
# Logging) and nothing else.
resource "google_service_account" "vm" {
  project      = var.project_id
  account_id   = "${var.instance_name}-vm"
  display_name = "wms-chatbot self-hosted Redis VM"
}

resource "google_storage_bucket_iam_member" "vm_snapshot_writer" {
  bucket = google_storage_bucket.snapshots.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_project_iam_member" "vm_metrics_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_project_iam_member" "vm_logs_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

# ── Reserved static internal IP ────────────────────────────────────────────
# Reserving the IP means REDIS_URL doesn't change if the VM is recreated —
# Cloud Run keeps working without a secret rotation + revision restart.
resource "google_compute_address" "redis" {
  project      = var.project_id
  name         = "${var.instance_name}-internal-ip"
  region       = var.region
  subnetwork   = var.subnetwork_id
  address_type = "INTERNAL"
  purpose      = "GCE_ENDPOINT"
}

# ── Firewall: connector CIDR → VM :6379 ────────────────────────────────────
# Only traffic from the Cloud Run VPC access connector's /28 is allowed to
# hit Redis. Anything else in the VPC (or externally, though the VM has no
# external IP) is denied by default because we don't add an accept rule.
resource "google_compute_firewall" "redis_from_connector" {
  project = var.project_id
  name    = "${var.instance_name}-from-connector"
  network = var.network_id

  direction     = "INGRESS"
  source_ranges = [var.connector_cidr]
  target_tags   = ["${var.instance_name}-redis"]

  allow {
    protocol = "tcp"
    ports    = ["6379"]
  }
}

# IAP TCP tunnel SSH — Cloud Identity-Aware Proxy relays SSH connections
# through this range (documented at cloud.google.com/iap/docs/using-tcp-forwarding).
# Without this rule our custom VPC's implicit deny blocks SSH via IAP, and
# since the VM has no public IP there's no other way to reach :22 for
# operational tasks (checking systemd status, restoring from a snapshot,
# rotating passwords). Access is still IAM-gated on Google's side — the
# person SSHing needs roles/iap.tunnelResourceAccessor + compute.instanceAdmin
# regardless of this network rule.
resource "google_compute_firewall" "iap_ssh" {
  project = var.project_id
  name    = "${var.instance_name}-iap-ssh"
  network = var.network_id

  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["${var.instance_name}-redis"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# ── The VM itself ──────────────────────────────────────────────────────────
resource "google_compute_instance" "redis" {
  project      = var.project_id
  name         = var.instance_name
  zone         = var.zone
  machine_type = var.machine_type

  tags = ["${var.instance_name}-redis"]

  boot_disk {
    initialize_params {
      # Debian 12 (bookworm) — long-term stable, Redis 7 in apt.
      image = "debian-cloud/debian-12"
      size  = 10 # GB — plenty for OS + Redis dump.rdb (~5 MB today)
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = var.subnetwork_id
    network_ip = google_compute_address.redis.address
    # No access_config block = no public IP. VPC-private only.
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = templatefile("${path.module}/startup.sh.tftpl", {
    redis_maxmemory          = var.redis_maxmemory
    gcs_bucket               = google_storage_bucket.snapshots.name
    snapshot_interval        = var.snapshot_interval
    snapshot_retention_count = var.snapshot_retention_count
    project_id               = var.project_id
    password_secret_id       = google_secret_manager_secret.redis_password.secret_id
  })

  # If we ever want to swap machine types, the disk (and its data) should
  # survive. Ignore changes to the image field so an OS image refresh doesn't
  # force VM replacement + data loss.
  lifecycle {
    ignore_changes = [
      boot_disk[0].initialize_params[0].image,
    ]
  }

  # Cloud Ops Agent is installed by the startup script; this label doesn't
  # gate it, but tags the instance so it's visible as "monitoring-enabled"
  # in the console listing.
  labels = {
    monitoring = "enabled"
    component  = "redis"
  }

  depends_on = [
    google_storage_bucket_iam_member.vm_snapshot_writer,
    google_project_iam_member.vm_metrics_writer,
    google_project_iam_member.vm_logs_writer,
    google_secret_manager_secret_iam_member.vm_reads_password,
    google_secret_manager_secret_version.redis_password,
  ]
}
