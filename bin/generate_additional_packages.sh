#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${SCRIPT_DIR}/../Dockerfile"

# Extract version from Dockerfile ARG declaration
# Usage: extract_dockerfile_version "OSV_SCANNER" "/path/to/Dockerfile"
extract_dockerfile_version() {
  local name="$1"
  local dockerfile="$2"
  # Match ARG NAME_VERSION=vX.Y.Z format (version starts with v followed by digits and dots)
  grep -E "^ARG ${name}_VERSION=" "$dockerfile" | sed -n 's/.*=\(v[0-9.]*\).*/\1/p' | head -1
}

if [ ! -f "$DOCKERFILE" ]; then
  echo "ERROR: Dockerfile not found at $DOCKERFILE" >&2
  exit 1
fi

OSV_SCANNER_VERSION=$(extract_dockerfile_version "OSV_SCANNER" "$DOCKERFILE")
COSIGN_VERSION=$(extract_dockerfile_version "COSIGN" "$DOCKERFILE")

if [ -z "$OSV_SCANNER_VERSION" ]; then
  echo "ERROR: Could not extract OSV_SCANNER_VERSION from Dockerfile" >&2
  exit 1
fi

if [ -z "$COSIGN_VERSION" ]; then
  echo "ERROR: Could not extract COSIGN_VERSION from Dockerfile" >&2
  exit 1
fi

# Export for sourcing
export OSV_SCANNER_VERSION
export COSIGN_VERSION

# When executed directly (not sourced), output PURLs
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "pkg:golang/github.com/google/osv-scanner@${OSV_SCANNER_VERSION}"
  echo "pkg:golang/github.com/sigstore/cosign@${COSIGN_VERSION}"
fi
