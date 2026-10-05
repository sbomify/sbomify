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

# Build the Go module path for a repo at a given version.
#
# From v2 onward a Go module path carries its major version as a suffix, so
# cosign v3.1.3 is "github.com/sigstore/cosign/v3" and osv-scanner v2.3.8 is
# "github.com/google/osv-scanner/v2" (https://go.dev/ref/mod#module-path).
#
# Dropping the suffix does not merely mislabel the package, it names the
# abandoned v1 module. Advisories carry a separate entry for that path with
# "introduced 0" and no fixed version, so it matches every version forever:
# emitting "github.com/sigstore/cosign@v3.1.3" makes scanners report all six
# historical cosign CVEs against a binary that fixed the last of them in 3.0.6.
#
# v0 and v1 take no suffix.
go_module_path() {
  local base="$1"
  local version="$2"
  local major="${version#v}"
  major="${major%%.*}"

  # Non-numeric major (unparseable version): fall back to the bare path rather
  # than emitting a nonsense "/vX" segment.
  case "$major" in
    '' | *[!0-9]*)
      echo "$base"
      return
      ;;
  esac

  if [ "$major" -ge 2 ]; then
    echo "${base}/v${major}"
  else
    echo "$base"
  fi
}

# Export for sourcing
export OSV_SCANNER_VERSION
export COSIGN_VERSION

# When executed directly (not sourced), output PURLs
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "pkg:golang/$(go_module_path "github.com/google/osv-scanner" "${OSV_SCANNER_VERSION}")@${OSV_SCANNER_VERSION}"
  echo "pkg:golang/$(go_module_path "github.com/sigstore/cosign" "${COSIGN_VERSION}")@${COSIGN_VERSION}"
fi
