#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$SCRIPT_DIR/workdir"
OUTPUT_LOG="$SCRIPT_DIR/build.log"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./build-iso.sh"
  exit 1
fi

if ! command -v lb >/dev/null 2>&1; then
  apt-get update
  apt-get install -y live-build rsync
elif ! command -v rsync >/dev/null 2>&1; then
  apt-get update
  apt-get install -y rsync
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

rsync -a --delete "$SCRIPT_DIR/config/" "$BUILD_DIR/config/"

mkdir -p "$BUILD_DIR/config/includes.chroot/opt/linuxtv"
rsync -a --delete "$REPO_ROOT/linuxtvdesktop/" "$BUILD_DIR/config/includes.chroot/opt/linuxtv/linuxtvdesktop/"
if [ -d "$REPO_ROOT/linuxtvremote" ]; then
  rsync -a --delete --delete-excluded \
    --exclude '.git/' \
    --exclude 'node_modules/' \
    --exclude '.expo/' \
    --exclude '.gradle/' \
    --exclude 'android/.gradle/' \
    --exclude 'android/app/build/' \
    --exclude 'android/build/' \
    --exclude 'ios/' \
    --exclude 'dist/' \
    --exclude 'build/' \
    --exclude '.DS_Store' \
    --exclude '*.log' \
    --exclude '*.tmp' \
    --exclude 'record.json' \
    --exclude 'ecord.json' \
    "$REPO_ROOT/linuxtvremote/" "$BUILD_DIR/config/includes.chroot/opt/linuxtv/linuxtvremote/"
fi

cd "$BUILD_DIR"
lb clean --purge 2>/dev/null || true

lb config \
  --distribution trixie \
  --archive-areas "main contrib non-free non-free-firmware" \
  --debian-installer live \
  --debian-installer-gui false \
  --binary-images iso-hybrid \
  --iso-application "LinuxTV" \
  --iso-volume "LinuxTV" \
  --bootappend-live "boot=live components quiet splash" \
  --linux-flavours amd64 \
  --apt-recommends false

lb build 2>&1 | tee "$OUTPUT_LOG"

find "$BUILD_DIR" -maxdepth 1 -type f -name '*.iso' -exec cp -f {} "$SCRIPT_DIR/" \;
find "$BUILD_DIR" -maxdepth 1 -type f -name '*.packages' -exec cp -f {} "$SCRIPT_DIR/" \; 2>/dev/null || true

echo
echo "ISO built successfully!"
ls -lh "$SCRIPT_DIR"/*.iso
