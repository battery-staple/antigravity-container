#!/usr/bin/env bash
# ==============================================================================
# Google Antigravity Sandbox: Language Server Downloader
# ==============================================================================
# Downloads the Linux language_server binary from a URL into the canonical
# destination (~/.antigravity-sandbox/bin/language_server).
# ==============================================================================

set -euo pipefail

DEST_DIR="$HOME/.antigravity-sandbox/bin"
DEST_BIN="$DEST_DIR/language_server"

# Default verified Google Antigravity Desktop App / IDE Linux distributions
DEFAULT_URL_ARM64="https://storage.googleapis.com/antigravity-public/antigravity-hub/2.8.1-6512087774658560/linux-arm/Antigravity.tar.gz"
DEFAULT_URL_AMD64="https://storage.googleapis.com/antigravity-public/antigravity-hub/2.8.1-6512087774658560/linux-x64/Antigravity.tar.gz"

if [ "$(uname -m)" = "x86_64" ] || [ "$(uname -m)" = "amd64" ]; then
  DEFAULT_URL="$DEFAULT_URL_AMD64"
else
  DEFAULT_URL="$DEFAULT_URL_ARM64"
fi

# Optional environment variable override or default URL
DOWNLOAD_URL="${ANTIGRAVITY_LS_DOWNLOAD_URL:-$DEFAULT_URL}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url|-u)
      DOWNLOAD_URL="${2:-}"
      shift 2 || { echo "[Error] --url requires an argument" >&2; exit 1; }
      ;;
    -h|--help)
      echo "Usage: download-language-server.sh [--url <url>]"
      echo ""
      echo "Downloads the full Antigravity Desktop App distribution, extracts the Linux"
      echo "language_server binary, and installs it to ~/.antigravity-sandbox/bin/language_server."
      echo ""
      echo "Default URL ($(( [ "$(uname -m)" = "x86_64" ] || [ "$(uname -m)" = "amd64" ]) && echo "x64" || echo "arm64")):"
      echo "  $DEFAULT_URL"
      exit 0
      ;;
    *)
      if [[ "$1" =~ ^https?:// ]]; then
        DOWNLOAD_URL="$1"
        shift
      else
        echo "[Error] Unknown argument: $1" >&2
        echo "Usage: download-language-server.sh [--url <url>]" >&2
        exit 1
      fi
      ;;
  esac
done

TEMP_DIR="$(mktemp -d /tmp/antigravity_ls_XXXXXX)"
cleanup() {
  rm -rf "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$DEST_DIR"

echo "=========================================================="
echo "  Antigravity Sandbox - Language Server Downloader"
echo "  Source URL  : $DOWNLOAD_URL"
echo "  Destination : $DEST_BIN"
echo "=========================================================="

# 1. Download
DOWNLOAD_PAYLOAD="$TEMP_DIR/download_payload"
echo "⠋ Downloading package..."
if ! curl -fsSL -o "$DOWNLOAD_PAYLOAD" "$DOWNLOAD_URL"; then
  echo "[Error] Failed to download from: $DOWNLOAD_URL" >&2
  exit 1
fi

# 2. Extract or Copy
EXTRACT_DIR="$TEMP_DIR/extracted"
mkdir -p "$EXTRACT_DIR"

if tar -tf "$DOWNLOAD_PAYLOAD" >/dev/null 2>&1; then
  echo "⠋ Extracting language_server from archive..."
  tar -xf "$DOWNLOAD_PAYLOAD" -C "$EXTRACT_DIR" 2>/dev/null || true
elif ar t "$DOWNLOAD_PAYLOAD" >/dev/null 2>&1; then
  echo "⠋ Extracting language_server from Debian package..."
  (cd "$EXTRACT_DIR" && ar -x "$DOWNLOAD_PAYLOAD" 2>/dev/null || true)
  if [ -f "$EXTRACT_DIR/data.tar.xz" ]; then
    tar -xf "$EXTRACT_DIR/data.tar.xz" -C "$EXTRACT_DIR" 2>/dev/null || true
  elif [ -f "$EXTRACT_DIR/data.tar.gz" ]; then
    tar -xf "$EXTRACT_DIR/data.tar.gz" -C "$EXTRACT_DIR" 2>/dev/null || true
  fi
fi

# Find the language_server binary inside extracted contents
FOUND_BIN=""
for candidate in "language_server" "language_server_linux_arm" "language_server_linux_x64" "language_server_linux_arm64"; do
  FOUND_BIN="$(find "$EXTRACT_DIR" -type f -name "$candidate" 2>/dev/null | head -n 1 || true)"
  if [ -n "$FOUND_BIN" ]; then
    break
  fi
done

if [ -z "$FOUND_BIN" ]; then
  # Fallback: search for Linux ELF executable
  FOUND_BIN="$(find "$EXTRACT_DIR" -type f -exec grep -lI '^.ELF' {} + 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$FOUND_BIN" ]; then
  if [ -f "$DOWNLOAD_PAYLOAD" ] && [ -s "$DOWNLOAD_PAYLOAD" ]; then
    FOUND_BIN="$DOWNLOAD_PAYLOAD"
  else
    echo "[Error] Could not find Linux language_server binary inside downloaded archive." >&2
    exit 1
  fi
fi

cp "$FOUND_BIN" "$DEST_BIN"
echo "✓ Extracted language_server binary (discarded remaining app files)."

# 3. Validate ELF Header
echo "⠋ Validating binary..."
python3 -c "
import sys, os
path = '$DEST_BIN'
if not os.path.isfile(path) or os.path.getsize(path) < 64:
    print('ERROR: Downloaded file is empty or too small.', file=sys.stderr)
    sys.exit(1)
with open(path, 'rb') as f:
    header = f.read(64)
if header[:4] != b'\x7fELF':
    if header[:4] in [b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca']:
        print('ERROR: The downloaded file is a macOS Mach-O binary, NOT a Linux ELF binary.', file=sys.stderr)
    else:
        print('ERROR: The downloaded file is not a valid Linux ELF executable.', file=sys.stderr)
    sys.exit(1)
"

chmod +x "$DEST_BIN"

echo "=========================================================="
echo "✓ Successfully installed Linux language_server!"
echo "  Canonical Path: $DEST_BIN"
echo "  In-Container  : /home/developer/.antigravity-bin/language_server"
echo "=========================================================="

# 4. Restart running container if active
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^antigravity-sandbox$"; then
  echo ""
  echo "⠋ Restarting Antigravity Sandbox container..."
  "$SCRIPT_DIR/antigravity-sandbox" restart
fi
