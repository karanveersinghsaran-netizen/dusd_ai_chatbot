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
#   make down                                                # destroy — zero the bill
#   make output                                              # show URLs, SAs, image base

ENV ?= staging
TFVARS ?= terraform.tfvars
ENV_DIR := envs/$(ENV)
TF_ARGS := -var-file=$(TFVARS)

.PHONY: help init fmt validate plan up down output console

help:
	@echo "Targets (ENV=$(ENV)):"
	@echo "  init          terraform init (requires TF_STATE_BUCKET=<bucket>)"
	@echo "  fmt           terraform fmt -recursive"
	@echo "  validate      terraform validate in $(ENV_DIR)"
	@echo "  plan          terraform plan -var-file=$(TFVARS)"
	@echo "  up            terraform apply -var-file=$(TFVARS)"
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
