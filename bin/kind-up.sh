#!/usr/bin/env bash
#
# Stand up a local Kubernetes cluster (kind) and deploy sbomify onto it with
# the Helm chart in charts/sbomify.
#
# Usage:
#   ./bin/kind-up.sh              # create cluster + deploy
#   ./bin/kind-up.sh --no-deploy  # create the cluster only
#   ./bin/kind-up.sh --down       # tear the cluster down
#
# Requires: docker, kind, kubectl, helm.
#
# There is no ingress controller: the chart runs Caddy as the cluster edge,
# which is what lets workspace custom domains get certificates on demand.
#
# PostgreSQL, Redis, MinIO and Keycloak are NOT part of the chart. They are
# applied separately from deploy/local/dependencies.yaml, mirroring how you
# would point the chart at managed services in production.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-sbomify}"
RELEASE="${RELEASE:-sbomify}"
NAMESPACE="${NAMESPACE:-sbomify}"
APP_HOST="${APP_HOST:-sbomify.localtest.me}"
KEYCLOAK_HOST="${KEYCLOAK_HOST:-keycloak.localtest.me}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="${REPO_ROOT}/charts/sbomify"
LOCAL_DIR="${REPO_ROOT}/deploy/local"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

require() {
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || {
      echo "error: '$cmd' is required but not installed" >&2
      exit 1
    }
  done
}

teardown() {
  log "Deleting kind cluster '${CLUSTER_NAME}'"
  kind delete cluster --name "${CLUSTER_NAME}"
  exit 0
}

DEPLOY=1
for arg in "$@"; do
  case "$arg" in
    --down) teardown ;;
    --no-deploy) DEPLOY=0 ;;
    -h | --help)
      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "error: unknown argument '$arg'" >&2
      exit 1
      ;;
  esac
done

require docker kind kubectl helm

# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------
if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  log "kind cluster '${CLUSTER_NAME}' already exists — reusing it"
else
  log "Creating kind cluster '${CLUSTER_NAME}'"
  kind create cluster --config "${LOCAL_DIR}/kind-cluster.yaml" --wait 300s
fi

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

# ---------------------------------------------------------------------------
# In-cluster DNS for the public hostnames
# ---------------------------------------------------------------------------
log "Pointing ${APP_HOST} and ${KEYCLOAK_HOST} at the Caddy edge"
APP_HOST="${APP_HOST}" \
KEYCLOAK_HOST="${KEYCLOAK_HOST}" \
CADDY_SVC="${RELEASE}-caddy.${NAMESPACE}.svc.cluster.local" \
  "${LOCAL_DIR}/coredns-rewrite.sh"

if [ "${DEPLOY}" -eq 0 ]; then
  log "Cluster ready. Skipping deploy (--no-deploy)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Backing services
# ---------------------------------------------------------------------------
# The chart does not ship PostgreSQL, Redis, object storage or Keycloak — it
# expects you to provide them. On a laptop, "provide them" means this file.
kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

log "Provisioning local backing services (not part of the chart)"
kubectl -n "${NAMESPACE}" apply -f "${LOCAL_DIR}/dependencies.yaml"

# The migration hook runs before any ordinary resource, so PostgreSQL and Redis
# have to be serving before `helm install` starts.
log "Waiting for PostgreSQL, Redis and MinIO"
kubectl -n "${NAMESPACE}" rollout status statefulset/sbomify-dev-postgresql --timeout=300s
kubectl -n "${NAMESPACE}" rollout status statefulset/sbomify-dev-redis --timeout=300s
kubectl -n "${NAMESPACE}" rollout status statefulset/sbomify-dev-minio --timeout=300s

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
# No TLS secret to create: Caddy issues its own certificates from its internal
# CA (caddy.localCerts), including for on-demand custom domains.
log "Deploying the sbomify chart"
helm upgrade --install "${RELEASE}" "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --values "${CHART_DIR}/values-local.yaml" \
  --wait --timeout 15m

# Keycloak can finish provisioning while the app rolls; only the login flow
# needs it, so it does not gate the release.
log "Waiting for the Keycloak realm to be provisioned"
kubectl -n "${NAMESPACE}" wait --for=condition=complete \
  job/sbomify-dev-keycloak-bootstrap --timeout=600s || \
  echo "warning: keycloak bootstrap did not finish; login will not work yet"

log "Deployment complete"
kubectl -n "${NAMESPACE}" get pods

cat <<EOF

  sbomify   https://${APP_HOST}       (Caddy internal CA — your browser will warn)
  Keycloak  http://${KEYCLOAK_HOST}   (admin / admin)

  Dev logins: jdoe / foobar123, ssmith / foobar123

  Smoke test:  helm test ${RELEASE} -n ${NAMESPACE}
  Tear down:   ./bin/kind-up.sh --down

EOF
