#!/usr/bin/env bash
#
# Point the public hostnames at the in-cluster Caddy edge.
#
# *.localtest.me resolves to 127.0.0.1, which is right from the host and
# useless from inside a pod. Rewriting these names to the Caddy Service makes
# the Keycloak issuer URL resolve identically on both sides — without it, OIDC
# discovery hands the browser and the application pods different endpoints.
#
# Shared by bin/kind-up.sh and .github/workflows/helm.yml. It lives in one file
# because it did not used to: the workflow carried its own copy of the Corefile
# with the `health` and `forward` blocks collapsed onto single lines, which
# CoreDNS rejects ("Wrong argument count or unexpected line ending after '}'"),
# so its pods crash-looped and every CI run failed on the rollout timeout.
set -euo pipefail

APP_HOST="${APP_HOST:-sbomify.localtest.me}"
KEYCLOAK_HOST="${KEYCLOAK_HOST:-keycloak.localtest.me}"
CADDY_SVC="${CADDY_SVC:-sbomify-caddy.sbomify.svc.cluster.local}"

if kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' \
    | grep -q "rewrite name ${KEYCLOAK_HOST}"; then
  echo "CoreDNS rewrites already in place"
  exit 0
fi

echo "Adding CoreDNS rewrites for ${APP_HOST} and ${KEYCLOAK_HOST} -> ${CADDY_SVC}"

# Written out in full rather than patched in place: string-splicing a Corefile
# is fragile, and this is kind's stock config plus two rewrites. Note every
# block opens at end-of-line and closes on its own line — CoreDNS uses Caddy's
# parser and will not accept `health { lameduck 5s }` inline.
kubectl -n kube-system create configmap coredns --dry-run=client -o yaml \
  --from-literal=Corefile=".:53 {
    errors
    health {
       lameduck 5s
    }
    ready
    rewrite name ${APP_HOST} ${CADDY_SVC}
    rewrite name ${KEYCLOAK_HOST} ${CADDY_SVC}
    kubernetes cluster.local in-addr.arpa ip6.arpa {
       pods insecure
       fallthrough in-addr.arpa ip6.arpa
       ttl 30
    }
    prometheus :9153
    forward . /etc/resolv.conf {
       max_concurrent 1000
    }
    cache 30
    loop
    reload
    loadbalance
}
" | kubectl apply -f -

kubectl -n kube-system rollout restart deployment coredns
kubectl -n kube-system rollout status deployment coredns --timeout=180s
