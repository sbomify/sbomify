#!/usr/bin/env bash
# Publish a committed CycloneDX VEX document to sbomify as a bom_type=vex artifact.
#
# The sbomify-action cannot set a bom_type, so VEX is uploaded by a direct API
# POST with ?bom_type=vex (per https://sbomify.com/faq/how-do-i-use-vex/),
# authenticated by the same GitHub OIDC trusted-publishing exchange the SBOM and
# CBOM jobs use.
#
# Required environment (set by the workflow job):
#   API_BASE_URL  - e.g. https://stage.sbomify.com
#   COMPONENT_ID  - target sbomify component
#   VEX_FILE      - path to the committed vex/*.cdx.json
#   VERSION       - release version stamped onto metadata.component.version
#   ACTIONS_ID_TOKEN_REQUEST_TOKEN / ACTIONS_ID_TOKEN_REQUEST_URL
#                 - provided automatically when permissions: id-token: write
set -euo pipefail

: "${API_BASE_URL:?}" "${COMPONENT_ID:?}" "${VEX_FILE:?}" "${VERSION:?}"
: "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:?}" "${ACTIONS_ID_TOKEN_REQUEST_URL:?}"

# The audience must match the backend's OIDC_GITHUB_AUDIENCE (default sbomify.com).
# Set explicitly in the workflow so it is easy to change per environment.
audience="${OIDC_AUDIENCE:-sbomify.com}"

# 1) GitHub Actions OIDC token for the sbomify audience.
gh_oidc="$(curl -fsS \
  -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=${audience}" | jq -r '.value')"
if [ -z "${gh_oidc}" ] || [ "${gh_oidc}" = "null" ]; then
  echo "Failed to obtain a GitHub OIDC token" >&2
  exit 1
fi

# 2) Exchange it for a short-lived sbomify token scoped to the component.
access_token="$(curl -fsS -X POST \
  "${API_BASE_URL}/api/v1/auth/oidc/github/exchange" \
  -H "Authorization: Bearer ${gh_oidc}" \
  -H 'Content-Type: application/json' \
  -d "{\"component_id\":\"${COMPONENT_ID}\"}" | jq -r '.access_token')"
if [ -z "${access_token}" ] || [ "${access_token}" = "null" ]; then
  echo "OIDC exchange did not return an access token" >&2
  exit 1
fi

# 3) Stamp the release version, then upload as bom_type=vex.
jq --arg v "${VERSION}" '.metadata.component.version = $v' "${VEX_FILE}" > /tmp/vex.json
code="$(curl -sS -o /tmp/vex-resp.json -w '%{http_code}' -X POST \
  "${API_BASE_URL}/api/v1/sboms/artifact/cyclonedx/${COMPONENT_ID}?bom_type=vex" \
  -H "Authorization: Bearer ${access_token}" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/vex.json)"

# 201 = uploaded; 409 = this version is already published (artifacts are immutable).
if [ "${code}" = "201" ] || [ "${code}" = "409" ]; then
  echo "VEX ${VEX_FILE} -> component ${COMPONENT_ID} (HTTP ${code})"
else
  echo "VEX upload failed (HTTP ${code}):" >&2
  cat /tmp/vex-resp.json >&2 || true
  exit 1
fi
