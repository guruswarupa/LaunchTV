#!/usr/bin/env python3
import asyncio
import configparser
import hashlib
import importlib
import json
import logging
import os
import queue
import signal
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:
    yaml = None

try:
    import websockets
except ImportError:
    websockets = None

QT_BINDING = None


def _load_qt_binding():
    preferred = os.getenv("LINUXTV_QT_BINDING")
    if preferred:
        order = [preferred]
    elif sys.platform.startswith("linux"):
        order = ["PyQt5", "PySide6"]
    else:
        order = ["PySide6", "PyQt5"]

    for binding in order:
        try:
            if binding == "PyQt5":
                qt_core = importlib.import_module("PyQt5.QtCore")
                qt_gui = importlib.import_module("PyQt5.QtGui")
                qt_widgets = importlib.import_module("PyQt5.QtWidgets")
            elif binding == "PySide6":
                qt_core = importlib.import_module("PySide6.QtCore")
                qt_gui = importlib.import_module("PySide6.QtGui")
                qt_widgets = importlib.import_module("PySide6.QtWidgets")
            else:
                logging.warning("Unknown Qt binding requested: %s", binding)
                continue

            return (
                binding,
                qt_core.QEvent,
                qt_core.Qt,
                qt_core.QSize,
                qt_core.QTimer,
                qt_gui.QFont,
                qt_gui.QIcon,
                qt_gui.QKeyEvent,
                qt_gui.QPixmap,
                qt_widgets.QApplication,
                qt_widgets.QComboBox,
                qt_widgets.QDialog,
                qt_widgets.QGridLayout,
                qt_widgets.QHBoxLayout,
                qt_widgets.QLabel,
                qt_widgets.QLineEdit,
                qt_widgets.QMainWindow,
                qt_widgets.QMessageBox,
                qt_widgets.QPushButton,
                qt_widgets.QSizePolicy,
                qt_widgets.QScrollArea,
                qt_widgets.QToolButton,
                qt_widgets.QVBoxLayout,
                qt_widgets.QWidget,
            )
        except ImportError:
            continue

    raise ImportError("No supported Qt binding found. Install PyQt5 or PySide6.")


(
    QT_BINDING,
    QEvent,
    Qt,
    QSize,
    QTimer,
    QFont,
    QIcon,
    QKeyEvent,
    QPixmap,
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
) = _load_qt_binding()

APP_NAME = "LinuxTV"
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
REMOTE_POINTER_SPEED_MULTIPLIER = 2.5
REMOTE_POINTER_TARGET_CACHE_SECONDS = 1.0

DEFAULT_CONFIG = {
    "native_apps": [
        {"name": "Kodi", "cmd": "kodi", "icon": "icons/kodi.png"},
        {"name": "Stremio", "cmd": "stremio", "icon": "icons/stremio.png"},
        {"name": "VLC", "cmd": "vlc", "icon": "icons/vlc.png"},
    ],
    "web_apps": [
        {"name": "YouTube", "url": "https://www.youtube.com", "icon": "icons/youtube.png"},
    ],
    "auth": {
        "username": "",
        "password_hash": "",
    },
    "auto_launch": {
        "app_kind": "",
        "app_target": "",
        "delay_seconds": 10,
    },
}

LINE_COUNT = 4
COLUMN_COUNT = 3
AUTO_LAUNCH_IDLE_MS = 10_000


def resource_path(relpath: str) -> Path:
    base = Path(__file__).parent
    return (base / relpath).expanduser().resolve()


def cache_dir() -> Path:
    return Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "linuxtv" / "icons"


def desktop_file_locations():
    return [
        Path.home() / ".local/share/applications",
        Path.home() / ".local/share/flatpak/exports/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
    ]


def icon_search_locations():
    return [
        Path.home() / ".local/share/icons",
        Path.home() / ".icons",
        Path.home() / ".local/share/flatpak/exports/share/icons",
        Path("/usr/local/share/icons"),
        Path("/usr/share/icons/hicolor"),
        Path("/var/lib/flatpak/exports/share/icons/hicolor"),
        Path("/usr/share/pixmaps"),
    ]


def normalized_icon_path(source_path: str, cache_key: str, size: int = 96):
    if not source_path:
        return ""

    icon_source = Path(source_path).expanduser()
    if not icon_source.exists():
        return ""

    normalized_dir = cache_dir() / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    target_path = normalized_dir / f"{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()}.png"
    if target_path.exists():
        return str(target_path)

    pixmap = QPixmap(str(icon_source))
    if pixmap.isNull():
        icon = QIcon(str(icon_source))
        pixmap = icon.pixmap(size, size)
    if pixmap.isNull():
        return str(icon_source)

    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    scaled.save(str(target_path), "PNG")
    return str(target_path)


def resolve_icon_name(icon_name: str):
    if not icon_name:
        return ""

    icon_path = Path(icon_name).expanduser()
    if icon_path.exists():
        return str(icon_path)

    for suffix in ("png", "svg", "xpm"):
        for base_dir in icon_search_locations():
            if not base_dir.exists():
                continue
            direct_match = base_dir / f"{icon_name}.{suffix}"
            if direct_match.exists():
                return str(direct_match)
            for candidate in base_dir.glob(f"**/{icon_name}.{suffix}"):
                if candidate.exists():
                    return str(candidate)
    return ""


def desktop_entry_for_command(command_text: str):
    parts = split_command(command_text)
    if not parts:
        return None

    if len(parts) >= 3 and parts[0] == "flatpak" and parts[1] == "run":
        flatpak_app_id = parts[2]
        for directory in desktop_file_locations():
            direct_match = directory / f"{flatpak_app_id}.desktop"
            if direct_match.exists():
                parser = configparser.ConfigParser(interpolation=None)
                try:
                    parser.read(direct_match, encoding="utf-8")
                except Exception:
                    continue
                if "Desktop Entry" in parser:
                    return parser["Desktop Entry"]

    executable = Path(parts[0]).name
    for directory in desktop_file_locations():
        if not directory.exists():
            continue
        for desktop_file in directory.glob("*.desktop"):
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(desktop_file, encoding="utf-8")
            except Exception:
                continue
            if "Desktop Entry" not in parser:
                continue
            entry = parser["Desktop Entry"]
            exec_line = entry.get("Exec", "")
            if not exec_line:
                continue
            exec_parts = split_command(exec_line.replace("%u", "").replace("%U", "").replace("%f", "").replace("%F", ""))
            if not exec_parts:
                continue
            entry_exec = Path(exec_parts[0]).name
            if executable == entry_exec:
                return entry
            if len(parts) >= 3 and parts[0] == "flatpak" and parts[1] == "run" and parts[2] in exec_parts:
                return entry
    return None


def resolve_native_icon(app):
    configured_icon = app.get("icon", "")
    if configured_icon:
        path = resource_path(configured_icon)
        if path.exists():
            return normalized_icon_path(str(path), f"native-config:{configured_icon}")
        resolved = resolve_icon_name(configured_icon)
        if resolved:
            return normalized_icon_path(resolved, f"native-theme:{configured_icon}")

    entry = desktop_entry_for_command(app.get("cmd", ""))
    if entry:
        resolved = resolve_icon_name(entry.get("Icon", ""))
        if resolved:
            return normalized_icon_path(resolved, f"native-entry:{app.get('cmd', '')}:{entry.get('Icon', '')}")
    return ""


def fetch_web_icon(app):
    configured_icon = app.get("icon", "")
    if configured_icon:
        path = resource_path(configured_icon)
        if path.exists():
            return normalized_icon_path(str(path), f"web-config:{configured_icon}")
        resolved = resolve_icon_name(configured_icon)
        if resolved:
            return normalized_icon_path(resolved, f"web-theme:{configured_icon}")

    url = app.get("url", "")
    if not url:
        return ""

    parsed = urlparse(url if "://" in url else f"https://{url}")
    if not parsed.netloc:
        return ""

    icon_dir = cache_dir() / "web"
    icon_dir.mkdir(parents=True, exist_ok=True)
    cache_file = icon_dir / f"{hashlib.sha1(parsed.netloc.encode('utf-8')).hexdigest()}.ico"
    if cache_file.exists():
        return normalized_icon_path(str(cache_file), f"web-cache:{parsed.netloc}")

    favicon_url = f"{parsed.scheme or 'https'}://{parsed.netloc}/favicon.ico"
    try:
        request = Request(favicon_url, headers={"User-Agent": "LinuxTV/1.0"})
        with urlopen(request, timeout=3) as response:
            data = response.read()
        if data:
            cache_file.write_bytes(data)
            return normalized_icon_path(str(cache_file), f"web-cache:{parsed.netloc}")
    except Exception as exc:
        logging.info("Could not fetch favicon for %s: %s", parsed.netloc, exc)
    return ""


def load_config(path: Path):
    if not path.exists():
        logging.warning("Config not found at %s, using built-in defaults", path)
        return normalize_config(DEFAULT_CONFIG)

    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yml", ".yaml"):
            if yaml is None:
                raise RuntimeError("pyyaml is required to load YAML config")
            return normalize_config(yaml.safe_load(text))
        if path.suffix.lower() == ".json":
            return normalize_config(json.loads(text))

        # fallback by heuristic
        if text.strip().startswith("{"):
            return normalize_config(json.loads(text))
        if yaml is None:
            raise RuntimeError("pyyaml is required to load YAML config")
        return normalize_config(yaml.safe_load(text))
    except Exception as e:
        logging.exception("Failed to load config '%s': %s", path, e)
        return normalize_config(DEFAULT_CONFIG)


def normalize_config(config):
    normalized = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        normalized.update(config)

    native_apps = normalized.get("native_apps")
    web_apps = normalized.get("web_apps")
    auth = normalized.get("auth")
    auto_launch = normalized.get("auto_launch")
    normalized["native_apps"] = native_apps if isinstance(native_apps, list) else list(DEFAULT_CONFIG["native_apps"])
    normalized["web_apps"] = web_apps if isinstance(web_apps, list) else list(DEFAULT_CONFIG["web_apps"])
    normalized["auth"] = auth if isinstance(auth, dict) else dict(DEFAULT_CONFIG["auth"])
    normalized["auto_launch"] = auto_launch if isinstance(auto_launch, dict) else dict(DEFAULT_CONFIG["auto_launch"])
    return normalized


