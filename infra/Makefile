# Wrappers around Terraform for the wms-chatbot infra.
#
# Usage: run from infra/  (or `make -C infra <target>` from anywhere).
#
#   ENV                = staging (default) — subdir under envs/
#   TFVARS             = terraform.tfvars — passed via -var-file
#   TF_STATE_BUCKET    = required for `make init` — the GCS bucket that
#                        holds remote state (bootstrapped per docs/deploy.md)
#
# Common flow:
#   make init TF_STATE_BUCKET=wms-chatbot-staging-tfstate   # one-time
#   make plan                                                # dry-run
#   make apply                                               # provision infra
#   make deploy                                              # build + push image, deploy Cloud Run
#   make chatbox-token                                       # mint a /chatbox access link (DAYS=7)
#   make chatbox-token GENERIC=1                             # ...a no-identity link for mass distribution
#   make destroy                                             # zero the bill — preserves secrets
#   make destroy-all                                         # nuke everything, including secret containers
#   make output                                              # show URLs, SAs, image base

ENV ?= staging
TFVARS ?= terraform.tfvars
ENV_DIR := envs/$(ENV)
TF_ARGS := -var-file=$(TFVARS)

# Repo root, relative to this Makefile (infra/). Used by `make deploy` as the
# docker build context so it picks up Dockerfile + app source.
REPO_ROOT := $(abspath ..)

# Image tag for `make deploy`. Defaults to git short SHA so every deploy is
# traceable to a commit; override with `TAG=... make deploy` for ad-hoc pushes.
TAG ?= $(shell git -C $(REPO_ROOT) rev-parse --short HEAD 2>/dev/null)

# Validity window for `make chatbox-token`. Override with `DAYS=... make chatbox-token`.
DAYS ?= 7

# Set to any non-empty value (e.g. `GENERIC=1 make chatbox-token`) to mint a
# mass-distribution link with no personal identity baked in — the correct
# choice for one link shared with many people (e.g. every parent at a
# school), as opposed to the default per-person link. See
# scripts/generate_chatbox_token.py and app/security/identity.py for what
# this actually changes.
GENERIC ?=

# Resources `make destroy` will tear down. Deliberately preserves several
# things that are cheap-to-keep or expensive-to-recreate:
#   - module.secrets            — real secret values must survive destroy.
#   - google_project_service    — APIs stay enabled; re-toggling adds minutes.
#   - Most of module.network    — VPC, subnet, peering, IAM are all free.
#     Destroying the peering (google_service_networking_connection) fails
#     with "Producer services still using this connection" because Google's
#     backend cleanup of Cloud SQL / MemoryStore lags behind Terraform's
#     view by several minutes. Since peering is free, just keep it.
#
# The only paid piece inside module.network is the VPC Access connector
# (~$5-10/mo for 2× e2-micro), so that's targeted explicitly for destroy.
#
# `google_secret_manager_secret_iam_member.cloud_run_access` is targeted so
# the IAM bindings referencing the (about-to-be-destroyed) Cloud Run runtime
# SA don't dangle in state after destroy.
DESTROY_TARGETS := \
	-target=module.cloud_run \
	-target=module.cloud_sql \
	-target=module.redis \
	-target=module.self_hosted_redis.google_compute_instance.redis \
	-target=module.self_hosted_redis.google_compute_address.redis \
	-target=module.self_hosted_redis.google_compute_firewall.redis_from_connector \
	-target=module.artifact_registry \
	-target=module.network.google_vpc_access_connector.connector \
	-target=google_secret_manager_secret_iam_member.cloud_run_access

.PHONY: help init fmt validate plan apply destroy destroy-all output console deploy chatbox-token nat-on nat-off _refresh

help:
	@echo "Targets (ENV=$(ENV)):"
	@echo "  init          terraform init (requires TF_STATE_BUCKET=<bucket>)"
	@echo "  fmt           terraform fmt -recursive"
	@echo "  validate      terraform validate in $(ENV_DIR)"
	@echo "  plan          terraform plan -var-file=$(TFVARS)"
	@echo "  apply         terraform apply -var-file=$(TFVARS) — provision infra"
	@echo "  deploy        docker build + push + gcloud run deploy (TAG=$(TAG))"
	@echo "  chatbox-token mint a /chatbox access link, valid DAYS=$(DAYS) days (GENERIC=1 for a mass-distribution link with no personal identity)"
	@echo "  nat-on        provision Cloud NAT (VM regains outbound internet — needed for apt-get)"
	@echo "  nat-off       destroy Cloud NAT (~\$$1-2/mo saved; VM keeps Google APIs via Private Google Access)"
	@echo "  destroy       terraform destroy -target=<ephemeral modules> — zero the bill,"
	@echo "                preserves Secret Manager containers + real values"
	@echo "  destroy-all   terraform destroy (no targets) — nuke EVERYTHING, secrets included"
	@echo "  output        terraform output"
	@echo "  console       terraform console"

init:
	@if [ -z "$(TF_STATE_BUCKET)" ]; then \
		echo "error: TF_STATE_BUCKET is required (e.g. TF_STATE_BUCKET=wms-chatbot-$(ENV)-tfstate make init)"; \
		exit 1; \
	fi
	terraform -chdir=$(ENV_DIR) init -backend-config="bucket=$(TF_STATE_BUCKET)"

fmt:
	terraform fmt -recursive .

validate:
	terraform -chdir=$(ENV_DIR) validate

