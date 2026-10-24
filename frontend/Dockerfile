# syntax=docker/dockerfile:1
# Production image of the web interface. Build from the frontend directory:
#   docker build -t uaw-frontend .
# Run with API_URL (the backend, as seen from this container) and API_KEY.

FROM node:22-bookworm-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Dependencies first: this layer is reused as long as the lock file does not change.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build

# --- Runtime stage: the standalone server only (output: "standalone") ---
FROM node:22-bookworm-slim
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