def hash_remote_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def remote_auth_enabled(config) -> bool:
    auth = config.get("auth", {})
    return bool(auth.get("username", "").strip() and auth.get("password_hash", "").strip())


def verify_remote_credentials(config, username: str, password: str) -> bool:
    auth = config.get("auth", {})
    expected_user = auth.get("username", "").strip()
    expected_hash = auth.get("password_hash", "").strip()
    if not expected_user or not expected_hash:
        return True
    return username.strip() == expected_user and hash_remote_password(password) == expected_hash


def save_config(path: Path, config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".yml", ".yaml"):
        if yaml is None:
            raise RuntimeError("pyyaml is required to save YAML config")
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=False), encoding="utf-8")
    elif path.suffix.lower() == ".json":
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    elif yaml is not None:
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_config_path() -> Path:
    config_path = Path(os.getenv("LINUXTV_CONFIG", "~/.config/linuxtv/config.yaml")).expanduser()
    bundled_path = Path(__file__).parent / "config.yaml"

    if config_path.exists():
        return config_path

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if bundled_path.exists():
        try:
            config_path.write_text(bundled_path.read_text(encoding="utf-8"), encoding="utf-8")
            logging.info("Seeded LinuxTV config at %s from %s", config_path, bundled_path)
        except Exception:
            logging.exception("Failed to seed LinuxTV config at %s", config_path)

    return config_path


def find_browser():
    candidates = ["brave-browser", "chromium", "chromium-browser", "google-chrome", "firefox"]
    for exe in candidates:
        if shutil.which(exe):
            return exe
    return None


def is_installed(cmd_or_path: str) -> bool:
    parts = split_command(cmd_or_path)
    if not parts:
        return False
    executable = parts[0]
    if Path(executable).is_absolute() and Path(executable).exists():
        return True
    return shutil.which(executable) is not None


def split_command(command_text: str):
    try:
        return shlex.split(command_text)
    except ValueError:
        logging.warning("Failed to parse command: %s", command_text)
        return []


def run_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.stdout
    except Exception as exc:
        logging.warning("Command failed %s: %s", command, exc)
        return ""


def switch_audio_to_hdmi():
    pactl = shutil.which("pactl")
    if not pactl:
        return False

    sinks_output = run_command([pactl, "list", "short", "sinks"])
    hdmi_sink = None
    for line in sinks_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "hdmi" in parts[1].lower():
            hdmi_sink = parts[1]
            break

    if not hdmi_sink:
        logging.info("No HDMI sink found; leaving audio output unchanged")
        return False

    logging.info("Switching audio to HDMI sink %s", hdmi_sink)
    subprocess.run([pactl, "set-default-sink", hdmi_sink], check=False)

    sink_inputs = run_command([pactl, "list", "short", "sink-inputs"])
    for line in sink_inputs.splitlines():
        parts = line.split()
        if parts:
            subprocess.run([pactl, "move-sink-input", parts[0], hdmi_sink], check=False)

    return True


def maintain_hdmi_audio(stop_event: threading.Event, duration_seconds: int = 20):
    deadline = time.monotonic() + duration_seconds
    while not stop_event.is_set() and time.monotonic() < deadline:
        switch_audio_to_hdmi()
        stop_event.wait(2)


def process_tree_pids(root_pid: int):
    output = run_command(["ps", "-eo", "pid=,ppid="])
    children_by_parent = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        children_by_parent.setdefault(ppid, []).append(pid)

    seen = set()
    pending = [root_pid]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(children_by_parent.get(current, []))
    return seen


def find_window_ids_for_pid(pid: int):
    wmctrl = shutil.which("wmctrl")
    if not wmctrl:
        return []

    tracked_pids = process_tree_pids(pid)
    output = run_command([wmctrl, "-lp"])
    window_ids = []
    for line in output.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 3:
            continue
        try:
            line_pid = int(parts[2])
        except ValueError:
            continue
        if line_pid in tracked_pids:
            window_ids.append(parts[0])
    return window_ids


def native_app_profile(command):
    if not command:
        return ""

    executable = Path(command[0]).name.lower()
    if executable == "flatpak" and len(command) >= 3 and command[1] == "run":
        app_id = command[2].lower()
        if "stremio" in app_id:
            return "stremio"
        if "vlc" in app_id:
            return "vlc"
        return app_id

    if "stremio" in executable:
        return "stremio"
    if executable == "vlc":
        return "vlc"
    return executable


def enforce_native_fullscreen(command, pid: int, geometry, stop_event: threading.Event, attempts: int = 8):
    if not command:
        return

    app_profile = native_app_profile(command)
    preferred_f11 = app_profile in {"stremio", "vlc"}
    wmctrl = shutil.which("wmctrl")
    xdotool = shutil.which("xdotool")
    target_width = geometry.width() + (2 if app_profile == "stremio" else 0)
    target_height = geometry.height() + (2 if app_profile == "stremio" else 0)
    f11_applied_windows = set()

    for _ in range(attempts):
        if stop_event.wait(1.2):
            return

        window_ids = find_window_ids_for_pid(pid)
        if not window_ids:
            continue

        for window_id in window_ids:
            if wmctrl:
                subprocess.run(
                    [
                        wmctrl,
                        "-i",
                        "-r",
                        window_id,
                        "-e",
                        f"0,{geometry.x()},{geometry.y()},{target_width},{target_height}",
                    ],
                    check=False,
                )
                subprocess.run([wmctrl, "-i", "-a", window_id], check=False)
                subprocess.run([wmctrl, "-i", "-r", window_id, "-b", "add,maximized_vert,maximized_horz"], check=False)
                subprocess.run([wmctrl, "-i", "-r", window_id, "-b", "remove,maximized_vert,maximized_horz"], check=False)
                subprocess.run([wmctrl, "-i", "-r", window_id, "-b", "add,fullscreen"], check=False)

            if xdotool:
                subprocess.run([xdotool, "windowmove", window_id, str(geometry.x()), str(geometry.y())], check=False)
                subprocess.run([xdotool, "windowsize", window_id, str(target_width), str(target_height)], check=False)

            if preferred_f11 and xdotool and window_id not in f11_applied_windows:
                subprocess.run([xdotool, "windowactivate", "--sync", window_id], check=False)
                subprocess.run([xdotool, "key", "--window", window_id, "F11"], check=False)
                f11_applied_windows.add(window_id)


def request_system_power_action(action: str):
    command_map = {
        "SHUTDOWN": ["systemctl", "poweroff"],
        "REBOOT": ["systemctl", "reboot"],
    }
    command = command_map.get(action.upper())
    if not command:
        logging.warning("Unknown system power action requested: %s", action)
        return False

    try:
        subprocess.Popen(command)
        logging.info("Triggered system power action: %s", action)
        return True
    except Exception:
        logging.exception("Failed to trigger system power action: %s", action)
        return False


class InputDeviceGrabber(threading.Thread):
    """Captures input events from remote control devices system-wide using evdev."""
    
    def __init__(self, launcher_window):
        super().__init__(daemon=True)
        self.launcher_window = launcher_window
        self.running = False
        self.devices = []
        self._stop_event = threading.Event()
        
    def start_grabbing(self):
        """Start capturing input events from remote control devices."""
        try:
            import evdev
        except ImportError:
            logging.warning("evdev not installed; global input grabbing disabled")
            return False
            
        self.running = True
        self.devices = []
        
        # Find all input devices
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
                caps = device.capabilities()
                
                # Look for devices that are likely remote controls
                # Remote controls typically have navigation keys but not full keyboard
                if evdev.ecodes.EV_KEY in caps:
                    key_codes = caps[evdev.ecodes.EV_KEY]
                    
                    # Check if this looks like a remote control
                    # Remote controls usually have directional keys, OK/Enter, back, etc.
                    has_directional = any(code in key_codes for code in [
                        evdev.ecodes.KEY_UP, evdev.ecodes.KEY_DOWN,
                        evdev.ecodes.KEY_LEFT, evdev.ecodes.KEY_RIGHT
                    ])
                    has_enter = evdev.ecodes.KEY_ENTER in key_codes or evdev.ecodes.KEY_KPENTER in key_codes
                    
                    # Check if it's NOT a full keyboard (doesn't have letter keys)
                    has_letters = any(code in key_codes for code in [
                        evdev.ecodes.KEY_A, evdev.ecodes.KEY_B, evdev.ecodes.KEY_C,
                        evdev.ecodes.KEY_Q, evdev.ecodes.KEY_W, evdev.ecodes.KEY_E
                    ])
                    
                    # Grab if it looks like a remote (has directional + enter, but not full keyboard)
                    if has_directional and (has_enter or len(key_codes) < 50) and not has_letters:
                        try:
                            device.grab()  # Grab exclusive access
                            self.devices.append(device)
                            logging.info("Grabbed remote control device: %s (%s)", device.name, path)
                        except Exception as e:
                            logging.warning("Failed to grab device %s: %s", path, e)
                    elif has_directional and has_letters:
                        # It's a keyboard - don't grab it exclusively
                        logging.debug("Skipping keyboard device: %s (%s)", device.name, path)
                        
            except Exception as e:
                logging.warning("Failed to check device %s: %s", path, e)
                
        if not self.devices:
            logging.info("No remote control devices found to grab (this is OK if using keyboard)")
            return False
            
        self.start()
        return True
        
    def stop_grabbing(self):
        """Stop capturing input events."""
        self._stop_event.set()
        self.running = False
        for device in self.devices:
            try:
                device.ungrab()
            except Exception:
                pass
        self.devices.clear()
        
    def run(self):
        """Main loop to read and process input events."""
        try:
            import evdev
            from select import select
        except ImportError:
            return
            
        while self.running and not self._stop_event.is_set():
            try:
                # Wait for events from any device
                readable, _, _ = select(self.devices, [], [], 0.5)
                for device in readable:
                    if self._stop_event.is_set():
                        break
                    try:
                        for event in device.read():
                            if event.type == evdev.ecodes.EV_KEY:
                                self._handle_key_event(event)
                    except Exception as e:
                        logging.debug("Error reading from device: %s", e)
            except Exception as e:
                logging.debug("Error in input grabber loop: %s", e)
                
    def _handle_key_event(self, event):
        """Handle a key event and forward to launcher."""
        try:
            import evdev
            from evdev import ecodes
        except ImportError:
            return
            
        # Only process key press events (not release)
        if event.value != 1:  # 1 = press, 0 = release, 2 = repeat
            return
            
        key_code = event.code
        key_name = ecodes.KEY[key_code] if key_code in ecodes.KEY else None
        
        if not key_name:
            return
            
        # Map common remote control keys to actions
        action_map = {
            'KEY_UP': 'UP',
            'KEY_DOWN': 'DOWN',
            'KEY_LEFT': 'LEFT',
            'KEY_RIGHT': 'RIGHT',
            'KEY_ENTER': 'SELECT',
            'KEY_KPENTER': 'SELECT',
            'KEY_SPACE': 'SELECT',
            'KEY_BACKSPACE': 'BACK',
            'KEY_ESC': 'BACK',
            'KEY_HOME': 'HOME',
            'KEY_MENU': 'MENU',
            'KEY_INFO': 'INFO',
            'KEY_PLAYPAUSE': 'PLAY_PAUSE',
            'KEY_PLAY': 'PLAY_PAUSE',
            'KEY_PAUSE': 'PLAY_PAUSE',
            'KEY_TAB': 'TAB',
        }
        
        action = action_map.get(key_name)
        if action:
            logging.debug("Remote key pressed: %s -> %s", key_name, action)
            # Queue the action for processing by the main thread
            self.launcher_window.queue_remote_action(action)