plan:
	terraform -chdir=$(ENV_DIR) plan $(TF_ARGS)

apply:
	terraform -chdir=$(ENV_DIR) apply $(TF_ARGS)

# Destroys ephemeral resources (Cloud SQL, Redis, VPC, Cloud Run, Artifact
# Registry) but preserves module.secrets — the containers and any real values
# added via `gcloud secrets versions add` survive. Also preserves the API
# enablement resources so the next `make apply` doesn't re-toggle them.
destroy:
	terraform -chdir=$(ENV_DIR) destroy $(DESTROY_TARGETS) $(TF_ARGS)

# Full teardown, including secret containers. Real secret values will be
# LOST. Only for permanent project retirement.
destroy-all:
	terraform -chdir=$(ENV_DIR) destroy $(TF_ARGS)

output:
	terraform -chdir=$(ENV_DIR) output

console:
	terraform -chdir=$(ENV_DIR) console

# Cloud NAT toggle — private VMs (self-hosted Redis) need outbound internet
# for apt-get installs and OS/Ops-Agent updates, but not for day-to-day
# Redis serving (Google APIs go via Private Google Access). Toggling saves
# ~$1-2/mo when NAT isn't needed. The `enable_nat` variable defaults to
# false so steady-state `make apply` doesn't recreate NAT — flip it on
# before booting/replacing a VM, then off once startup finishes.
nat-on:
	@echo "Bringing Cloud NAT UP — VM will regain outbound internet access."
	terraform -chdir=$(ENV_DIR) apply $(TF_ARGS) -var enable_nat=true

nat-off:
	@echo "Taking Cloud NAT DOWN — VM will lose outbound internet access."
	@echo "  (Google APIs still work via Private Google Access.)"
	@echo "  Bring back with: make nat-on"
	terraform -chdir=$(ENV_DIR) apply $(TF_ARGS) -var enable_nat=false

# Refresh state + outputs without touching any real resources. Used as a
# prereq for `deploy` so newly-added `output` blocks land in state without
# a full `make apply`. Skips prompts; runs in ~10-30s.
_refresh:
	@terraform -chdir=$(ENV_DIR) apply -refresh-only -auto-approve $(TF_ARGS) >/dev/null

# Manual deploy loop until the GitHub Actions workflow (Sprint 1.7 PR4) lands.
# Reads project/region/service/image-base from terraform outputs so it stays
# in sync with what infra actually provisioned. Always builds --platform
# linux/amd64 because Cloud Run is x86 (matters on Apple Silicon dev boxes).
deploy: _refresh
	@if [ -z "$(TAG)" ]; then echo "error: TAG could not be derived (not a git repo?). Set TAG=<something>."; exit 1; fi
	@REGION=$$(terraform -chdir=$(ENV_DIR) output -raw region) && \
	 SERVICE=$$(terraform -chdir=$(ENV_DIR) output -raw cloud_run_service_name) && \
	 IMG_BASE=$$(terraform -chdir=$(ENV_DIR) output -raw artifact_registry_image_base) && \
	 IMG=$${IMG_BASE}/app:$(TAG) && \
	 echo "==> Deploying $$IMG to Cloud Run service $$SERVICE ($$REGION)" && \
	 gcloud auth configure-docker $${REGION}-docker.pkg.dev --quiet && \
	 docker build --platform linux/amd64 -t $$IMG $(REPO_ROOT) && \
	 docker push $$IMG && \
	 gcloud run deploy $$SERVICE --region=$$REGION --image=$$IMG && \
	 echo "==> Deployed. Health check:" && \
	 curl -sSf "$$(terraform -chdir=$(ENV_DIR) output -raw cloud_run_url)/" && echo

# Mints a signed, self-expiring /chatbox access link — no redeploy required,
# it's a pure local computation against the already-deployed signing key
# (see docs/security.md § /chatbox access token). Fetches the key fresh from
# Secret Manager each run rather than relying on a local .env, so the link
# always matches what the running Cloud Run revision actually verifies
# against. Runs from REPO_ROOT (not infra/) so `scripts`/`app` are importable
# via `python -m`, and prefers the repo's own .venv if one exists.
#
# Personal (default) vs GENERIC=1: the underlying script defaults to a
# per-person link (a random identity baked into the token — fine for a
# single admin's own preview link, wrong for anything handed out broadly,
# since everyone who opens it would share that one identity/conversation).
# GENERIC=1 passes --generic instead, which embeds no personal identity;
# each visitor gets their own from their own device's session cookie.
chatbox-token:
	@PROJECT_ID=$$(terraform -chdir=$(ENV_DIR) output -raw project_id) && \
	 URL=$$(terraform -chdir=$(ENV_DIR) output -raw cloud_run_url) && \
	 SIGNING_KEY=$$(gcloud secrets versions access latest \
	   --secret=CHATBOX_TOKEN_SIGNING_KEY --project=$$PROJECT_ID) && \
	 PYTHON=$$( [ -x $(REPO_ROOT)/.venv/bin/python3 ] && echo $(REPO_ROOT)/.venv/bin/python3 || echo python3 ) && \
	 cd $(REPO_ROOT) && \
	 CHATBOX_TOKEN_SIGNING_KEY=$$SIGNING_KEY $$PYTHON -m scripts.generate_chatbox_token --base-url "$$URL" --days $(DAYS) $(if $(GENERIC),--generic,)
