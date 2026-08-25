FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=
ARG VITE_USE_MOCK_API=true
ARG VITE_USE_PLAN_VERSION_API=true
ARG VITE_USE_WORKFLOW_API=true

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_USE_MOCK_API=$VITE_USE_MOCK_API \
    VITE_USE_PLAN_VERSION_API=$VITE_USE_PLAN_VERSION_API \
    VITE_USE_WORKFLOW_API=$VITE_USE_WORKFLOW_API

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV API_UPSTREAM=http://backend:8000

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
