# LinuxTV (Linux Media Launcher)

## Overview

LinuxTV is a fullscreen, remote-friendly launcher for home media setups (10-foot UI). It replaces the desktop/login UX with a focused launcher showing native apps + curated web services.

> This README is inside `linuxtvdesktop/` and documents the desktop launcher configuration, systemd service setup, and boot flow.


- Full-screen GUI via PySide6
- Config-driven web apps (`config.yaml`)
- Native app detection + hide-unavailable behavior
- Kiosk web app launch via chromium/firefox
- Auto-login workflow (no password prompts at Runtime)

---

## Files

- `launcher.py`: main PySide6 launcher app
- `config.yaml`: sample config with `native_apps` + `web_apps`
- `linuxtv.service`: example systemd unit
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

1. Load `~/ .config/linuxtv/config.yaml` or `./config.yaml` fallback.
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

1. Run `setup.sh` as the normal user you want LinuxTV to use at boot.
2. The installer uses that same user as the runtime/autologin account, installs to `~/LinuxTV`, and creates `~/.linuxtv_venv`.
3. Required Debian packages are installed automatically.
4. `~/.xinitrc` is written for that runtime user and starts `~/LinuxTV/linuxtvdesktop/launcher.py`.
5. Setup autologin tty1:
   - `sudo mkdir -p /etc/systemd/system/getty@tty1.service.d`
   - create `/etc/systemd/system/getty@tty1.service.d/override.conf`:
     ```ini
     [Service]
     ExecStart=
     ExecStart=-/sbin/agetty --autologin <your-user> --noclear %I $TERM
     ```
6. Disable desktop managers:
   - `sudo systemctl disable gdm3 lightdm sddm` (adjust according to installed DM)
7. Option A: Auto-start from `.bash_profile`/`.profile` (for tty1):
   ```bash
   if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
       startx
   fi
   ```
8. Option B: systemd service (if running in graphical target with X):
   - `sudo cp ~/LinuxTV/linuxtvdesktop/linuxtv.service /etc/systemd/system/linuxtv.service`
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable linuxtv.service`

Reboot.

---

## Optional enhancements

- Add `favorites` and `categories` sections in `config.yaml` (then extend `launcher.py`).
- Add remote control/gamepad mapping using `inputs` or `evdev`.
- Add app icon downloads and fallback icons.

---

## Quick run

`python3 ~/LinuxTV/linuxtvdesktop/launcher.py`

---

## Remote control (WebSocket)

- `launcher.py` starts a WebSocket server on `ws://0.0.0.0:8765`.
- Use the gear button in the top-right corner of LinuxTV to configure phone login and choose which app auto-opens after the idle timeout.
- Expected payload: `{ "action": "UP" }`, `DOWN`, `LEFT`, `RIGHT`, `SELECT`, `BACK`, `HOME`, `CLOSE_APP`, `SHUTDOWN`, `REBOOT`.
- Server sends acknowledgment JSON `{ "status": "ok", "action": "UP" }`.
- UI navigation is mapped in real time. When an app is already open, navigation commands are forwarded to that window and `CLOSE_APP` terminates it.

## Expo mobile app (`linuxtvremote`)

1. `cd linuxtvremote`
2. `npm install` (or `yarn`)
3. `npm run start`
4. In Expo Go, open the project.

Controls:
- Input TV IP/port (e.g. `192.168.1.100:8765`)
- Connect / Disconnect
- Sign in once with the desktop username/password and save it securely on the phone
- D-pad and OK / BACK / HOME
- Close App
- Shutdown and Reboot with confirmation prompts

---

## Notes

- `launcher.py` uses `pyyaml` if config is YAML and falls back to JSON.
- No root auth/prompt is required at runtime.
- If running in a secure environment, use a dedicated runtime account or restrict autologin appropriately.
