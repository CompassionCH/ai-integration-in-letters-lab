#!/usr/bin/env bash
# Vendor the Alpine.js CSP build into static/vendor/ so it is self-hosted (no
# runtime CDN). The CSP build evaluates a restricted expression subset without
# eval()/new Function(), so it stays compatible with a strict Content-Security-
# Policy. Pinned version + SHA256-verified post-download. Re-running is a no-op
# when valid.
set -euo pipefail

ALPINE_VERSION="3.15.12"
ALPINE_SHA256="566167134bb2347110904e2ced6e816d2e8d837200c158f98b72372b3bb0b9a6"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT/static/vendor"
DEST="$VENDOR_DIR/alpine.csp.min.js"
URL="https://cdn.jsdelivr.net/npm/@alpinejs/csp@$ALPINE_VERSION/dist/cdn.min.js"

verify() { echo "$ALPINE_SHA256  $DEST" | sha256sum --check --status; }

if [ -f "$DEST" ] && verify 2>/dev/null; then
  echo "install_alpine: $DEST already present and verified (v$ALPINE_VERSION)."
  exit 0
fi

mkdir -p "$VENDOR_DIR"
echo "install_alpine: downloading Alpine.js CSP build v$ALPINE_VERSION..."
curl -fsSL -o "$DEST" "$URL"

if ! verify; then
  echo "install_alpine: SHA256 mismatch for $DEST -- refusing to use it." >&2
  rm -f "$DEST"
  exit 1
fi
echo "install_alpine: installed and verified $DEST (v$ALPINE_VERSION)."
