# Nginx reverse proxy to LiteLLM on another host (set LITELLM_HOST at runtime).
# Official image runs envsubst on /etc/nginx/templates/*.template
FROM nginx:1.27-alpine

COPY default.conf.template /etc/nginx/templates/default.conf.template
