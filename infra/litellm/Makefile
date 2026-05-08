# Nginx edge image + deploy to the Nginx EC2 (same PEM as Terraform).
# Run from: live/mvp/litellm  (or via repo root Makefile: make deploy-mvp-nginx-edge)
#
# Requires: docker, ssh, terraform outputs (run terraform apply first).
#   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN  # if using SSO profile for terraform output

INFRA         ?= infra
KEY           ?= mvp-litellm-ec2.pem
SSH_USER      ?= ec2-user
IMAGE_NAME    ?= mvp-nginx-edge
CONTAINER_NAME ?= mvp-nginx-edge-docker

.PHONY: tf-outputs deploy-nginx-edge-docker

tf-outputs:
	@cd $(INFRA) && terraform output -json | head -c 200 && echo "..."

# Private IP of LiteLLM host (upstream). Public IP of Nginx host (SSH target).
LITELLM_PRIVATE_IP ?= $(shell cd $(INFRA) && terraform output -raw litellm_private_ip)
NGINX_PUBLIC_IP    ?= $(shell cd $(INFRA) && terraform output -raw nginx_public_ip)

deploy-nginx-edge-docker: ## Build image, copy to Nginx EC2, run with LITELLM_HOST set from Terraform.
	@test -f "$(KEY)" || (echo "Missing $(KEY); set KEY=path/to/mvp-litellm-ec2.pem" >&2; exit 1)
	docker build -t $(IMAGE_NAME) ./nginx-edge
	docker save $(IMAGE_NAME) | ssh -o StrictHostKeyChecking=accept-new -i "$(KEY)" "$(SSH_USER)@$(NGINX_PUBLIC_IP)" docker load
	ssh -i "$(KEY)" "$(SSH_USER)@$(NGINX_PUBLIC_IP)" 'docker rm -f mvp-nginx-edge $(CONTAINER_NAME) 2>/dev/null; true'
	ssh -i "$(KEY)" "$(SSH_USER)@$(NGINX_PUBLIC_IP)" \
		"docker run -d --name $(CONTAINER_NAME) --restart unless-stopped -p 80:80 \
		-e LITELLM_HOST=$(LITELLM_PRIVATE_IP) $(IMAGE_NAME)"
