#!/usr/bin/env bash
set -euo pipefail

# Create runtime config JSON from environment variables so you can
# change API endpoints, stages, flags per environment WITHOUT rebuilding.
# Read these in your Angular app via HTTP GET /assets/runtime-config.json

RUNTIME_DIR="/usr/share/nginx/html/assets"
mkdir -p "$RUNTIME_DIR"

cat > "$RUNTIME_DIR/runtime-config.json" <<EOF
{
  "apiBaseUrl": "${API_BASE_URL:-https://api.example.com}",
  "stage": "${STAGE:-prod}",
  "featureXEnabled": ${FEATURE_X_ENABLED:-false}
}
EOF

# Start nginx (foreground)
exec "$@"
