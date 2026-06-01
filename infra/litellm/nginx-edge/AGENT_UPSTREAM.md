# Route public traffic to the datasyn brain

The **datasyn** stack may run a FastAPI brain on a **private host** in your VPC. An **Nginx edge** instance reverse-proxies paths to that host (e.g. port **8002** on the brain container or **8000** inside it).

## 1. Security groups / firewall

The **brain** host should allow **ingress** on the brain port only from the **edge** proxy (security group, firewall rule, or private network). Do not expose MCP ports (`8040`, `8044`) or MinIO to the public internet.

## 2. Config files (pick one workflow)

| Workflow | Edit |
|----------|------|
| Bootstrap from IaC / S3 | Your nginx template — refresh config and reload the edge container. |
| Custom image (`make deploy-mvp-nginx-edge`) | [`default.conf.template`](default.conf.template) in this folder — rebuild/redeploy the image. |

Add a `location` block **above** the generic `location /` catch-all:

```nginx
location /api/ {
    proxy_pass http://BRAIN_PRIVATE_IP:8002;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;
}
```

Adjust port if the brain listens on `8000` inside the VPC without the Docker host mapping.

## 3. Reload Nginx

```bash
sudo docker exec <nginx-container> nginx -t && sudo docker exec <nginx-container> nginx -s reload
```

Enable OAuth on the brain (`OAUTH_*` in `.env.example`) before routing public traffic to `/api/agent/chat`.