class WebSocketControlServer(threading.Thread):
    def __init__(self, window, host="0.0.0.0", port=8765):
        super().__init__(daemon=True)
        self.window = window
        self.host = host
        self.port = port
        self.loop = None
        self.server = None
        self._stop_event = threading.Event()

    async def handler(self, websocket, path=None):
        logging.info("WebSocket connection from %s", websocket.remote_address)
        authenticated = not remote_auth_enabled(self.window.config)
        try:
            async for message in websocket:
                logging.info("Received remote action: %s", message)
                try:
                    payload = json.loads(message)
                    message_type = str(payload.get("type", "")).lower()
                except Exception:
                    payload = {}
                    message_type = ""

                if message_type == "auth":
                    username = str(payload.get("username", ""))
                    password = str(payload.get("password", ""))
                    if verify_remote_credentials(self.window.config, username, password):
                        authenticated = True
                        await websocket.send(json.dumps({"status": "auth_ok"}))
                    else:
                        await websocket.send(json.dumps({"status": "auth_error", "error": "invalid credentials"}))
                    continue

                if not authenticated:
                    await websocket.send(json.dumps({"status": "auth_required"}))
                    continue

                if message_type == "text":
                    text = str(payload.get("text", ""))
                    if text:
                        self.window.queue_remote_event({"type": "text", "text": text})
                        await websocket.send(json.dumps({"status": "ok", "type": "text"}))
                    else:
                        await websocket.send(json.dumps({"status": "error", "error": "invalid text"}))
                    continue

                if message_type == "key":
                    key = str(payload.get("key", "")).upper()
                    if key:
                        self.window.queue_remote_event({"type": "key", "key": key})
                        await websocket.send(json.dumps({"status": "ok", "type": "key", "key": key}))
                    else:
                        await websocket.send(json.dumps({"status": "error", "error": "invalid key"}))
                    continue

                if message_type == "pointer":
                    event_type = str(payload.get("event", "")).lower()
                    if event_type == "move":
                        try:
                            dx = int(round(float(payload.get("dx", 0))))
                            dy = int(round(float(payload.get("dy", 0))))
                        except (TypeError, ValueError):
                            dx = 0
                            dy = 0

                        if dx or dy:
                            self.window.queue_remote_event(
                                {"type": "pointer", "event": "move", "dx": dx, "dy": dy}
                            )
                            await websocket.send(
                                json.dumps({"status": "ok", "type": "pointer", "event": "move"})
                            )
                        else:
                            await websocket.send(json.dumps({"status": "error", "error": "invalid move"}))
                    elif event_type in ("tap", "click", "right_click"):
                        self.window.queue_remote_event({"type": "pointer", "event": event_type})
                        await websocket.send(
                            json.dumps({"status": "ok", "type": "pointer", "event": event_type})
                        )
                    else:
                        await websocket.send(json.dumps({"status": "error", "error": "invalid pointer event"}))
                    continue

                action = str(payload.get("action", "")).upper()
                if action:
                    self.window.queue_remote_action(action)
                    await websocket.send(json.dumps({"status": "ok", "action": action}))
                else:
                    await websocket.send(json.dumps({"status": "error", "error": "invalid action"}))
        except Exception as exc:
            logging.warning("WebSocket client disconnected: %s", exc)

    async def _run_server(self):
        if websockets is None:
            logging.error("websockets library not installed; remote control disabled")
            return
        self.server = await websockets.serve(self.handler, self.host, self.port)
        logging.info("WebSocket remote server started on ws://%s:%s", self.host, self.port)
        try:
            await self.server.wait_closed()
        except asyncio.CancelledError:
            pass

    def run(self):
        if websockets is None:
            return
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_server())
            self.loop.run_forever()
        finally:
            self.loop.close()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._stop_event.set()


class TileButton(QPushButton):
    def __init__(self, name: str, icon_path: str, tooltip: str = "", variant: str = "default", subtitle: str = ""):
        button_text = name if not subtitle else f"{name}\n{subtitle}"
        super().__init__(button_text)
        self.variant = variant
        self.title = name
        self.subtitle = subtitle
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumSize(QSize(340, 172))
        self.setMaximumHeight(186)
        self.setFont(QFont("Sans Serif", 18, QFont.Bold))
        if icon_path:
            path = resource_path(icon_path)
            if path.exists():
                self.setIcon(QIcon(str(path)))
                self.setIconSize(QSize(80, 80))
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("tileVariant", variant)
        self.setProperty("hasSubtitle", "true" if subtitle else "false")
        self.setStyleSheet("")


class AppCard(QWidget):
    def __init__(self, tile_button: TileButton, edit_callback=None, delete_callback=None, show_actions: bool = True):
        super().__init__()
        self.setObjectName("appCardShell")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumSize(tile_button.minimumSize())
        self.setFixedHeight(tile_button.maximumHeight())

        self.tile_button = tile_button
        self.tile_button.setParent(self)
        self.tile_button.setGeometry(0, 0, self.width(), self.height())

        self.edit_button = None
        self.delete_button = None
        if show_actions:
            self.edit_button = QToolButton(self)
            self.edit_button.setObjectName("editButton")
            self.edit_button.setText("⚙")
            self.edit_button.setToolTip("Edit this app")
            self.edit_button.clicked.connect(edit_callback)
            self.edit_button.setCursor(Qt.PointingHandCursor)
            self.edit_button.setFocusPolicy(Qt.NoFocus)
            self.edit_button.setFixedSize(44, 44)

            self.delete_button = QToolButton(self)
            self.delete_button.setObjectName("deleteButton")
            self.delete_button.setText("✕")
            self.delete_button.setToolTip("Delete this app")
            self.delete_button.clicked.connect(delete_callback)
            self.delete_button.setCursor(Qt.PointingHandCursor)
            self.delete_button.setFocusPolicy(Qt.NoFocus)
            self.delete_button.setFixedSize(44, 44)

    def sizeHint(self):
        return self.tile_button.sizeHint()

    def minimumSizeHint(self):
        return self.tile_button.minimumSizeHint()

    def resizeEvent(self, event):
        self.tile_button.setGeometry(0, 0, self.width(), self.height())
        if self.edit_button is not None:
            self.edit_button.move(self.width() - self.edit_button.width() - 14, 14)
        if self.delete_button is not None:
            self.delete_button.move(self.width() - self.delete_button.width() - 14, 64)
        super().resizeEvent(event)


