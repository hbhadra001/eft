# ===== 1) BUILD STAGE =====
FROM node:20-alpine AS build
WORKDIR /app

# Speed up installs
ENV CI=true
# Optional: set Angular CLI cache
ENV NG_CLI_ANALYTICS=false

# Install dependencies first (better caching)
COPY package*.json ./
RUN npm ci --omit=dev

# Copy sources and build
COPY . .
# If using Angular 17+:  npm run build -- --configuration=production
# If Angular <=16:       npm run build -- --prod
RUN npm run build -- --configuration=production

# Angular dist path (adjust if your project name differs)
# Example dist: /app/dist/<your-app>
# We'll detect it at runtime in the next stage via ARG if needed.


# ===== 2) RUNTIME STAGE =====
FROM nginx:1.27-alpine

# --- Security/size hardening ---
# Remove default modules you don't need (optional),
# and add tools used only at runtime (sh, envsubst from gettext)
RUN apk add --no-cache bash curl gettext

# Copy custom NGINX config
COPY ops/nginx.conf /etc/nginx/nginx.conf

# Copy a minimal default site
RUN mkdir -p /usr/share/nginx/html
# Copy Angular build output (update <your-app> to the actual folder in dist)
COPY --from=build /app/dist /usr/share/nginx/html

# Runtime config writer (injects ENV into a JSON that your app can read)
COPY ops/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Healthcheck: NGINX responds on 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8080/health || exit 1

# Run as non-root; ensure port >1024
# Create an unprivileged user and give it ownership of web root and nginx dirs that need write/read
RUN addgroup -S web && adduser -S web -G web \
 && chown -R web:web /var/cache/nginx /var/run /var/log/nginx /usr/share/nginx/html
USER web

EXPOSE 8080

# Use a small wrapper entrypoint that renders runtime config, then starts nginx
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
