#!/usr/bin/env bash
# Fetch the Tailwind CSS v4 standalone CLI binary into bin/ (no Node.js required).
# Pinned version + SHA256-verified. Re-running is a no-op when the binary is valid.
set -euo pipefail

TAILWIND_VERSION="v4.3.1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$ROOT/bin"
DEST="$BIN_DIR/tailwindcss"

# SHA256 of each supported platform asset for the pinned version.
SHA256_linux_x64="2526d063ba03b71f9a3ea7d5cee14f0aec147f117f222d5adc97b1d736d45999"

# Detect platform -> official release asset name + expected hash.
os="$(uname -s)"
arch="$(uname -m)"
case "$os-$arch" in
  Linux-x86_64) asset="tailwindcss-linux-x64"; expected="$SHA256_linux_x64" ;;
  *)
    echo "install_tailwind: unpinned platform '$os-$arch'." >&2
    echo "Add its SHA256 for $TAILWIND_VERSION to this script before building here." >&2
    exit 1 ;;
esac

verify() { echo "$expected  $DEST" | sha256sum --check --status; }

if [ -x "$DEST" ] && verify 2>/dev/null; then
  echo "install_tailwind: $DEST already present and verified ($TAILWIND_VERSION)."
  exit 0
fi

mkdir -p "$BIN_DIR"
url="https://github.com/tailwindlabs/tailwindcss/releases/download/$TAILWIND_VERSION/$asset"
echo "install_tailwind: downloading $asset ($TAILWIND_VERSION)..."
curl -fsSL -o "$DEST" "$url"

if ! verify; then
  echo "install_tailwind: SHA256 mismatch for $DEST -- refusing to use it." >&2
  rm -f "$DEST"
  exit 1
fi
chmod +x "$DEST"
echo "install_tailwind: installed and verified $DEST ($TAILWIND_VERSION)."
