Dockerfile design

Multi-stage to keep runtime minimal.

NGINX configured for SPA fallback & optimal caching.

Non-root on 8080 for Fargate.

Runtime JSON config so one image works everywhere.

Healthchecks aligned for Docker/ECS/ALB.

