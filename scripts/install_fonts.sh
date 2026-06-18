#!/usr/bin/env bash
# Fetch the self-hosted Inter web fonts (woff2, latin subset) into static/fonts/.
# Pinned version + SHA256-verified, same pattern as install_tailwind.sh / install_htmx.sh.
# Re-running is a no-op when all files are present and verified. The app loads these
# local files via @font-face in static/css/app.src.css -- no runtime web-font CDN.
set -euo pipefail

INTER_VERSION="5.2.8"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FONTS_DIR="$ROOT/static/fonts"
BASE_URL="https://cdn.jsdelivr.net/npm/@fontsource/inter@${INTER_VERSION}/files"

# weight -> SHA256 of inter-latin-<weight>-normal.woff2 for Fontsource v${INTER_VERSION}.
WEIGHTS=(300 400 500 600)
SHA_300="be0276550393a72b94d673505567dceba801511d5e1ca5a87793190dc5d5a6ca"
SHA_400="8909904ab6c872eb994093482a88a28eca2cd95912d7b6fecd72103b0dc07edc"
SHA_500="f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f"
SHA_600="f9a06e79cd3a2a20951c0f0e28f66dd0e6d3fda73911d640a2125c8fcb78f21a"

sha_for() { local v="SHA_$1"; echo "${!v}"; }
dest_for() { echo "$FONTS_DIR/inter-$1.woff2"; }
verify() { echo "$(sha_for "$1")  $(dest_for "$1")" | sha256sum --check --status; }

all_present_and_valid() {
  for w in "${WEIGHTS[@]}"; do
    [ -f "$(dest_for "$w")" ] && verify "$w" 2>/dev/null || return 1
  done
}

if all_present_and_valid; then
  echo "install_fonts: Inter ${INTER_VERSION} already present and verified."
  exit 0
fi

mkdir -p "$FONTS_DIR"
for w in "${WEIGHTS[@]}"; do
  dest="$(dest_for "$w")"
  url="$BASE_URL/inter-latin-${w}-normal.woff2"
  echo "install_fonts: downloading inter-${w}.woff2 (Inter ${INTER_VERSION})..."
  curl -fsSL -o "$dest" "$url"
  if ! verify "$w"; then
    echo "install_fonts: SHA256 mismatch for $dest -- refusing to use it." >&2
    rm -f "$dest"
    exit 1
  fi
done
echo "install_fonts: installed and verified Inter ${INTER_VERSION} (weights ${WEIGHTS[*]}) in $FONTS_DIR."
