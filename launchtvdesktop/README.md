# LaunchTV (Linux Media Launcher)

## Overview

LaunchTV is a fullscreen, remote-friendly launcher for home media setups (10-foot UI). It replaces the desktop/login UX with a focused launcher showing native apps + curated web services.

- Full-screen GUI via PySide6
- Config-driven web apps (`config.yaml`)
- Native app detection + hide-unavailable behavior
- Kiosk web app launch via chromium/firefox
- Auto-login workflow (no password prompts at Runtime)

---

## Files

- `launcher.py`: main PySide6 launcher app
- `config.yaml`: sample config with `native_apps` + `web_apps`
- `launchtv.service`: example systemd unit
- `setup.sh`: install dependencies + instructions message
- `README.md`: this documentation

---

## `config.yaml` schema

- `native_apps`: list of objects
  - `name`: display name
  - `cmd`: executable name
  - `icon`: optional icon path in project

- `web_apps`: list of objects
  - `name`: display name
  - `url`: URL to launch
  - `icon`: optional icon path

---

## Python app behavior

1. Load `~/ .config/launchtv/config.yaml` or `./config.yaml` fallback.
2. Detect installed native apps (via `which`).
3. Show available app tiles in fullscreen.
4. Keyboard navigation:
   - Arrow keys: move
   - Enter/Space: launch
   - Esc: close launcher
5. On app exit, return to launcher.

---

## Web app launch behavior

- Detects system browser in order: chromium*, chromium-browser, brave-browser, google-chrome, firefox
- Chromium-based launches in kiosk + app mode
- Firefox launches in kiosk

---

## Setup flow (recommended, Deb-based)

1. `sudo adduser --disabled-password --gecos '' media`
2. `sudo chown -R media:media /home/media/Dev/LaunchTV`
3. `sudo apt install -y python3 python3-pip python3-pyqt5 python3-pyqt5.qtwebengine chromium-browser xinit xserver-xorg`
4. `pip3 install --user pyyaml`
5. In user `media` home: `cat > /home/media/.xinitrc <<'EOF'` then `exec /usr/bin/python3 /home/media/Dev/LaunchTV/launchtvdesktop/launcher.py`.
6. Setup autologin tty1:
   - `sudo mkdir -p /etc/systemd/system/getty@tty1.service.d`
   - create `/etc/systemd/system/getty@tty1.service.d/override.conf`:
     ```ini
     [Service]
     ExecStart=
     ExecStart=-/sbin/agetty --autologin media --noclear %I $TERM
     ```
7. Disable desktop managers:
   - `sudo systemctl disable gdm3 lightdm sddm` (adjust according to installed DM)
8. Option A: Auto-start from `.bash_profile`/`.profile` (for tty1):
   ```bash
   if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
       startx
   fi
   ```
9. Option B: systemd service (if running in graphical target with X):
   - `sudo cp /home/media/Dev/LaunchTV/launchtv.service /etc/systemd/system/launchtv.service`
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable launchtv.service`

Reboot.

---

## Optional enhancements

- Add `favorites` and `categories` sections in `config.yaml` (then extend `launcher.py`).
- Add remote control/gamepad mapping using `inputs` or `evdev`.
- Add app icon downloads and fallback icons.

---

## Quick run

`python3 /home/media/Dev/LaunchTV/launchtvdesktop/launcher.py`

---

## Remote control (WebSocket)

- `launcher.py` starts a WebSocket server on `ws://0.0.0.0:8765`.
- Expected payload: `{ "action": "UP" }`, `DOWN`, `LEFT`, `RIGHT`, `SELECT`, `BACK`, `HOME`.
- Server sends acknowledgment JSON `{ "status": "ok", "action": "UP" }`.
- UI navigation is mapped in real time.

## Expo mobile app (`launchtvremote`)

1. `cd launchtvremote`
2. `npm install` (or `yarn`)
3. `npm run start`
4. In Expo Go, open the project.

Controls:
- Input TV IP/port (e.g. `192.168.1.100:8765`)
- Connect button
- D-pad and OK / BACK / HOME

---

## Notes

- `launcher.py` uses `pyyaml` if config is YAML and falls back to JSON.
- No root auth/prompt is required at runtime.
- If running in secure environment, ensure the `media` user has `PasswordAuthentication no` etc. for user safety.
