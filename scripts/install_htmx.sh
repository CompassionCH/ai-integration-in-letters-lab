#!/usr/bin/env bash
# Vendor the HTMX library into static/vendor/ so it is self-hosted (no runtime CDN).
# Pinned version + SHA256-verified post-download. Re-running is a no-op when valid.
set -euo pipefail

HTMX_VERSION="2.0.9"
HTMX_SHA256="57d9191515339922bd1356d7b2d80b1ee3b29f1b3a2c65a078bb8b2e8fd9ae5f"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT/static/vendor"
DEST="$VENDOR_DIR/htmx.min.js"
URL="https://cdn.jsdelivr.net/npm/htmx.org@$HTMX_VERSION/dist/htmx.min.js"

verify() { echo "$HTMX_SHA256  $DEST" | sha256sum --check --status; }

if [ -f "$DEST" ] && verify 2>/dev/null; then
  echo "install_htmx: $DEST already present and verified (v$HTMX_VERSION)."
  exit 0
fi

mkdir -p "$VENDOR_DIR"
echo "install_htmx: downloading htmx v$HTMX_VERSION..."
curl -fsSL -o "$DEST" "$URL"

if ! verify; then
  echo "install_htmx: SHA256 mismatch for $DEST -- refusing to use it." >&2
  rm -f "$DEST"
  exit 1
fi
echo "install_htmx: installed and verified $DEST (v$HTMX_VERSION)."