class AddItemDialog(QDialog):
    def __init__(self, parent=None, title_text="Add To Apps", type_text="Application", name_text="", value_text="", allow_type_change=True):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", 24, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Create a launcher for an installed app command or a website.")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Sans Serif", 14))
        layout.addWidget(subtitle)

        type_label = QLabel("Type")
        type_label.setObjectName("dialogFieldLabel")
        layout.addWidget(type_label)

        self.type_select = QComboBox()
        self.type_select.addItems(["Application", "Website"])
        layout.addWidget(self.type_select)

        name_label = QLabel("Name")
        name_label.setObjectName("dialogFieldLabel")
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Spotify, YouTube, Kodi...")
        layout.addWidget(self.name_input)

        self.value_label = QLabel("Launch command")
        self.value_label.setObjectName("dialogFieldLabel")
        layout.addWidget(self.value_label)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("flatpak run com.spotify.Client")
        layout.addWidget(self.value_input)

        self.helper_label = QLabel("Tip: Flatpak apps work too, for example `flatpak run com.spotify.Client`.")
        self.helper_label.setObjectName("dialogHelper")
        self.helper_label.setWordWrap(True)
        layout.addWidget(self.helper_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.setProperty("tileVariant", "dialogSecondary")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        save_button = QPushButton("Save")
        save_button.setProperty("tileVariant", "accent")
        save_button.clicked.connect(self.accept)
        button_row.addWidget(save_button)

        layout.addLayout(button_row)
        self.type_select.currentTextChanged.connect(self.update_mode)
        self.type_select.setCurrentText(type_text)
        self.type_select.setEnabled(allow_type_change)
        self.name_input.setText(name_text)
        self.value_input.setText(value_text)
        self.update_mode(self.type_select.currentText())

        self.setStyleSheet(
            """
            QDialog {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 20px;
            }
            QLabel#dialogTitle {
                color: #f0f6fc;
            }
            QLabel#dialogSubtitle {
                color: #8b949e;
            }
            QLabel#dialogFieldLabel {
                color: #c9d1d9;
                font-weight: 600;
                padding-top: 6px;
            }
            QLabel#dialogHelper {
                color: #8b949e;
                padding-top: 4px;
            }
            QLineEdit, QComboBox {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 12px 16px;
                min-height: 24px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #58a6ff;
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QPushButton[tileVariant="dialogSecondary"] {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="dialogSecondary"]:hover {
                background-color: #30363d;
                border: 1px solid #58a6ff;
            }
            QPushButton[tileVariant="dialogSecondary"]:focus {
                border: 2px solid #58a6ff;
            }
            QPushButton[tileVariant="accent"] {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #238636, stop:1 #1a7f37);
                color: #ffffff;
                border: 1px solid #2ea043;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="accent"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2ea043, stop:1 #238636);
                border: 1px solid #3fb950;
            }
            QPushButton[tileVariant="accent"]:focus {
                border: 2px solid #3fb950;
            }
            """
        )

    def update_mode(self, mode_text: str):
        if mode_text == "Website":
            self.value_label.setText("Website URL")
            self.value_input.setPlaceholderText("https://www.youtube.com")
            self.helper_label.setText("Add a full URL or just a domain. LinuxTV will normalize it to HTTPS.")
        else:
            self.value_label.setText("Launch command")
            self.value_input.setPlaceholderText("flatpak run com.spotify.Client")
            self.helper_label.setText("Tip: Flatpak apps work too, for example `flatpak run com.spotify.Client`.")

    def values(self):
        return {
            "type": self.type_select.currentText(),
            "name": self.name_input.text().strip(),
            "value": self.value_input.text().strip(),
        }


class ConfirmDialog(QDialog):
    def __init__(self, parent=None, title_text="Confirm Delete", body_text="Delete this app?"):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setFixedWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", 24, QFont.Bold))
        layout.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("dialogSubtitle")
        body.setWordWrap(True)
        body.setFont(QFont("Sans Serif", 14))
        layout.addWidget(body)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.setProperty("tileVariant", "dialogSecondary")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        delete_button = QPushButton("Delete")
        delete_button.setProperty("tileVariant", "danger")
        delete_button.clicked.connect(self.accept)
        button_row.addWidget(delete_button)

        layout.addLayout(button_row)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 20px;
            }
            QLabel#dialogTitle {
                color: #f0f6fc;
            }
            QLabel#dialogSubtitle {
                color: #8b949e;
            }
            QPushButton[tileVariant="dialogSecondary"] {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="dialogSecondary"]:hover {
                background-color: #30363d;
                border: 1px solid #58a6ff;
            }
            QPushButton[tileVariant="danger"] {
                background-color: #da3633;
                color: #ffffff;
                border: 1px solid #f85149;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="danger"]:hover {
                background-color: #f85149;
                border: 1px solid #ff7b72;
            }
            """
        )


class SettingsDialog(QDialog):
    def __init__(self, username_text="", auto_launch=None, app_options=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LinuxTV Settings")
        self.setModal(True)
        self.setFixedWidth(560)

        auto_launch = auto_launch or {}
        app_options = app_options or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", 24, QFont.Bold))
        layout.addWidget(title)

        auto_title = QLabel("Auto Open")
        auto_title.setObjectName("dialogSection")
        auto_title.setFont(QFont("Sans Serif", 18, QFont.Bold))
        layout.addWidget(auto_title)

        auto_subtitle = QLabel("Choose which app or site opens automatically after LinuxTV sits idle.")
        auto_subtitle.setObjectName("dialogSubtitle")
        auto_subtitle.setWordWrap(True)
        auto_subtitle.setFont(QFont("Sans Serif", 14))
        layout.addWidget(auto_subtitle)

        self.auto_launch_combo = QComboBox()
        self.auto_launch_combo.setMinimumHeight(44)
        self.auto_launch_combo.addItem("Disabled", ("", ""))
        selected_kind = str(auto_launch.get("app_kind", "")).strip()
        selected_target = str(auto_launch.get("app_target", "")).strip()
        selected_index = 0
        for index, option in enumerate(app_options, start=1):
            self.auto_launch_combo.addItem(option["label"], (option["kind"], option["target"]))
            if option["kind"] == selected_kind and option["target"] == selected_target:
                selected_index = index
        self.auto_launch_combo.setCurrentIndex(selected_index)
        layout.addWidget(self.auto_launch_combo)

        self.delay_input = QLineEdit()
        self.delay_input.setPlaceholderText("Idle delay in seconds")
        self.delay_input.setText(str(auto_launch.get("delay_seconds", AUTO_LAUNCH_IDLE_MS // 1000)))
        self.delay_input.setMinimumHeight(44)
        layout.addWidget(self.delay_input)

        auto_helper = QLabel("Pick Disabled to turn auto open off. Enter a whole number of seconds.")
        auto_helper.setObjectName("dialogSubtitle")
        auto_helper.setWordWrap(True)
        auto_helper.setFont(QFont("Sans Serif", 13))
        layout.addWidget(auto_helper)

        remote_title = QLabel("Remote Login")
        remote_title.setObjectName("dialogSection")
        remote_title.setFont(QFont("Sans Serif", 18, QFont.Bold))
        layout.addWidget(remote_title)

        subtitle = QLabel("Set the phone credentials required to control LinuxTV.")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Sans Serif", 14))
        layout.addWidget(subtitle)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setText(username_text)
        self.username_input.setMinimumHeight(44)
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(44)
        layout.addWidget(self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Confirm password")
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.setMinimumHeight(44)
        layout.addWidget(self.confirm_input)

        helper = QLabel("Leave all three fields empty to disable phone authentication.")
        helper.setObjectName("dialogSubtitle")
        helper.setWordWrap(True)
        helper.setFont(QFont("Sans Serif", 13))
        layout.addWidget(helper)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.setProperty("tileVariant", "dialogSecondary")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        save_button = QPushButton("Save")
        save_button.setProperty("tileVariant", "accent")
        save_button.clicked.connect(self.accept)
        button_row.addWidget(save_button)

        layout.addLayout(button_row)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 20px;
            }
            QLabel#dialogTitle {
                color: #f0f6fc;
            }
            QLabel#dialogSection {
                color: #c9d1d9;
                padding-top: 8px;
                font-weight: 600;
            }
            QLabel#dialogSubtitle {
                color: #8b949e;
            }
            QLineEdit, QComboBox {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 10px 14px;
                font-size: 15px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #58a6ff;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox QAbstractItemView {
                background-color: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                selection-background-color: #1f6feb;
            }
            QPushButton[tileVariant="dialogSecondary"] {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="dialogSecondary"]:hover {
                background-color: #30363d;
                border: 1px solid #58a6ff;
            }
            QPushButton[tileVariant="accent"] {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #238636, stop:1 #1a7f37);
                color: #ffffff;
                border: 1px solid #2ea043;
                border-radius: 12px;
                padding: 12px 20px;
                min-width: 100px;
            }
            QPushButton[tileVariant="accent"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2ea043, stop:1 #238636);
                border: 1px solid #3fb950;
            }
            """
        )

    def values(self):
        selected_kind, selected_target = self.auto_launch_combo.currentData()
        return {
            "auto_launch_app_kind": selected_kind,
            "auto_launch_app_target": selected_target,
            "auto_launch_delay_seconds": self.delay_input.text().strip(),
            "username": self.username_input.text().strip(),
            "password": self.password_input.text(),
            "confirm_password": self.confirm_input.text(),
        }


