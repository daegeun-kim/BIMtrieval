# syntax=docker/dockerfile:1.7
#
# Viewer + chat UI: built with Vite, served as static files by nginx.
#
# The frontend holds no secret and talks to nothing but the backend's HTTP API,
# so the runtime image is just nginx and a folder of assets.

FROM node:22-bookworm-slim AS builder

WORKDIR /app

# `npm ci` from the lock file, in its own layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Where the BROWSER reaches the backend — a published host port, not the
# compose network name, because this URL is resolved by the user's browser and
# not by any container. Baked at build time: Vite inlines it.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY docker/frontend-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Probes 127.0.0.1, not `localhost`. nginx here listens on IPv4 only, while
# Alpine resolves `localhost` to ::1 first — so the probe was refused on IPv6
# and reported the container unhealthy while it was serving correctly.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
