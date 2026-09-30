# Cloud Monitoring dashboard, log-based metrics, and alert policies for the
# wms-chatbot service. Replaces ad-hoc `gcloud logging read` queries with a
# bookmarkable Cloud Console dashboard, and pages on the three failure modes
# most likely to actually matter (server errors, elevated latency, database
# and cache pressure). PR#5 / Sprint 1.7 completion.

# ── Log-based metrics ──────────────────────────────────────────────────────
# Cloud Run's built-in request metrics can chart request volume + latency +
# status codes filtered by URL, but NOT distinct-user counts — that needs a
# log-based metric with the remote IP kept as a label so the dashboard can
# `count_distinct` it over a day.

resource "google_logging_metric" "chat_requests_by_ip" {
  name        = "wms_chatbot/chat_requests_by_ip"
  description = "Counter of successful POST /chat responses, labeled by remote IP, so the dashboard can compute distinct users per time window. POST filter is required because httpRequest.requestUrl:\"/chat\" is a substring match that would otherwise catch GET /chatbox and GET /chat/history too, inflating the count with page loads and history-restores instead of tracking real messages sent."
  project     = var.project_id

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    httpRequest.requestMethod="POST"
    httpRequest.requestUrl:"/chat"
    NOT httpRequest.requestUrl:"/chat/history"
    httpRequest.status=200
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Chat requests (labeled by IP)"

    labels {
      key         = "remote_ip"
      value_type  = "STRING"
      description = "Client IP the request came from. Aggregate as count_distinct for unique-user counts."
    }
  }

  label_extractors = {
    "remote_ip" = "EXTRACT(httpRequest.remoteIp)"
  }
}

resource "google_logging_metric" "feedback_submissions" {
  name        = "wms_chatbot/feedback_submissions"
  description = "Counter of successful /feedback/{thanks,report} POSTs, labeled by which endpoint, so the dashboard can show how the feedback loop is actually being used."
  project     = var.project_id

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    httpRequest.requestMethod="POST"
    (httpRequest.requestUrl:"/feedback/thanks" OR httpRequest.requestUrl:"/feedback/report")
    httpRequest.status=200
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Feedback submissions"

    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "'thanks' or 'report' — extracted from the URL path."
    }
  }

  label_extractors = {
    "endpoint" = "REGEXP_EXTRACT(httpRequest.requestUrl, \"/feedback/(thanks|report)\")"
  }
}

# ── Notification channel ────────────────────────────────────────────────────
# Optional — only created when the operator provides an email. Alert policies
# reference it via a `for_each = var.alert_email != "" ? { ... } : {}` idiom
# so the alerts still exist (visible in the console) even if no email is set.
# The recipient must click the verification link in the first email Google
# sends; unverified channels stay in state as "unverified" and don't deliver.

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "wms-chatbot alerts"
  type         = "email"
  description  = "Ops alerts for the wms-chatbot Cloud Run service. Managed by Terraform."

  labels = {
    email_address = var.alert_email
  }
}

locals {
  notification_channels = google_monitoring_notification_channel.email[*].id
}

# ── Alert policies ─────────────────────────────────────────────────────────
# Four alerts, calibrated to fire only on real problems (not every minor spike).

