#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

install -d -m 0755 /etc/apt/keyrings
curl -fsSLo /etc/apt/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
cat > /etc/apt/sources.list.d/brave-browser-release.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/brave-browser-archive-keyring.gpg arch=amd64] https://brave-browser-apt-release.s3.brave.com/ stable main
EOF

apt-get update
apt-get install -y brave-browser flatpak

flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y --system flathub com.stremio.Stremio