class LauncherWindow(QMainWindow):
    def __init__(self, config_path: Path):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.browser_exe = find_browser()
        self.config_path = config_path

        self.config = load_config(config_path)
        self.tiles = []
        self.current_index = 0
        self.active_process = None
        self.active_process_kind = None
        self.active_process_name = None
        self.active_audio_thread = None
        self.active_audio_stop_event = None
        self.active_fullscreen_thread = None
        self.active_fullscreen_stop_event = None
        self.remote_target_window_cache = None
        self.remote_target_window_cache_at = 0.0
        self.remote_action_queue = queue.Queue()

        self.process_monitor = QTimer(self)
        self.process_monitor.setInterval(500)
        self.process_monitor.timeout.connect(self.check_active_process)

        self.remote_action_timer = QTimer(self)
        self.remote_action_timer.setInterval(50)
        self.remote_action_timer.timeout.connect(self.drain_remote_actions)
        self.remote_action_timer.start()

        self.auto_launch_timer = QTimer(self)
        self.auto_launch_timer.setSingleShot(True)
        self.auto_launch_timer.setInterval(AUTO_LAUNCH_IDLE_MS)
        self.auto_launch_timer.timeout.connect(self.auto_launch_selected_app_if_idle)

        self.auto_launch_countdown_timer = QTimer(self)
        self.auto_launch_countdown_timer.setInterval(250)
        self.auto_launch_countdown_timer.timeout.connect(self.update_auto_launch_status)
        self.auto_launch_paused = False

        self.ws_server = WebSocketControlServer(self)
        self.ws_server.start()

        # Initialize global input device grabber for system-wide remote control
        self.input_grabber = InputDeviceGrabber(self)
        self.input_grabber.start_grabbing()

        self.setup_ui()
        self.apply_fullscreen_to_primary_screen()

    def get_target_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            return screen
        screens = QApplication.screens()
        return screens[0] if screens else None

    def get_target_geometry(self):
        screen = self.get_target_screen()
        if screen:
            return screen.geometry()
        return self.geometry()

    def apply_fullscreen_to_primary_screen(self):
        geometry = self.get_target_geometry()
        self.setGeometry(geometry)
        self.move(geometry.topLeft())
        self.showFullScreen()

    def showEvent(self, event):
        super().showEvent(event)
        # Delay the reset until the window is actually visible so auto-open
        # also starts on a fresh system boot.
        QTimer.singleShot(0, self.reset_auto_launch_timer)

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("centralShell")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(40, 32, 40, 24)
        main_layout.setSpacing(14)

        hero = QWidget()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 16, 24, 16)
        hero_layout.setSpacing(0)

        hero_top_row = QHBoxLayout()
        hero_top_row.setContentsMargins(0, 0, 0, 0)
        hero_top_row.setSpacing(12)

        header_spacer = QWidget()
        header_spacer.setFixedSize(40, 40)
        hero_top_row.addWidget(header_spacer)

        hero_top_row.addStretch(1)
        title = QLabel("LinuxTV")
        title.setObjectName("heroTitle")
        title.setFont(QFont("Sans Serif", 34, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        hero_top_row.addWidget(title)
        hero_top_row.addStretch(1)

        settings_button = QToolButton()
        settings_button.setObjectName("settingsButton")
        settings_button.setText("⚙")
        settings_button.setToolTip("Open LinuxTV settings")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.setFixedSize(40, 40)
        settings_button.clicked.connect(self.open_remote_settings)
        hero_top_row.addWidget(settings_button)
        hero_layout.addLayout(hero_top_row)
        main_layout.addWidget(hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setObjectName("tileScroll")
        self.tile_scroll = scroll
        container = QWidget()
        container.setObjectName("tileContainer")
        self.grid = QGridLayout(container)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setHorizontalSpacing(20)
        self.grid.setVerticalSpacing(20)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.populate_tiles()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        footer = QLabel("Arrows move • Enter opens • Use the Add App tile to add apps or sites • Esc exits LinuxTV")
        footer.setObjectName("footerHint")
        footer.setWordWrap(True)
        footer.setFont(QFont("Sans Serif", 14))
        footer.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(footer)

        auto_launch_status_row = QHBoxLayout()
        auto_launch_status_row.setContentsMargins(0, 0, 0, 0)
        auto_launch_status_row.setSpacing(12)
        auto_launch_status_row.addStretch(1)

        self.auto_launch_status_label = QLabel("")
        self.auto_launch_status_label.setObjectName("autoLaunchStatus")
        self.auto_launch_status_label.setWordWrap(True)
        self.auto_launch_status_label.setFont(QFont("Sans Serif", 14))
        self.auto_launch_status_label.setAlignment(Qt.AlignCenter)
        self.auto_launch_status_label.hide()
        auto_launch_status_row.addWidget(self.auto_launch_status_label)

        self.auto_launch_cancel_button = QPushButton("Cancel Auto-Open")
        self.auto_launch_cancel_button.setObjectName("autoLaunchCancelButton")
        self.auto_launch_cancel_button.setCursor(Qt.PointingHandCursor)
        self.auto_launch_cancel_button.clicked.connect(self.toggle_auto_launch_pause)
        self.auto_launch_cancel_button.hide()
        auto_launch_status_row.addWidget(self.auto_launch_cancel_button)
        auto_launch_status_row.addStretch(1)
        main_layout.addLayout(auto_launch_status_row)

        self.setCentralWidget(central)
        self.apply_theme()

        if self.tiles:
            self.tiles[0].setFocus()
        self.reset_auto_launch_timer()

    def apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background: #0a0e17;
            }
            QWidget#centralShell {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0d1117, stop:0.5 #0f1419, stop:1 #0a0e17);
                color: #e6edf3;
            }
            QWidget#heroCard {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #161b22, stop:0.5 #1c2128, stop:1 #161b22);
                border: 1px solid #30363d;
                border-radius: 20px;
            }
            QToolButton#settingsButton {
                background-color: rgba(33, 38, 45, 0.95);
                color: #c9d1d9;
                border: 1px solid #3a424c;
                border-radius: 18px;
                font-size: 16px;
                padding-bottom: 1px;
            }
            QToolButton#settingsButton:hover {
                background-color: rgba(48, 54, 61, 0.98);
                border: 1px solid #58a6ff;
            }
            QToolButton#settingsButton:pressed {
                background-color: rgba(56, 63, 71, 1);
            }
            QLabel#heroTitle {
                color: #f0f6fc;
                font-weight: bold;
                letter-spacing: 0.5px;
            }
            QScrollArea#tileScroll, QWidget#tileContainer {
                background: transparent;
                border: none;
            }
            QScrollArea#tileScroll QScrollBar:vertical {
                background: transparent;
                width: 0px;
                margin: 0px;
            }
            QScrollArea#tileScroll QScrollBar:horizontal {
                background: transparent;
                height: 0px;
                margin: 0px;
            }
            QScrollArea#tileScroll::corner {
                background: transparent;
            }
            QPushButton[tileVariant="default"] {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #21262d, stop:1 #161b22);
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 16px;
                padding: 24px 28px;
                padding-left: 36px;
                padding-right: 80px;
                text-align: left;
                font-size: 16px;
            }
            QPushButton[tileVariant="default"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #30363d, stop:1 #21262d);
                border: 1px solid #58a6ff;
            }
            QPushButton[tileVariant="default"]:focus {
                border: 2px solid #58a6ff;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f6feb, stop:1 #1a5fb4);
                color: #ffffff;
            }
            QPushButton[tileVariant="accent"] {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #238636, stop:1 #1a7f37);
                color: #ffffff;
                border: 1px solid #2ea043;
                border-radius: 16px;
                padding: 24px 28px;
                padding-left: 36px;
                padding-right: 80px;
                text-align: left;
                font-size: 16px;
            }
            QPushButton[tileVariant="accent"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2ea043, stop:1 #238636);
                border: 1px solid #3fb950;
            }
            QPushButton[tileVariant="accent"]:focus {
                border: 2px solid #3fb950;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3fb950, stop:1 #2ea043);
            }
            QWidget#appCardShell {
                background: transparent;
            }
            QToolButton#editButton {
                background-color: rgba(33, 38, 45, 0.95);
                color: #8b949e;
                border: 1px solid #30363d;
                border-radius: 14px;
                font-size: 18px;
                padding-bottom: 2px;
            }
            QToolButton#editButton:hover {
                background-color: rgba(48, 54, 61, 0.98);
                color: #c9d1d9;
                border: 1px solid #58a6ff;
            }
            QToolButton#editButton:pressed {
                background-color: rgba(56, 63, 71, 1);
            }
            QToolButton#deleteButton {
                background-color: rgba(48, 27, 30, 0.95);
                color: #f85149;
                border: 1px solid #da3633;
                border-radius: 14px;
                font-size: 18px;
            }
            QToolButton#deleteButton:hover {
                background-color: rgba(63, 35, 39, 0.98);
                border: 1px solid #f85149;
            }
            QToolButton#deleteButton:pressed {
                background-color: rgba(78, 43, 48, 1);
            }
            QPushButton[hasSubtitle="true"] {
                padding-top: 20px;
                padding-bottom: 20px;
            }
            QLabel#footerHint {
                color: #8b949e;
                padding: 8px 16px;
                font-size: 14px;
            }
            QLabel#autoLaunchStatus {
                color: #58a6ff;
                padding: 0 16px 10px 16px;
                font-size: 14px;
            }
            QPushButton#autoLaunchCancelButton {
                background-color: rgba(33, 38, 45, 0.95);
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 14px;
                padding: 10px 18px;
                min-width: 150px;
                font-size: 14px;
            }
            QPushButton#autoLaunchCancelButton:hover {
                background-color: rgba(48, 54, 61, 0.98);
                border: 1px solid #58a6ff;
            }
            QPushButton#autoLaunchCancelButton:pressed {
                background-color: rgba(56, 63, 71, 1);
            }
            """
        )

    def clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def populate_tiles(self):
        self.clear_grid()
        self.tiles = []
        self.current_index = 0
        row = 0
        col = 0

        entries = self.get_launchable_entries()

        label = QLabel("Apps")
        label.setFont(QFont("Sans Serif", 24, QFont.Bold))
        label.setStyleSheet("color: #f0f6fc; padding: 16px 4px 8px 4px;")
        self.grid.addWidget(label, row, 0, 1, COLUMN_COUNT)
        row += 1

        for entry in entries:
            app = entry["item"]
            icon_path = resolve_native_icon(app) if entry["kind"] == "native" else fetch_web_icon(app)
            tile = TileButton(
                app.get("name", "Untitled"),
                icon_path,
                entry["tooltip"],
                subtitle=entry["subtitle"],
            )
            tile.clicked.connect(lambda checked=False, item=app, kind=entry["kind"]: self.launch_app(item, kind))
            card = AppCard(
                tile,
                lambda checked=False, item=app, kind=entry["kind"]: self.prompt_edit_entry(kind, item),
                lambda checked=False, item=app, kind=entry["kind"]: self.prompt_delete_entry(kind, item),
            )
            self.grid.addWidget(card, row, col)
            self.tiles.append(tile)
            col += 1
            if col >= COLUMN_COUNT:
                col = 0
                row += 1

        add_tile = TileButton("Add App", "", "Save a new app or site to config.yaml", variant="accent", subtitle="Add a command or website")
        add_tile.clicked.connect(self.prompt_add_entry)
        add_card = AppCard(add_tile, show_actions=False)
        self.grid.addWidget(add_card, row, col)
        self.tiles.append(add_tile)
        col += 1
        if col >= COLUMN_COUNT:
            col = 0
            row += 1

        self.reset_auto_launch_timer()

    def get_launchable_entries(self):
        entries = []
        for app in self.config.get("native_apps", []):
            if is_installed(app.get("cmd", "")):
                subtitle = app.get("cmd", "").split()[0] if app.get("cmd") else "Application"
                entries.append({
                    "kind": "native",
                    "item": app,
                    "subtitle": subtitle,
                    "tooltip": app.get("cmd", ""),
                })

        for app in self.config.get("web_apps", []):
            url = app.get("url", "")
            subtitle = url.replace("https://", "").replace("http://", "")
            entries.append({
                "kind": "web",
                "item": app,
                "subtitle": subtitle,
                "tooltip": url,
            })
        return entries

    def get_auto_launch_options(self):
        options = []
        for entry in self.get_launchable_entries():
            app = entry["item"]
            target = app.get("cmd", "") if entry["kind"] == "native" else app.get("url", "")
            label = f"{app.get('name', 'Untitled')} ({'App' if entry['kind'] == 'native' else 'Site'})"
            options.append({
                "kind": entry["kind"],
                "target": target,
                "label": label,
            })
        return options

    def normalize_url(self, url: str) -> str:
        cleaned = url.strip()
        if not cleaned:
            return cleaned
        if "://" not in cleaned:
            cleaned = "https://" + cleaned
        return cleaned

    def prompt_add_entry(self):
        dialog = AddItemDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        entry_type = values["type"]
        name = values["name"]
        value = values["value"]
        if not name or not value:
            QMessageBox.information(self, "Missing Details", "Enter both a name and a command or URL.")
            return
        if entry_type == "Application":
            self.add_native_app(name, value)
            return
        self.add_web_service(name, value)

    def prompt_edit_entry(self, kind: str, app):
        type_text = "Application" if kind == "native" else "Website"
        value_text = app.get("cmd", "") if kind == "native" else app.get("url", "")
        dialog = AddItemDialog(
            self,
            title_text="Edit App",
            type_text=type_text,
            name_text=app.get("name", ""),
            value_text=value_text,
            allow_type_change=False,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.values()
        if not values["name"] or not values["value"]:
            QMessageBox.information(self, "Missing Details", "Enter both a name and a command or URL.")
            return

        app["name"] = values["name"]
        if kind == "native":
            app["cmd"] = values["value"]
        else:
            app["url"] = self.normalize_url(values["value"])

        try:
            save_config(self.config_path, self.config)
        except Exception as exc:
            logging.exception("Failed to save config")
            QMessageBox.critical(self, "Save Failed", f"Could not save config:\n{exc}")
            return

        self.populate_tiles()
        if self.tiles:
            self.tiles[0].setFocus()
        QMessageBox.information(self, "Saved", f"{values['name']} has been updated.")

    def prompt_delete_entry(self, kind: str, app):
        dialog = ConfirmDialog(
            self,
            title_text="Delete App",
            body_text=f"Remove '{app.get('name', 'this app')}' from LinuxTV?",
        )
        if dialog.exec() != QDialog.Accepted:
            return

        collection_name = "native_apps" if kind == "native" else "web_apps"
        collection = self.config.get(collection_name, [])
        try:
            collection.remove(app)
        except ValueError:
            return

        try:
            save_config(self.config_path, self.config)
        except Exception as exc:
            logging.exception("Failed to save config")
            QMessageBox.critical(self, "Save Failed", f"Could not save config:\n{exc}")
            collection.append(app)
            return

        self.populate_tiles()
        if self.tiles:
            self.tiles[0].setFocus()

    def open_remote_settings(self):
        auth = self.config.get("auth", {})
        auto_launch = self.config.get("auto_launch", {})
        dialog = SettingsDialog(
            auth.get("username", ""),
            auto_launch,
            self.get_auto_launch_options(),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.values()
        auto_launch_delay_text = values["auto_launch_delay_seconds"]
        try:
            auto_launch_delay_seconds = int(auto_launch_delay_text)
        except ValueError:
            QMessageBox.information(self, "Invalid Delay", "Enter a whole number of seconds for auto open.")
            return
        if auto_launch_delay_seconds < 1:
            QMessageBox.information(self, "Invalid Delay", "Auto open delay must be at least 1 second.")
            return

        self.config["auto_launch"] = {
            "app_kind": values["auto_launch_app_kind"],
            "app_target": values["auto_launch_app_target"],
            "delay_seconds": auto_launch_delay_seconds,
        }
        username = values["username"]
        password = values["password"]
        confirm_password = values["confirm_password"]

        if username or password or confirm_password:
            if not username or not password:
                QMessageBox.information(self, "Missing Details", "Enter both a username and password, or leave all fields blank to disable authentication.")
                return
            if password != confirm_password:
                QMessageBox.information(self, "Password Mismatch", "The passwords do not match.")
                return
            self.config["auth"] = {
                "username": username,
                "password_hash": hash_remote_password(password),
            }
        else:
            self.config["auth"] = dict(DEFAULT_CONFIG["auth"])

        try:
            save_config(self.config_path, self.config)
        except Exception as exc:
            logging.exception("Failed to save settings")
            QMessageBox.critical(self, "Save Failed", f"Could not save settings:\n{exc}")
            return

        self.reset_auto_launch_timer()
        if remote_auth_enabled(self.config):
            QMessageBox.information(self, "Saved", "Settings saved. Phone authentication is enabled for LinuxTV Remote.")
        else:
            QMessageBox.information(self, "Saved", "Settings saved. Phone authentication is disabled.")

    def add_native_app(self, name: str, cmd: str):
        native_apps = self.config.setdefault("native_apps", [])
        native_apps.append({"name": name.strip(), "cmd": cmd.strip(), "icon": ""})

        try:
            save_config(self.config_path, self.config)
        except Exception as exc:
            logging.exception("Failed to save config")
            QMessageBox.critical(self, "Save Failed", f"Could not save config:\n{exc}")
            native_apps.pop()
            return

        self.populate_tiles()
        if self.tiles:
            self.current_index = max(len(self.tiles) - 2, 0)
            self.tiles[self.current_index].setFocus()
        QMessageBox.information(self, "Added", f"{name.strip()} is now available in Apps.")

    def add_web_service(self, name: str, url: str):
        normalized_url = self.normalize_url(url)
        web_apps = self.config.setdefault("web_apps", [])
        web_apps.append({"name": name.strip(), "url": normalized_url, "icon": ""})

        try:
            save_config(self.config_path, self.config)
        except Exception as exc:
            logging.exception("Failed to save config")
            QMessageBox.critical(self, "Save Failed", f"Could not save config:\n{exc}")
            web_apps.pop()
            return

        self.populate_tiles()
        if self.tiles:
            self.current_index = max(len(self.tiles) - 2, 0)
            self.tiles[self.current_index].setFocus()
        QMessageBox.information(self, "Added", f"{name.strip()} is now available in Apps.")

    def keyPressEvent(self, event):
        if not self.tiles:
            return

        key = event.key()
        self.reset_auto_launch_timer()
        if key == Qt.Key_Escape:
            self.close()
            return

        if key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_Down, Qt.Key_Up):
            self.navigate({
                Qt.Key_Right: "RIGHT",
                Qt.Key_Left: "LEFT",
                Qt.Key_Down: "DOWN",
                Qt.Key_Up: "UP",
            }[key])
            return

        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activate_current()

    def closeEvent(self, event):
        if hasattr(self, "ws_server") and self.ws_server:
            self.ws_server.stop()
        if hasattr(self, "input_grabber") and self.input_grabber:
            self.input_grabber.stop_grabbing()
        event.accept()

    def queue_remote_action(self, action):
        self.remote_action_queue.put(action)

    def queue_remote_event(self, event):
        self.remote_action_queue.put(event)

    def drain_remote_actions(self):
        while True:
            try:
                action = self.remote_action_queue.get_nowait()
            except queue.Empty:
                break
            self.process_remote_event(action)

    def process_remote_event(self, event):
        if isinstance(event, dict):
            event_type = str(event.get("type", "")).lower()
            if event_type == "text":
                self.send_remote_text_to_active_window(str(event.get("text", "")))
                return
            if event_type == "key":
                self.send_remote_special_key_to_active_window(str(event.get("key", "")))
                return
            if event_type == "pointer":
                self.process_remote_pointer_event(event)
                return

        self.process_remote_action(str(event))

    def launcher_window_ids(self):
        window_ids = set()
        for widget in QApplication.topLevelWidgets():
            if not widget.isVisible():
                continue
            try:
                window_ids.add(str(int(widget.winId())))
            except Exception:
                continue
        return window_ids

    def active_system_window(self):
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return None, None
        active_window = run_command([xdotool, "getactivewindow"]).strip()
        return xdotool, active_window or None

    def focus_remote_target_window(self, xdotool, target_window):
        if not xdotool or not target_window:
            return False
        subprocess.run([xdotool, "windowactivate", "--sync", target_window], check=False)
        subprocess.run([xdotool, "windowfocus", "--sync", target_window], check=False)
        return True

    def remember_remote_target_window(self, target_window):
        if not target_window:
            return
        self.remote_target_window_cache = target_window
        self.remote_target_window_cache_at = time.monotonic()

    def clear_remote_target_window_cache(self):
        self.remote_target_window_cache = None
        self.remote_target_window_cache_at = 0.0

    def _focus_launched_app_window(self, pid: int, attempts: int = 10, delay_seconds: float = 1.0):
        """Wait for a launched app window to appear, then activate it."""
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return

        for _ in range(attempts):
            time.sleep(delay_seconds)
            window_ids = find_window_ids_for_pid(pid)
            if not window_ids:
                continue

            target_window = window_ids[0]
            subprocess.run([xdotool, "windowactivate", "--sync", target_window], check=False)
            subprocess.run([xdotool, "windowfocus", "--sync", target_window], check=False)
            logging.info("Focused launched app window %s for pid %s", target_window, pid)
            return

        logging.warning("Could not find window for launched app pid %s after %s attempts", pid, attempts)

    def launcher_context_is_active(self):
        _, active_window = self.active_system_window()
        launcher_ids = self.launcher_window_ids()
        if active_window and active_window in launcher_ids:
            return True
        active_widget = QApplication.activeWindow()
        return bool(active_widget and active_widget.isVisible())

    def dispatch_remote_key_to_launcher(self, key, modifiers=Qt.NoModifier, text=""):
        target = QApplication.focusWidget() or QApplication.activeWindow() or self
        if not target:
            return False

        for event_type in (QEvent.KeyPress, QEvent.KeyRelease):
            event = QKeyEvent(event_type, key, modifiers, text)
            QApplication.sendEvent(target, event)
        return True

    def handle_remote_action_in_launcher(self, action: str):
        modal_widget = QApplication.activeModalWidget()
        if modal_widget:
            modal_widget.activateWindow()
            modal_widget.raise_()

        if not modal_widget and self.isVisible():
            if action in ("UP", "DOWN", "LEFT", "RIGHT"):
                self.navigate(action)
                return True

            if action in ("SELECT", "OK"):
                self.activate_current()
                return True

            if action in ("BACK", "HOME"):
                self.current_index = 0
                if self.tiles:
                    self.tiles[0].setFocus()
                return True

        qt_action_map = {
            "UP": (Qt.Key_Up, Qt.NoModifier, ""),
            "DOWN": (Qt.Key_Down, Qt.NoModifier, ""),
            "LEFT": (Qt.Key_Left, Qt.NoModifier, ""),
            "RIGHT": (Qt.Key_Right, Qt.NoModifier, ""),
            "SELECT": (Qt.Key_Return, Qt.NoModifier, "\r"),
            "OK": (Qt.Key_Return, Qt.NoModifier, "\r"),
            "BACK": (Qt.Key_Escape, Qt.NoModifier, ""),
            "HOME": (Qt.Key_Home, Qt.NoModifier, ""),
            "TAB": (Qt.Key_Tab, Qt.NoModifier, "\t"),
            "SHIFT_TAB": (Qt.Key_Backtab, Qt.ShiftModifier, "\t"),
            "MENU": (Qt.Key_Menu, Qt.NoModifier, ""),
            "PLAY_PAUSE": (Qt.Key_Space, Qt.NoModifier, " "),
            "INFO": (Qt.Key_I, Qt.NoModifier, "i"),
        }
        key_info = qt_action_map.get(action)
        if not key_info:
            return False
        return self.dispatch_remote_key_to_launcher(*key_info)

    def process_remote_action(self, action: str):
        action = action.upper()
        launcher_active = self.launcher_context_is_active()
        if action in ("UP", "DOWN", "LEFT", "RIGHT") and launcher_active:
            self.pause_auto_launch()
        else:
            self.reset_auto_launch_timer()
        xdotool, target_window = self.remote_target_window()
        if launcher_active and self.handle_remote_action_in_launcher(action):
            return

        if xdotool and target_window and action in (
            "UP",
            "DOWN",
            "LEFT",
            "RIGHT",
            "SELECT",
            "OK",
            "BACK",
            "HOME",
            "TAB",
            "SHIFT_TAB",
            "MENU",
            "PLAY_PAUSE",
            "INFO",
        ):
            self.send_remote_key_to_active_window(action)
            return

        if action in ("CLOSE", "EXIT", "STOP", "CLOSE_APP") and self.active_process:
            self.close_active_app()
            return

        if action in ("SHUTDOWN", "REBOOT"):
            request_system_power_action(action)
            return

        if action in ("UP", "DOWN", "LEFT", "RIGHT"):
            self.navigate(action)
            return

        if action in ("SELECT", "OK"):
            self.activate_current()
            return

        if action == "BACK":
            # On launcher this returns to start tile
            self.current_index = 0
            self.tiles[0].setFocus()
            return

        if action == "HOME":
            self.current_index = 0
            self.tiles[0].setFocus()
            return

        if action in ("CLOSE", "EXIT", "STOP", "CLOSE_APP"):
            self.close()
            return

        logging.warning("Unknown remote action: %s", action)

    def active_app_profile(self):
        name = (self.active_process_name or "").lower()
        if "kodi" in name:
            return "kodi"
        if "stremio" in name:
            return "stremio"
        if self.active_process_kind == "web":
            return "web"
        return "generic"

    def key_sequences_for_action(self, action: str):
        profile = self.active_app_profile()

        common_map = {
            "UP": ["Up"],
            "DOWN": ["Down"],
            "LEFT": ["Left"],
            "RIGHT": ["Right"],
            "SELECT": ["Return"],
            "OK": ["Return"],
            "TAB": ["Tab"],
            "SHIFT_TAB": ["shift+Tab"],
            "PLAY_PAUSE": ["space"],
            "MENU": ["m"],
            "INFO": ["i"],
        }

        profile_overrides = {
            "web": {
                "BACK": ["Alt+Left", "BackSpace", "Escape"],
                "HOME": ["Alt+Home", "Home"],
                "MENU": ["Alt"],
                "PLAY_PAUSE": ["k", "space"],
            },
            "kodi": {
                "BACK": ["BackSpace", "Escape"],
                "HOME": ["h"],
                "MENU": ["c"],
                "PLAY_PAUSE": ["space"],
                "INFO": ["i"],
            },
            "stremio": {
                "BACK": ["BackSpace", "Escape"],
                "HOME": ["Home"],
                "MENU": ["m"],
                "PLAY_PAUSE": ["space", "k"],
                "INFO": ["i"],
            },
        }

        overrides = profile_overrides.get(profile, {})
        if action in overrides:
            return overrides[action]
        return common_map.get(action, [])

    def remote_target_window(self, focus: bool = True, allow_cached: bool = False):
        xdotool, active_window = self.active_system_window()
        if not xdotool:
            return None, None

        if active_window and active_window not in self.launcher_window_ids():
            self.remember_remote_target_window(active_window)
            return xdotool, active_window

        if allow_cached:
            cache_age = time.monotonic() - self.remote_target_window_cache_at
            if self.remote_target_window_cache and cache_age <= REMOTE_POINTER_TARGET_CACHE_SECONDS:
                return xdotool, self.remote_target_window_cache

        if not self.active_process or self.active_process.poll() is not None:
            self.clear_remote_target_window_cache()
            return xdotool, None

        window_ids = find_window_ids_for_pid(self.active_process.pid)
        if not window_ids:
            return xdotool, None

        target_window = window_ids[0]
        self.remember_remote_target_window(target_window)
        if focus:
            self.focus_remote_target_window(xdotool, target_window)
        return xdotool, target_window

    def send_remote_key_to_active_window(self, action: str):
        key_sequences = self.key_sequences_for_action(action)
        if not key_sequences:
            logging.warning("No key mapping for remote action %s", action)
            return

        xdotool, target_window = self.remote_target_window()
        if not xdotool:
            logging.warning("xdotool is not installed; cannot forward remote action %s", action)
            return
        if not target_window:
            logging.warning("No active target window found for remote action %s", action)
            return

        self.focus_remote_target_window(xdotool, target_window)
        for key_name in key_sequences:
            subprocess.run([xdotool, "key", "--window", target_window, "--clearmodifiers", key_name], check=False)
        logging.info("Forwarded remote action %s to active window", action)

    def send_remote_text_to_active_window(self, text: str):
        if not text:
            return

        xdotool, target_window = self.remote_target_window()
        if not xdotool:
            logging.warning("xdotool is not installed; cannot type remote text")
            return
        if not target_window:
            logging.warning("No active target window found for remote text")
            return

        self.focus_remote_target_window(xdotool, target_window)
        subprocess.run(
            [xdotool, "type", "--window", target_window, "--delay", "0", text],
            check=False,
        )
        logging.info("Forwarded remote text to active window")

    def send_remote_special_key_to_active_window(self, key: str):
        if not key:
            return

        key_map = {
            "ENTER": "Return",
            "SPACE": "space",
            "BACKSPACE": "BackSpace",
            "ESCAPE": "Escape",
            "TAB": "Tab",
        }
        key_name = key_map.get(key.upper())
        if not key_name:
            logging.warning("Unknown remote special key: %s", key)
            return

        if self.launcher_context_is_active():
            qt_special_key_map = {
                "ENTER": (Qt.Key_Return, Qt.NoModifier, "\r"),
                "SPACE": (Qt.Key_Space, Qt.NoModifier, " "),
                "BACKSPACE": (Qt.Key_Backspace, Qt.NoModifier, "\b"),
                "ESCAPE": (Qt.Key_Escape, Qt.NoModifier, ""),
                "TAB": (Qt.Key_Tab, Qt.NoModifier, "\t"),
            }
            key_info = qt_special_key_map.get(key.upper())
            if key_info and self.dispatch_remote_key_to_launcher(*key_info):
                logging.info("Forwarded remote special key %s to LinuxTV", key)
                return

        xdotool, target_window = self.remote_target_window()
        if not xdotool:
            logging.warning("xdotool is not installed; cannot send remote special key %s", key)
            return
        if not target_window:
            logging.warning("No active target window found for remote special key %s", key)
            return

        self.focus_remote_target_window(xdotool, target_window)
        subprocess.run([xdotool, "key", "--window", target_window, "--clearmodifiers", key_name], check=False)
        logging.info("Forwarded remote special key %s to active window", key)

    def process_remote_pointer_event(self, event):
        event_type = str(event.get("event", "")).lower()
        allow_cached = event_type == "move"
        focus_target = event_type != "move"
        xdotool, target_window = self.remote_target_window(focus=focus_target, allow_cached=allow_cached)
        if not xdotool:
            logging.warning("xdotool is not installed; cannot forward remote pointer event")
            return
        if not target_window:
            logging.warning("No active target window found for remote pointer event")
            return

        if event_type == "move":
            dx = int(round(float(event.get("dx", 0)) * REMOTE_POINTER_SPEED_MULTIPLIER))
            dy = int(round(float(event.get("dy", 0)) * REMOTE_POINTER_SPEED_MULTIPLIER))
            if dx or dy:
                subprocess.run([xdotool, "mousemove_relative", "--", str(dx), str(dy)], check=False)
            return

        if event_type in ("tap", "click"):
            self.focus_remote_target_window(xdotool, target_window)
            subprocess.run([xdotool, "click", "1"], check=False)
            return

        if event_type == "right_click":
            self.focus_remote_target_window(xdotool, target_window)
            subprocess.run([xdotool, "click", "3"], check=False)
            return

    def close_active_app(self):
        if not self.active_process or self.active_process.poll() is not None:
            logging.info("No active app to close")
            return

        logging.info("Closing active app %s (pid=%s)", self.active_process_name, self.active_process.pid)
        try:
            os.killpg(self.active_process.pid, signal.SIGTERM)
        except Exception:
            logging.exception("Failed to terminate active app process group")
            try:
                self.active_process.terminate()
            except Exception:
                logging.exception("Failed to terminate active app directly")

    def check_active_process(self):
        if not self.active_process:
            return

        if self.active_process.poll() is None:
            return

        logging.info("Active app exited with code %s", self.active_process.returncode)
        self.finish_active_process()

    def finish_active_process(self):
        if self.active_audio_stop_event:
            self.active_audio_stop_event.set()
        if self.active_fullscreen_stop_event:
            self.active_fullscreen_stop_event.set()
        if self.active_audio_thread:
            self.active_audio_thread.join(timeout=1)
        if self.active_fullscreen_thread:
            self.active_fullscreen_thread.join(timeout=1)

        self.active_process = None
        self.active_process_kind = None
        self.active_process_name = None
        self.active_audio_thread = None
        self.active_audio_stop_event = None
        self.active_fullscreen_thread = None
        self.active_fullscreen_stop_event = None
        self.clear_remote_target_window_cache()
        self.process_monitor.stop()

        self.apply_fullscreen_to_primary_screen()
        self.raise_()
        self.activateWindow()
        QApplication.restoreOverrideCursor()
        self.auto_launch_paused = False
        if self.tiles:
            self.tiles[self.current_index].setFocus()
        self.reset_auto_launch_timer()

    def toggle_auto_launch_pause(self):
        self.auto_launch_paused = not self.auto_launch_paused
        if self.auto_launch_paused:
            self.auto_launch_timer.stop()
            self.auto_launch_countdown_timer.stop()
        else:
            self.reset_auto_launch_timer()
            return
        self.update_auto_launch_status()

    def pause_auto_launch(self):
        if self.auto_launch_paused:
            self.update_auto_launch_status()
            return
        self.auto_launch_paused = True
        self.auto_launch_timer.stop()
        self.auto_launch_countdown_timer.stop()
        self.update_auto_launch_status()

    def reset_auto_launch_timer(self):
        if self.active_process or not self.isVisible() or QApplication.activeModalWidget():
            self.auto_launch_timer.stop()
            self.auto_launch_countdown_timer.stop()
            self.update_auto_launch_status()
            return
        auto_launch = self.config.get("auto_launch", {})
        delay_seconds = int(auto_launch.get("delay_seconds", AUTO_LAUNCH_IDLE_MS // 1000) or 0)
        app_kind = str(auto_launch.get("app_kind", "")).strip()
        app_target = str(auto_launch.get("app_target", "")).strip()
        if not app_kind or not app_target or delay_seconds < 1:
            self.auto_launch_timer.stop()
            self.auto_launch_countdown_timer.stop()
            self.update_auto_launch_status()
            return
        selected_entry = self.find_auto_launch_entry()
        if selected_entry is None:
            self.auto_launch_timer.stop()
            self.auto_launch_countdown_timer.stop()
            self.update_auto_launch_status()
            return
        if self.auto_launch_paused:
            self.auto_launch_timer.stop()
            self.auto_launch_countdown_timer.stop()
            self.update_auto_launch_status()
            return
        self.auto_launch_timer.setInterval(delay_seconds * 1000)
        self.auto_launch_timer.start()
        self.auto_launch_countdown_timer.start()
        self.update_auto_launch_status()

    def find_auto_launch_entry(self):
        auto_launch = self.config.get("auto_launch", {})
        target_kind = str(auto_launch.get("app_kind", "")).strip()
        target_value = str(auto_launch.get("app_target", "")).strip()
        if not target_kind or not target_value:
            return None

        for entry in self.get_launchable_entries():
            app = entry["item"]
            value = app.get("cmd", "") if entry["kind"] == "native" else app.get("url", "")
            if entry["kind"] == target_kind and value == target_value:
                return entry
        return None

    def auto_launch_selected_app_if_idle(self):
        self.auto_launch_countdown_timer.stop()
        self.update_auto_launch_status()
        if self.active_process or not self.isVisible() or QApplication.activeModalWidget():
            return

        selected_entry = self.find_auto_launch_entry()
        if selected_entry is None:
            return

        logging.info("Idle timeout reached; auto-launching %s", selected_entry["item"].get("name", "selected app"))
        self.launch_app(selected_entry["item"], selected_entry["kind"])

    def update_auto_launch_status(self):
        if not hasattr(self, "auto_launch_status_label"):
            return

        selected_entry = self.find_auto_launch_entry()
        if selected_entry is None:
            self.auto_launch_status_label.hide()
            self.auto_launch_status_label.setText("")
            self.auto_launch_cancel_button.hide()
            return

        if self.active_process or not self.isVisible() or QApplication.activeModalWidget():
            self.auto_launch_status_label.hide()
            self.auto_launch_status_label.setText("")
            self.auto_launch_cancel_button.hide()
            return

        app_name = selected_entry["item"].get("name", "selected app")
        if self.auto_launch_paused:
            self.auto_launch_status_label.setText(
                f"Auto-open paused for {app_name}. Resume when you're ready."
            )
            self.auto_launch_cancel_button.setText("Resume Auto-Open")
        else:
            remaining_ms = self.auto_launch_timer.remainingTime()
            if remaining_ms is None or remaining_ms < 0 or not self.auto_launch_timer.isActive():
                remaining_seconds = int(self.config.get("auto_launch", {}).get("delay_seconds", AUTO_LAUNCH_IDLE_MS // 1000) or 0)
            else:
                remaining_seconds = max(0, (remaining_ms + 999) // 1000)
            self.auto_launch_status_label.setText(
                f"Auto-open enabled: opening {app_name} in {remaining_seconds} seconds."
            )
            self.auto_launch_cancel_button.setText("Cancel Auto-Open")
        self.auto_launch_status_label.show()
        self.auto_launch_cancel_button.show()

    def navigate(self, direction: str):
        if not self.tiles:
            return

        max_idx = len(self.tiles) - 1
        row_count = COLUMN_COUNT
        old = self.current_index

        if direction == "RIGHT":
            self.current_index = min(old + 1, max_idx)
        elif direction == "LEFT":
            self.current_index = max(old - 1, 0)
        elif direction == "DOWN":
            self.current_index = min(old + row_count, max_idx)
        elif direction == "UP":
            self.current_index = max(old - row_count, 0)

        self.tiles[self.current_index].setFocus()
        self.ensure_current_tile_visible()
        self.reset_auto_launch_timer()

    def ensure_current_tile_visible(self):
        if not hasattr(self, "tile_scroll") or not self.tiles:
            return
        current_tile = self.tiles[self.current_index]
        self.tile_scroll.ensureWidgetVisible(current_tile, 24, 24)

    def activate_current(self):
        if not self.tiles:
            return
        self.auto_launch_timer.stop()
        widget = self.tiles[self.current_index]
        if widget:
            widget.click()

    def launch_app(self, item, kind: str):
        self.auto_launch_timer.stop()
        command = None
        if kind == "native":
            cmd = item.get("cmd")
            if not cmd:
                logging.warning("Native item missing command: %s", item)
                return
            command = split_command(cmd)
            executable_name = Path(command[0]).name.lower() if command else ""
            if executable_name == "vlc":
                command.extend(["--fullscreen", "--video-on-top"])

        if kind == "web":
            if not self.browser_exe:
                logging.error("No browser found for web app launch")
                return
            url = item.get("url")
            if not url:
                logging.warning("Web app missing URL: %s", item)
                return

            if "chromium" in self.browser_exe or "chrome" in self.browser_exe or "brave" in self.browser_exe:
                geometry = self.get_target_geometry()
                command = [
                    self.browser_exe,
                    "--kiosk",
                    "--start-fullscreen",
                    "--app=%s" % url,
                    "--no-first-run",
                    "--disable-translate",
                    "--disable-infobars",
                    "--window-position=%s,%s" % (geometry.x(), geometry.y()),
                    "--window-size=%s,%s" % (geometry.width(), geometry.height()),
                ]
            elif "firefox" in self.browser_exe:
                command = [self.browser_exe, "--kiosk", url]
            else:
                command = [self.browser_exe, url]

        if not command:
            logging.error("Cannot create command for %s item: %s", kind, item)
            return

        logging.info("Launching %s: %s", item.get("name"), command)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Drop out of the way so the launched app receives focus/input.
            self.hide()
            self.clear_remote_target_window_cache()
            switch_audio_to_hdmi()
            geometry = self.get_target_geometry()
            self.active_process = subprocess.Popen(command, start_new_session=True)
            self.active_process_kind = kind
            self.active_process_name = item.get("name")
            self.active_audio_stop_event = threading.Event()
            self.active_audio_thread = threading.Thread(
                target=maintain_hdmi_audio,
                args=(self.active_audio_stop_event,),
                daemon=True,
            )
            self.active_audio_thread.start()
            if kind == "native":
                self.active_fullscreen_stop_event = threading.Event()
                self.active_fullscreen_thread = threading.Thread(
                    target=enforce_native_fullscreen,
                    args=(command, self.active_process.pid, geometry, self.active_fullscreen_stop_event),
                    daemon=True,
                )
                self.active_fullscreen_thread.start()
            else:
                self.active_fullscreen_stop_event = None
                self.active_fullscreen_thread = None
            self.process_monitor.start()
            threading.Thread(
                target=self._focus_launched_app_window,
                args=(self.active_process.pid,),
                daemon=True,
            ).start()
        except Exception:
            logging.exception("App launch failed")
            self.finish_active_process()


def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logging.info("Starting %s with Qt binding %s", APP_NAME, QT_BINDING)

    config_path = resolve_config_path()

    app = QApplication(sys.argv)

    window = LauncherWindow(config_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
