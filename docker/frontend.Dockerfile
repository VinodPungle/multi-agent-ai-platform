# =============================================================================
# Frontend image — AI Platform Portal
# =============================================================================
# Build context is the repository root, matching the backend image so both are
# built the same way from CI and Compose.
#
#   docker build -f docker/frontend.Dockerfile -t agent-platform-frontend .
#
# Targets:
#   development  — Vite dev server with hot reload
#   production   — static bundle served by nginx as a non-root user  (default)
# =============================================================================

ARG NODE_VERSION=22
ARG NGINX_VERSION=1.27

# -----------------------------------------------------------------------------
# Stage 1 — dependencies
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS dependencies

WORKDIR /app

# Manifests first: `npm ci` re-runs only when a manifest changes, not on every
# source edit.
COPY src/frontend/package.json src/frontend/package-lock.json ./

# `npm ci` rather than `npm install`: it installs exactly the locked tree and
# fails if the lock file and manifest disagree, so a build is reproducible.
RUN npm ci --no-audit --no-fund

# -----------------------------------------------------------------------------
# Stage 2 — development
# -----------------------------------------------------------------------------
FROM dependencies AS development

COPY src/frontend ./

# Bind-mounted volumes on Windows and macOS do not deliver filesystem events
# into a Linux container, so the watcher must poll to see changes.
ENV VITE_USE_POLLING=true

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# -----------------------------------------------------------------------------
# Stage 3 — build
# -----------------------------------------------------------------------------
FROM dependencies AS build

COPY src/frontend ./

# Vite inlines `VITE_*` values at build time, so the API URL is a build
# argument, not a runtime setting. Deploying to a different environment means
# rebuilding — the trade the handbook accepts for a fully static, CDN-cacheable
# bundle with no runtime configuration fetch.
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_APP_NAME="Multi-Agent AI Platform"
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_APP_NAME=${VITE_APP_NAME}

# `npm run build` type-checks before bundling, so a type error fails the image
# build rather than shipping.
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 4 — production
# -----------------------------------------------------------------------------
FROM nginx:${NGINX_VERSION}-alpine AS production

# The nginx image ships an unprivileged `nginx` user; binding port 8080 rather
# than 80 avoids needing CAP_NET_BIND_SERVICE to run as that user.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

# Writable paths nginx needs when it is not root.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
 && touch /var/run/nginx.pid \
 && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
