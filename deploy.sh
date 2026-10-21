#!/usr/bin/env bash
# Deploys greenrouter-api to Azure Container Apps. Secret values are read from .env and never printed.
set -euo pipefail   # stop on the first error, an unset variable, or a failed pipe

RG=greenrouter-rg
ENV=greenrouter-env
APP=greenrouter-api
TAG=${1:-v1}        # usage: ./deploy.sh v2
ACR=$(az acr list -g "$RG" --query "[0].name" -o tsv)
val() { grep -E "^$1=" .env | cut -d= -f2- | tr -d '\r\n'; }

az containerapp create -n "$APP" -g "$RG" \
  --environment "$ENV" \
  --image "$ACR.azurecr.io/api:$TAG" \
  --registry-server "$ACR.azurecr.io" --registry-identity system \
  --target-port 8080 --ingress external \
  --cpu 1.0 --memory 2.0Gi \
  --min-replicas 0 --max-replicas 2 \
  --secrets tiger-dsn="$(val TIGER_DSN)" \
            westus-endpoint="$(val WESTUS_ENDPOINT)" westus-key="$(val WESTUS_KEY)" \
            ncus-endpoint="$(val NCUS_ENDPOINT)" ncus-key="$(val NCUS_KEY)" \
            demo-token="$(val DEMO_TOKEN)" \
  --env-vars TIGER_DSN=secretref:tiger-dsn \
             WESTUS_ENDPOINT=secretref:westus-endpoint WESTUS_KEY=secretref:westus-key \
             NCUS_ENDPOINT=secretref:ncus-endpoint NCUS_KEY=secretref:ncus-key \
             DEMO_TOKEN=secretref:demo-token \
             SMALL_DEPLOYMENT="$(val SMALL_DEPLOYMENT)" LARGE_DEPLOYMENT="$(val LARGE_DEPLOYMENT)" \
             MAX_LIVE_CALLS_PER_DAY="$(val MAX_LIVE_CALLS_PER_DAY)" \
             ALLOWED_ORIGINS=https://green-router-tau.vercel.app \
             TRUSTED_PROXY_HOPS=1 \
             GREENROUTER_ENV=production \
  --query properties.configuration.ingress.fqdn -o tsv