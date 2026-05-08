# Route public traffic to the Ubika agent (MVP)

The Ubika **MVP** stack may run a FastAPI agent on **another EC2** in the same VPC. The **Nginx edge** host (separate instance from LiteLLM) reverse-proxies paths to that instance (e.g. port **8000**).

## 1. Security groups

The **agent** instance security group should allow **ingress TCP 8000** from the **edge** security group (`edge_security_group_id` in Terraform outputs). The **Nginx** EC2 is the only instance with the `edge` SG, so Nginx can connect to the agent private IP.

## 2. Config files (pick one workflow)

| Workflow | Edit |
|----------|------|
| Bootstrap from Terraform / S3 | [`../infra/nginx-edge.conf.tpl`](../infra/nginx-edge.conf.tpl) — `terraform apply` refreshes `bootstrap/nginx-edge.conf`; restart or replace the Nginx instance, or re-fetch S3 and restart the container on the **Nginx** host. |
| Custom image (`make deploy-mvp-nginx-edge`) | [`default.conf.template`](default.conf.template) in this folder — rebuild/redeploy the image. |

Add a `location` block **above** the generic `location /` catch-all:

```nginx
location /api/ {
    proxy_pass http://AGENT_PRIVATE_IP:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;
}
```

## 3. Reload on the Nginx EC2

Stock image (user-data):

```bash
sudo docker exec mvp-nginx-edge nginx -t && sudo docker exec mvp-nginx-edge nginx -s reload
```

Custom image from this folder:

```bash
sudo docker exec mvp-nginx-edge-docker nginx -t && sudo docker exec mvp-nginx-edge-docker nginx -s reload
```

(Adjust container name if you changed it in the Makefile.)
