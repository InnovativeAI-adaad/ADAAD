#!/usr/bin/env bash
# ADAAD Subdomain Deployment Script
# Authority: HUMAN-0 · Dustin L. Reid
# Run as root on the adaad.pro server
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NGINX_CONF="$REPO_ROOT/ops/nginx/adaad.conf"
WEBROOT="/var/www/adaad/public"

echo "▶ ADAAD subdomain deployment"
echo "  Config: $NGINX_CONF"
echo "  Webroot: $WEBROOT"

# 1. Copy static landing page
mkdir -p "$WEBROOT"
cp -r "$REPO_ROOT/public/"* "$WEBROOT/"
echo "  ✔ Landing page deployed to $WEBROOT"

# 2. Install nginx config
cp "$NGINX_CONF" /etc/nginx/sites-available/adaad.conf
ln -sf /etc/nginx/sites-available/adaad.conf /etc/nginx/sites-enabled/adaad.conf
echo "  ✔ Nginx config installed"

# 3. Test nginx config
nginx -t
echo "  ✔ Nginx config valid"

# 4. Obtain/renew certs (skip if already present)
if [ ! -f /etc/letsencrypt/live/adaad.pro/fullchain.pem ]; then
    echo "  ▶ Obtaining TLS certificates..."
    certbot --nginx \
        -d adaad.pro \
        -d www.adaad.pro \
        -d aponi.adaad.pro \
        -d api.adaad.pro \
        -d docs.adaad.pro \
        --non-interactive \
        --agree-tos \
        --email dev@innovativeai.io
    echo "  ✔ Certificates obtained"
else
    echo "  ✔ Certificates already present — run: certbot renew"
fi

# 5. Reload nginx
systemctl reload nginx
echo "  ✔ Nginx reloaded"

echo ""
echo "✅ Deployment complete"
echo "   https://adaad.pro          → landing page"
echo "   https://aponi.adaad.pro    → Aponi governance dashboard"
echo "   https://api.adaad.pro      → ADAAD REST API"
echo "   https://docs.adaad.pro     → Documentation"
