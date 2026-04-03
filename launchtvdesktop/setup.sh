#!/usr/bin/env bash
set -euo pipefail

echo "[LaunchTV] Installing dependencies (Debian/Ubuntu)..."
if ! command -v apt >/dev/null 2>&1; then
  echo "This setup script is Debian/Ubuntu-focused. Use distro packages manually for others."
  exit 1
fi

sudo apt update
sudo apt install -y python3 python3-pip python3-pyqt5 python3-pyqt5.qtwebengine chromium-browser xinit xserver-xorg

pip3 install --user pyyaml

echo "[LaunchTV] Ensuring config and app files are in place..."
mkdir -p ~/.config/launchtv
cp -n config.yaml ~/.config/launchtv/config.yaml

cat <<'EOF'

✅ LaunchTV setup prepped. Next steps:
1) Create a dedicated user: sudo adduser --disabled-password --gecos '' media
2) Add the user to video/audio groups if needed.
3) Copy LaunchTV files into /home/media/Dev/LaunchTV and set ownership:
   sudo chown -R media:media /home/media/Dev/LaunchTV
4) Add ~/.xinitrc to media user:
   exec /usr/bin/python3 /home/media/Dev/LaunchTV/launcher.py
5) Configure auto-login on tty1:
   sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
   sudo tee /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null <<'EOL'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin media --noclear %I $TERM
EOL
6) Disable display manager: sudo systemctl disable gdm3 lightdm sddm
7) Optional: Install service file /etc/systemd/system/launchtv.service and enable.
   sudo cp /home/media/Dev/LaunchTV/launchtv.service /etc/systemd/system/launchtv.service
   sudo systemctl daemon-reload
   sudo systemctl enable launchtv.service

Reboot to test.
EOF
