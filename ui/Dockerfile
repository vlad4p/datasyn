# syntax=docker/dockerfile:1
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src ./src
COPY images ./images

# Docker publish: skip tsc + skip minify on huge vendor chunks (internal registry).
ENV NODE_ENV=production VITE_FAST_BUILD=1
RUN --mount=type=cache,target=/app/node_modules/.vite \
    npm run build:docker

EXPOSE 8003

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "8003"]
