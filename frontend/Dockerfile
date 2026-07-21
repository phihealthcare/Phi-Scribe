# Frontend (Vite/React), built to static files and served by nginx, which
# also reverse-proxies /api/ to the backend container. This keeps frontend
# and backend on the same origin in production so no CORS setup is needed
# (the Flask app only enables CORS in DEBUG/development mode — see
# app/__init__.py).

FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* vars at build time. Default assumes this image's own
# nginx proxies /api/* to the backend (see nginx.conf) — override only if
# the API is served from a different origin.
ARG VITE_API_BASE_URL=/api/v1/audio
ARG VITE_USE_MOCK=false
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_USE_MOCK=$VITE_USE_MOCK
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:80/ || exit 1
