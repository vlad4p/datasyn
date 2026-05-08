# MVP LiteLLM (app + infra)

- **`infra/`** — Terraform: VPC remote state, S3 config bucket, IAM (module `ec2-instance-profile-ssm` + inline policies), two EC2 modules (`nginx` + `litellm`), security groups, GitHub deploy key (optional). Run `terraform` from `infra/` (`backend.hcl` is there).
- **`docker-compose.yaml`** — **Postgres + LiteLLM** only; port **4000** published for the separate Nginx host.
- **`nginx-edge/`** — Dockerfile + `default.conf.template` for optional **`make deploy-mvp-nginx-edge`**; optional [`AGENT_UPSTREAM.md`](nginx-edge/AGENT_UPSTREAM.md). Terraform uses **`infra/nginx-edge.conf.tpl`** for S3 `bootstrap/nginx-edge.conf` (not duplicated under `nginx-edge/`).
- **`scripts/`** — Manual bootstrap on the **LiteLLM** instance if user-data failed.

## Quick provision

1. `cd live/mvp/networking && terraform init -backend-config=backend.hcl && terraform apply`
2. `cd live/mvp/litellm/infra && terraform init -backend-config=backend.hcl && terraform apply`
3. Browser: `http://$(terraform output -raw nginx_public_ip)/`
4. Optional: from repo root, `make deploy-mvp-nginx-edge` (custom Nginx image; needs `mvp-litellm-ec2.pem` and local Docker).

See [`../README.md`](../README.md) for full detail.
