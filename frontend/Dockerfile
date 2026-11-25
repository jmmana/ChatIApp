# syntax=docker/dockerfile:1

# --- Etapa 1: compilar el frontend ---
FROM node:22-alpine AS build
# corepack toma la versión exacta de pnpm de "packageManager" en package.json
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

# --- Etapa 2: nginx con el estático y el proxy a la API ---
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1