resource "google_monitoring_alert_policy" "cloud_run_5xx_rate" {
  project      = var.project_id
  display_name = "wms-chatbot: elevated 5xx rate"
  combiner     = "OR"

  documentation {
    content   = "Server-error rate on wms-chatbot exceeded 5% over 5 minutes. Check Cloud Run logs for the failing route and recent deploys."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "5xx > 5% over 5m"
    condition_threshold {
      # request_count filtered to 5xx, ratio'd against total request_count.
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }

      denominator_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_count\""

      denominator_aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "chat_latency_p95" {
  project      = var.project_id
  display_name = "wms-chatbot: /chat p95 latency > 30s"
  combiner     = "OR"

  documentation {
    content   = "The 95th-percentile latency on /chat has been above 30 seconds for 5+ minutes. Usually indicates the Claude API is slow or unreachable. Verify status.anthropic.com and check for retry storms in the app logs."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "p95 latency > 30s"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 30000 # ms

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "cloud_sql_cpu" {
  project      = var.project_id
  display_name = "wms-chatbot db: CPU > 80%"
  combiner     = "OR"

  documentation {
    content   = "Cloud SQL CPU utilization stayed above 80% for 15 minutes. On db-f1-micro this is easy to trip transiently; only genuinely-sustained load is worth attention. Consider a larger tier if this fires repeatedly."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "CPU > 80% over 15m"
    condition_threshold {
      filter          = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${var.cloud_sql_instance_id}\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      duration        = "900s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "self_hosted_redis_vm_up" {
  # Only created when the self-hosted VM is deployed — module stays usable
  # without it. Uses metric-absence rather than a Cloud Monitoring uptime
  # check because the VM has no public IP; external uptime checkers can't
  # reach it. Ops Agent (installed by the VM's startup script) reports the
  # instance-uptime metric every ~60s, so a 5-minute gap is a real signal:
  # either the VM crashed, GCE rebooted it for maintenance, or the Ops
  # Agent itself stopped shipping metrics.
  count        = var.self_hosted_redis_vm_name != "" ? 1 : 0
  project      = var.project_id
  display_name = "wms-chatbot redis VM: unreachable / down"
  combiner     = "OR"

  documentation {
    content   = "The self-hosted Redis VM (${var.self_hosted_redis_vm_name}) hasn't reported its uptime metric for 5 minutes. Most likely cause: the VM rebooted, crashed, or the Google Cloud Ops Agent stopped shipping data. `gcloud compute instances describe ${var.self_hosted_redis_vm_name} --zone=<zone>` will show whether the VM is RUNNING. If it is, SSH via IAP and check `sudo systemctl status redis-server google-cloud-ops-agent`."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "VM uptime metric absent > 5m"
    condition_absent {
      filter   = "resource.type=\"gce_instance\" AND metric.type=\"compute.googleapis.com/instance/uptime\" AND metric.labels.instance_name=\"${var.self_hosted_redis_vm_name}\""
      duration = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "redis_memory" {
  project      = var.project_id
  display_name = "wms-chatbot redis: memory > 80%"
  combiner     = "OR"

  documentation {
    content   = "Redis memory usage crossed 80% of the configured 1 GB. At current usage (~5 MB) this would represent 200× growth and warrants investigation — likely a leaked key without TTL, or a runaway loop writing to Redis. Look at `commands/calls` by cmd to find the writer."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "memory used > 80%"
    condition_threshold {
      filter          = "resource.type=\"redis_instance\" AND resource.labels.instance_id=\"projects/${var.project_id}/locations/${var.region}/instances/${var.redis_instance_id}\" AND metric.type=\"redis.googleapis.com/stats/memory/usage_ratio\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy {
    auto_close = "1800s"
  }
}

# ── Dashboard ──────────────────────────────────────────────────────────────
# Three rows × 3 tiles each in a 12-col mosaic grid. Ops on top, adoption in
# the middle, resource utilization at the bottom — reading top-to-bottom
# roughly matches the "is the site up? is anyone using it? are we OK on
# capacity?" triage sequence.

resource "google_monitoring_dashboard" "wms_chatbot" {
  project = var.project_id

  # Google's dashboards API massages our JSON on write: injects
  # `targetAxis = "Y1"` defaults on every xyChart dataSet, drops
  # zero-valued xPos/yPos on tiles, etc. Terraform then reads it back and
  # sees permanent drift, showing "1 to change" on every `make apply`. The
  # drift is purely cosmetic — the dashboard renders identically either
  # way — so ignore dashboard_json changes and treat this resource as
  # write-once. When you DO intentionally want to update the dashboard,
  # force a re-apply with:
  #   terraform apply -replace=module.monitoring.google_monitoring_dashboard.wms_chatbot
  lifecycle {
    ignore_changes = [dashboard_json]
  }

  dashboard_json = jsonencode({
    displayName = "WMS Chatbot — ops + adoption"
    mosaicLayout = {
      columns = 12
      tiles = [
        # ── Row 1: Ops ────────────────────────────────────────────────────
        {
          xPos = 0, yPos = 0, width = 4, height = 4,
          widget = {
            title = "Request rate by status class"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.response_code_class"]
                    }
                  }
                }
                plotType = "STACKED_AREA"
              }]
              timeshiftDuration = "0s"
              yAxis             = { label = "req/s", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 4, yPos = 0, width = 4, height = 4,
          widget = {
            title = "Latency p50/p95/p99"
            xyChart = {
              dataSets = [
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_50"
                        crossSeriesReducer = "REDUCE_MEAN"
                      }
                    }
                  }
                  plotType       = "LINE"
                  legendTemplate = "p50"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_95"
                        crossSeriesReducer = "REDUCE_MEAN"
                      }
                    }
                  }
                  plotType       = "LINE"
                  legendTemplate = "p95"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_99"
                        crossSeriesReducer = "REDUCE_MEAN"
                      }
                    }
                  }
                  plotType       = "LINE"
                  legendTemplate = "p99"
                }
              ]
              yAxis = { label = "ms", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 8, yPos = 0, width = 4, height = 4,
          widget = {
            title = "Cloud Run instance count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/container/instance_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.state"]
                    }
                  }
                }
                plotType = "STACKED_AREA"
              }]
              yAxis = { label = "instances", scale = "LINEAR" }
            }
          }
        },

        # ── Row 2: Adoption scorecards (at-a-glance D/W/M) ────────────────
        # Four compact cards showing the "how many people used this
        # today / this week / this month" numbers without needing to
        # eyeball the trend charts below. Sparklines under each show a
        # short trend so week-over-week direction is visible even without
        # a formal comparison widget (Cloud Monitoring's scorecards don't
        # do %-change comparisons out of the box).
        {
          xPos = 0, yPos = 4, width = 3, height = 3,
          widget = {
            title = "Unique users — today"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_requests_by_ip.name}\""
                  aggregation = {
                    # Same distinct-IP-per-day math as the trend chart —
                    # scorecard shows the latest bucket's value.
                    alignmentPeriod    = "86400s"
                    perSeriesAligner   = "ALIGN_COUNT"
                    crossSeriesReducer = "REDUCE_COUNT"
                  }
                }
              }
              sparkChartView = {
                sparkChartType = "SPARK_BAR"
              }
            }
          }
        },
        {
          xPos = 3, yPos = 4, width = 3, height = 3,
          widget = {
            title = "Unique users — last 7 days"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_requests_by_ip.name}\""
                  aggregation = {
                    # 7-day bucket = weekly unique-IP count. Sparkline
                    # below shows previous weeks' buckets, so w/w change
                    # is visible without a formal percent widget.
                    alignmentPeriod    = "604800s"
                    perSeriesAligner   = "ALIGN_COUNT"
                    crossSeriesReducer = "REDUCE_COUNT"
                  }
                }
              }
              sparkChartView = {
                sparkChartType = "SPARK_BAR"
              }
            }
          }
        },
        {
          xPos = 6, yPos = 4, width = 3, height = 3,
          widget = {
            title = "Unique users — last 30 days"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_requests_by_ip.name}\""
                  aggregation = {
                    alignmentPeriod    = "2592000s"
                    perSeriesAligner   = "ALIGN_COUNT"
                    crossSeriesReducer = "REDUCE_COUNT"
                  }
                }
              }
              sparkChartView = {
                sparkChartType = "SPARK_BAR"
              }
            }
          }
        },
        {
          xPos = 9, yPos = 4, width = 3, height = 3,
          widget = {
            title = "Thanks — last 7 days"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  # Filter on the endpoint label so this scorecard sums only
                  # "thanks" clicks, not report submissions. The Row 3
                  # stacked-bar tile still shows the full thanks-vs-report
                  # split if the breakdown matters.
                  filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.feedback_submissions.name}\" metric.label.endpoint=\"thanks\""
                  aggregation = {
                    alignmentPeriod    = "604800s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = {
                sparkChartType = "SPARK_BAR"
              }
            }
          }
        },

        # ── Row 3: Adoption trends (daily bars, all history) ─────────────
        {
          xPos = 0, yPos = 7, width = 4, height = 4,
          widget = {
            title = "Chat requests per day"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_requests_by_ip.name}\""
                    aggregation = {
                      alignmentPeriod    = "86400s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType = "STACKED_BAR"
              }]
              yAxis = { label = "chats/day", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 4, yPos = 7, width = 4, height = 4,
          widget = {
            title = "Unique users per day (distinct IPs)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_requests_by_ip.name}\""
                    # Each remote_ip label value = one input series. Aligning
                    # per series to 24h counts events per IP per day, then
                    # crossSeriesReducer REDUCE_COUNT collapses everything
                    # into a single output series counting how many input
                    # series had data in each daily bucket — which is exactly
                    # "unique IPs per day". No groupByFields on purpose: any
                    # field preserved there re-splits the output back into
                    # multiple series and silently defeats the distinct-count.
                    aggregation = {
                      alignmentPeriod    = "86400s"
                      perSeriesAligner   = "ALIGN_COUNT"
                      crossSeriesReducer = "REDUCE_COUNT"
                    }
                  }
                }
                plotType = "STACKED_BAR"
              }]
              yAxis = { label = "unique IPs/day", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 8, yPos = 7, width = 4, height = 4,
          widget = {
            title = "Feedback submissions per day (stacked by endpoint)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.feedback_submissions.name}\""
                    aggregation = {
                      alignmentPeriod    = "86400s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.endpoint"]
                    }
                  }
                }
                plotType = "STACKED_BAR"
              }]
              yAxis = { label = "submissions/day", scale = "LINEAR" }
            }
          }
        },

        # ── Row 4: Resource utilization ───────────────────────────────────
        {
          xPos = 0, yPos = 11, width = 4, height = 4,
          widget = {
            title = "Cloud SQL CPU %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${var.cloud_sql_instance_id}\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "utilization", scale = "LINEAR" }
              # XyChart threshold blocks only accept `value` and `label` —
              # `color`, `direction`, and `targetAxis` are Scorecard-only and
              # rejected here (Cloud Monitoring API returns 400). The line
              # still renders horizontally at the value using default styling.
              thresholds = [{ value = 0.8, label = "alert" }]
            }
          }
        },
        {
          xPos = 4, yPos = 11, width = 4, height = 4,
          widget = {
            title = "Redis memory used %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"redis_instance\" AND resource.labels.instance_id=\"projects/${var.project_id}/locations/${var.region}/instances/${var.redis_instance_id}\" AND metric.type=\"redis.googleapis.com/stats/memory/usage_ratio\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "utilization", scale = "LINEAR" }
              # XyChart threshold blocks only accept `value` and `label` —
              # `color`, `direction`, and `targetAxis` are Scorecard-only and
              # rejected here (Cloud Monitoring API returns 400). The line
              # still renders horizontally at the value using default styling.
              thresholds = [{ value = 0.8, label = "alert" }]
            }
          }
        },
        {
          xPos = 8, yPos = 11, width = 4, height = 4,
          widget = {
            title = "Redis key count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"redis_instance\" AND resource.labels.instance_id=\"projects/${var.project_id}/locations/${var.region}/instances/${var.redis_instance_id}\" AND metric.type=\"redis.googleapis.com/keyspace/keys\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "keys", scale = "LINEAR" }
            }
          }
        },

        # ── Row 5: Self-hosted Redis VM (added alongside MemoryStore
        #    tiles above during the cutover — keep both so you can watch
        #    MemoryStore go idle while the VM picks up traffic. Both rows
        #    stay until PR 3 destroys MemoryStore, at which point Row 4's
        #    two Redis tiles come out.) ───────────────────────────────────
        {
          xPos = 0, yPos = 15, width = 4, height = 4,
          widget = {
            title = "VM Redis: CPU %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = var.self_hosted_redis_vm_name != "" ? "resource.type=\"gce_instance\" AND metric.type=\"compute.googleapis.com/instance/cpu/utilization\" AND metric.labels.instance_name=\"${var.self_hosted_redis_vm_name}\"" : ""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "utilization", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 4, yPos = 15, width = 4, height = 4,
          widget = {
            title = "VM Redis: memory used %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    # agent.googleapis.com metrics come from the Google Cloud
                    # Ops Agent installed on the VM (see startup.sh.tftpl).
                    # memory/percent_used is a straightforward 0-100 gauge.
                    filter = var.self_hosted_redis_vm_name != "" ? "resource.type=\"gce_instance\" AND metric.type=\"agent.googleapis.com/memory/percent_used\" AND metric.labels.instance_name=\"${var.self_hosted_redis_vm_name}\"" : ""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "percent", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 8, yPos = 15, width = 4, height = 4,
          widget = {
            title = "VM Redis: uptime (s)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    # A drop to 0 = VM rebooted (planned maintenance or
                    # crash). Cross-references the VM-down alert policy.
                    filter = var.self_hosted_redis_vm_name != "" ? "resource.type=\"gce_instance\" AND metric.type=\"compute.googleapis.com/instance/uptime\" AND metric.labels.instance_name=\"${var.self_hosted_redis_vm_name}\"" : ""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
              yAxis = { label = "seconds", scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })
}
