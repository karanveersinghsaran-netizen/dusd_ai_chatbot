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
#   make up                                                  # apply
#   make deploy                                              # build + push image, deploy Cloud Run
#   make down                                                # destroy — zero the bill
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

.PHONY: help init fmt validate plan up down output console deploy _refresh

help:
	@echo "Targets (ENV=$(ENV)):"
	@echo "  init          terraform init (requires TF_STATE_BUCKET=<bucket>)"
	@echo "  fmt           terraform fmt -recursive"
	@echo "  validate      terraform validate in $(ENV_DIR)"
	@echo "  plan          terraform plan -var-file=$(TFVARS)"
	@echo "  up            terraform apply -var-file=$(TFVARS)"
	@echo "  deploy        docker build + push + gcloud run deploy (TAG=$(TAG))"
	@echo "  down          terraform destroy -var-file=$(TFVARS) — zero the bill"
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

up:
	terraform -chdir=$(ENV_DIR) apply $(TF_ARGS)

down:
	terraform -chdir=$(ENV_DIR) destroy $(TF_ARGS)

output:
	terraform -chdir=$(ENV_DIR) output

console:
	terraform -chdir=$(ENV_DIR) console

# Refresh state + outputs without touching any real resources. Used as a
# prereq for `deploy` so newly-added `output` blocks land in state without
# a full `make up`. Skips prompts; runs in ~10-30s.
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
