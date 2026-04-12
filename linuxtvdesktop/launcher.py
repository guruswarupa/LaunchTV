#!/usr/bin/env python3
import asyncio
import configparser
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
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
import tempfile
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
                signal_type = qt_core.pyqtSignal
            elif binding == "PySide6":
                qt_core = importlib.import_module("PySide6.QtCore")
                qt_gui = importlib.import_module("PySide6.QtGui")
                qt_widgets = importlib.import_module("PySide6.QtWidgets")
                signal_type = qt_core.Signal
            else:
                logging.warning("Unknown Qt binding requested: %s", binding)
                continue

            return (
                binding,
                qt_core.QEvent,
                qt_core.QEasingCurve,
                qt_core.QObject,
                qt_core.QPropertyAnimation,
                qt_core.QRect,
                qt_core.Qt,
                qt_core.QSize,
                qt_core.QTimer,
                signal_type,
                qt_gui.QFont,
                qt_gui.QIcon,
                qt_gui.QKeyEvent,
                qt_gui.QPixmap,
                qt_gui.QWheelEvent,
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
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    Qt,
    QSize,
    QTimer,
    Signal,
    QFont,
    QIcon,
    QKeyEvent,
    QPixmap,
    QWheelEvent,
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
        {"name": "Stremio", "cmd": "flatpak run com.stremio.Stremio", "icon": "icons/stremio.png"},
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
UPDATE_REPO_URL = "https://github.com/guruswarupa/LinuxTV"


def sync_system_time():
    timedatectl = shutil.which("timedatectl")
    if not timedatectl:
        return False, "timedatectl is not installed."

    try:
        result = subprocess.run(
            [timedatectl, "set-ntp", "true"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception as exc:
        logging.exception("Failed to enable automatic time sync")
        return False, f"Could not enable automatic time sync: {exc}"

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Unknown error").strip()
        return False, f"Could not enable automatic time sync: {message}"

    try:
        status_result = subprocess.run(
            [timedatectl, "show", "--property=NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        ntp_synced = status_result.stdout.strip().lower() == "yes"
    except Exception:
        ntp_synced = False

    if ntp_synced:
        return True, "System time synchronized."
    return True, "Automatic time sync enabled."


def dialog_metrics():
    screen = QApplication.primaryScreen()
    geometry = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
    width = geometry.width()
    height = geometry.height()
    compact = width <= 1600 or height <= 950
    if compact:
        return {
            "compact": True,
            "add_width": 460,
            "confirm_width": 420,
            "settings_width": 560,
            "settings_height": 610,
            "dialog_margin_x": 22,
            "dialog_margin_y": 20,
            "dialog_spacing": 12,
            "title_font": 20,
            "section_font": 16,
            "subtitle_font": 12,
            "helper_font": 11,
            "input_min_height": 40,
            "nav_spacing": 8,
            "status_padding_v": 10,
            "status_padding_h": 12,
            "field_font_css": 13,
            "button_font_css": 13,
            "button_min_width": 96,
            "button_padding_v": 11,
            "button_padding_h": 16,
        }
    return {
        "compact": False,
        "add_width": 560,
        "confirm_width": 500,
        "settings_width": 640,
        "settings_height": 700,
        "dialog_margin_x": 28,
        "dialog_margin_y": 24,
        "dialog_spacing": 14,
        "title_font": 24,
        "section_font": 18,
        "subtitle_font": 14,
        "helper_font": 13,
        "input_min_height": 44,
        "nav_spacing": 10,
        "status_padding_v": 12,
        "status_padding_h": 14,
        "field_font_css": 15,
        "button_font_css": 15,
        "button_min_width": 110,
        "button_padding_v": 13,
        "button_padding_h": 20,
    }


def dialog_stylesheet(metrics=None):
    metrics = metrics or dialog_metrics()
    stylesheet = """
        QDialog {
            background-color: #111418;
            border: 1px solid #2a3139;
            border-radius: 22px;
        }
        QLabel#dialogTitle {
            color: #f7f9fb;
        }
        QLabel#dialogSection {
            color: #eef2f7;
            padding-top: 10px;
            font-weight: 700;
        }
        QLabel#dialogSubtitle {
            color: #9aa7b4;
        }
        QLabel#dialogFieldLabel {
            color: #dbe3ec;
            font-weight: 600;
            padding-top: 6px;
        }
        QLabel#dialogHelper {
            color: #7e8b97;
            padding-top: 4px;
        }
        QLabel#dialogStatus {
            color: #b7c4d1;
            background-color: #171d24;
            border: 1px solid #29323c;
            border-radius: 12px;
            padding: __STATUS_PADDING_V__px __STATUS_PADDING_H__px;
        }
        QLineEdit, QComboBox {
            background-color: #0b0f13;
            color: #edf2f7;
            border: 1px solid #2b3641;
            border-radius: 14px;
            padding: __BUTTON_PADDING_V__px 16px;
            min-height: 24px;
            font-size: __FIELD_FONT__px;
        }
        QLineEdit:focus, QComboBox:focus {
            border: 1px solid #33c3a0;
        }
        QComboBox::drop-down {
            border: none;
            width: 28px;
        }
        QComboBox QAbstractItemView {
            background-color: #141a21;
            color: #edf2f7;
            border: 1px solid #2b3641;
            selection-background-color: #33c3a0;
            selection-color: #09110f;
            alternate-background-color: #10161d;
        }
        QComboBox QAbstractItemView::item {
            background-color: #141a21;
            color: #edf2f7;
            padding: 8px 10px;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: #33c3a0;
            color: #09110f;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #1d2731;
            color: #edf2f7;
        }
        QComboBox QLineEdit {
            background-color: #0b0f13;
            color: #edf2f7;
            border: none;
            selection-background-color: #33c3a0;
            selection-color: #09110f;
        }
        QPushButton[tileVariant="dialogSecondary"] {
            background-color: #1a222b;
            color: #d9e2ec;
            border: 1px solid #32404d;
            border-radius: 14px;
            padding: __BUTTON_PADDING_V__px __BUTTON_PADDING_H__px;
            min-width: __BUTTON_MIN_WIDTH__px;
            font-size: __BUTTON_FONT__px;
            font-weight: 500;
        }
        QPushButton[tileVariant="dialogSecondary"]:hover {
            background-color: #212c37;
            border: 1px solid #4a5d6f;
        }
        QPushButton[tileVariant="accent"] {
            background-color: #33c3a0;
            color: #08130f;
            border: 1px solid #6be2c5;
            border-radius: 14px;
            padding: __BUTTON_PADDING_V__px __BUTTON_PADDING_H__px;
            min-width: __BUTTON_MIN_WIDTH__px;
            font-size: __BUTTON_FONT__px;
            font-weight: 700;
        }
        QPushButton[tileVariant="accent"]:hover {
            background-color: #4bd3b2;
            border: 1px solid #8bead1;
        }
        QPushButton[tileVariant="danger"] {
            background-color: #d74f62;
            color: #ffffff;
            border: 1px solid #f18493;
            border-radius: 14px;
            padding: __BUTTON_PADDING_V__px __BUTTON_PADDING_H__px;
            min-width: __BUTTON_MIN_WIDTH__px;
            font-size: __BUTTON_FONT__px;
            font-weight: 700;
        }
        QPushButton[tileVariant="danger"]:hover {
            background-color: #e06375;
            border: 1px solid #f5a0ac;
        }
    """
    replacements = {
        "__STATUS_PADDING_V__": str(metrics["status_padding_v"]),
        "__STATUS_PADDING_H__": str(metrics["status_padding_h"]),
        "__BUTTON_PADDING_V__": str(metrics["button_padding_v"]),
        "__BUTTON_PADDING_H__": str(metrics["button_padding_h"]),
        "__FIELD_FONT__": str(metrics["field_font_css"]),
        "__BUTTON_FONT__": str(metrics["button_font_css"]),
        "__BUTTON_MIN_WIDTH__": str(metrics["button_min_width"]),
    }
    for token, value in replacements.items():
        stylesheet = stylesheet.replace(token, value)
    return stylesheet


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


@lru_cache(maxsize=256)
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


def control_system_volume(action: str):
    action = action.upper().strip()

    wpctl = shutil.which("wpctl")
    if wpctl:
        if action == "VOLUME_UP":
            result = subprocess.run(
                [wpctl, "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "5%+"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
        elif action == "VOLUME_DOWN":
            result = subprocess.run(
                [wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
        elif action == "MUTE":
            result = subprocess.run(
                [wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True

    pactl = shutil.which("pactl")
    if pactl:
        if action == "VOLUME_UP":
            result = subprocess.run(
                [pactl, "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
        elif action == "VOLUME_DOWN":
            result = subprocess.run(
                [pactl, "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
        elif action == "MUTE":
            result = subprocess.run(
                [pactl, "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True

    amixer = shutil.which("amixer")
    if amixer:
        if action == "VOLUME_UP":
            result = subprocess.run([amixer, "set", "Master", "5%+"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                return True
        elif action == "VOLUME_DOWN":
            result = subprocess.run([amixer, "set", "Master", "5%-"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                return True
        elif action == "MUTE":
            result = subprocess.run([amixer, "set", "Master", "toggle"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                return True

    logging.warning("No supported volume backend succeeded for action %s", action)
    return False


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
        "SLEEP": ["systemctl", "suspend"],
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
        
        # If no authentication required, send apps list immediately
        if authenticated:
            apps_list = self.window.get_installed_apps()
            await websocket.send(json.dumps({
                "status": "ok",
                "type": "apps_list",
                "apps": apps_list
            }))
        
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
                        # Automatically send apps list after successful authentication
                        apps_list = self.window.get_installed_apps()
                        await websocket.send(json.dumps({
                            "status": "ok",
                            "type": "apps_list",
                            "apps": apps_list
                        }))
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

                # Handle app listing request
                if message_type == "get_apps" or str(payload.get("action", "")).upper() == "GET_APPS":
                    apps_list = self.window.get_installed_apps()
                    await websocket.send(json.dumps({
                        "status": "ok",
                        "type": "apps_list",
                        "apps": apps_list
                    }))
                    continue

                # Handle add app request
                if message_type == "add_app":
                    app_kind = str(payload.get("kind", ""))
                    app_name = str(payload.get("name", "")).strip()
                    
                    if not app_name:
                        await websocket.send(json.dumps({"status": "error", "error": "app name required"}))
                        continue
                    
                    if app_kind == "native":
                        app_command = str(payload.get("command", "")).strip()
                        if not app_command:
                            await websocket.send(json.dumps({"status": "error", "error": "command required for native app"}))
                            continue
                        
                        self.window.add_native_app(app_name, app_command)
                        logging.info("Added native app: %s (%s)", app_name, app_command)
                        
                    elif app_kind == "web":
                        app_url = str(payload.get("url", "")).strip()
                        if not app_url:
                            await websocket.send(json.dumps({"status": "error", "error": "url required for web app"}))
                            continue
                        
                        self.window.add_web_app(app_name, app_url)
                        logging.info("Added web app: %s (%s)", app_name, app_url)
                    
                    await websocket.send(json.dumps({"status": "ok", "type": "app_added"}))
                    continue

                # Handle remove app request
                if message_type == "remove_app":
                    app_id = str(payload.get("id", "")).strip()
                    
                    if not app_id:
                        await websocket.send(json.dumps({"status": "error", "error": "app id required"}))
                        continue
                    
                    self.window.remove_app_by_id(app_id)
                    logging.info("Removed app: %s", app_id)
                    
                    await websocket.send(json.dumps({"status": "ok", "type": "app_removed"}))
                    continue

                # Handle app launch request
                action = str(payload.get("action", ""))
                if action.startswith("LAUNCH_APP:"):
                    app_id = action.replace("LAUNCH_APP:", "")
                    logging.info("Launching app from remote: %s", app_id)
                    self.window.launch_app_by_id(app_id)
                    await websocket.send(json.dumps({"status": "ok", "action": "launch_app", "app_id": app_id}))
                    continue

                action = action.upper()
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
    SHELL_PADDING_X = 14
    SHELL_PADDING_Y = 14

    def __init__(self, name: str, icon_path: str, tooltip: str = "", variant: str = "default", subtitle: str = "", metrics=None):
        button_text = name if not subtitle else f"{name}\n{subtitle}"
        super().__init__(button_text)
        metrics = metrics or {}
        self.variant = variant
        self.title = name
        self.subtitle = subtitle
        tile_width = int(metrics.get("tile_width", 400))
        tile_height = int(metrics.get("tile_height", 230))
        tile_font = int(metrics.get("tile_font_size", 19))
        tile_icon = int(metrics.get("tile_icon_size", 130))
        self.base_size = QSize(tile_width, tile_height)
        self.shell_size = QSize(
            self.base_size.width() + (self.SHELL_PADDING_X * 2),
            self.base_size.height() + (self.SHELL_PADDING_Y * 2),
        )
        self._rest_rect = QRect(
            self.SHELL_PADDING_X,
            self.SHELL_PADDING_Y,
            self.base_size.width(),
            self.base_size.height(),
        )
        self._focus_rect = QRect(0, 0, self.shell_size.width(), self.shell_size.height())
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.card_shell = None
        self.row_scroll = None
        self.section_widget = None
        self.entry_kind = ""
        self.entry_item = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMinimumSize(self.base_size)
        self.setMaximumSize(self.shell_size)
        self.setFont(QFont("Sans Serif", tile_font, QFont.Bold))
        self.setIconSize(QSize(tile_icon, tile_icon))
        self.set_tile_icon(icon_path)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("tileVariant", variant)
        self.setProperty("hasSubtitle", "true" if subtitle else "false")
        self.setStyleSheet("")
        self.setGeometry(self._rest_rect)

    def set_tile_icon(self, icon_path: str):
        if not icon_path:
            self.setIcon(QIcon())
            return

        path = resource_path(icon_path)
        if not path.exists():
            path = Path(icon_path).expanduser()
        if path.exists():
            self.setIcon(QIcon(str(path)))

    def update_geometry_targets(self, shell_rect: QRect):
        self._focus_rect = QRect(0, 0, shell_rect.width(), shell_rect.height())
        self._rest_rect = shell_rect.adjusted(
            self.SHELL_PADDING_X,
            self.SHELL_PADDING_Y,
            -self.SHELL_PADDING_X,
            -self.SHELL_PADDING_Y,
        )
        self._anim.stop()
        self.setGeometry(self._focus_rect if self.hasFocus() else self._rest_rect)

    def animate_focus(self, focused: bool):
        end_rect = self._focus_rect if focused else self._rest_rect
        if self.geometry() == end_rect:
            return
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(end_rect)
        self._anim.start()
        if focused and self.parentWidget():
            self.parentWidget().raise_()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.animate_focus(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.animate_focus(False)


class AppCard(QWidget):
    def __init__(self, tile_button: TileButton, edit_callback=None, delete_callback=None, show_actions: bool = True, metrics=None):
        super().__init__()
        metrics = metrics or {}
        action_button_size = int(metrics.get("action_button_size", 44))
        self.setObjectName("appCardShell")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(tile_button.shell_size)

        self.tile_button = tile_button
        self.tile_button.setParent(self)
        self.tile_button.update_geometry_targets(self.rect())

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
            self.edit_button.setFixedSize(action_button_size, action_button_size)

            self.delete_button = QToolButton(self)
            self.delete_button.setObjectName("deleteButton")
            self.delete_button.setText("✕")
            self.delete_button.setToolTip("Delete this app")
            self.delete_button.clicked.connect(delete_callback)
            self.delete_button.setCursor(Qt.PointingHandCursor)
            self.delete_button.setFocusPolicy(Qt.NoFocus)
            self.delete_button.setFixedSize(action_button_size, action_button_size)

    def sizeHint(self):
        return self.tile_button.shell_size

    def minimumSizeHint(self):
        return self.tile_button.shell_size

    def resizeEvent(self, event):
        self.tile_button.update_geometry_targets(self.rect())
        if self.edit_button is not None:
            self.edit_button.move(self.width() - self.edit_button.width() - 16, 16)
        if self.delete_button is not None:
            self.delete_button.move(self.width() - self.delete_button.width() - 16, 68)
        super().resizeEvent(event)


class IconUpdateBridge(QObject):
    icon_ready = Signal(int, object, str)


class AddItemDialog(QDialog):
    def __init__(self, parent=None, title_text="Add To Apps", type_text="Application", name_text="", value_text="", allow_type_change=True):
        super().__init__(parent)
        metrics = dialog_metrics()
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setFixedWidth(metrics["add_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(metrics["dialog_margin_x"], metrics["dialog_margin_y"], metrics["dialog_margin_x"], metrics["dialog_margin_y"])
        layout.setSpacing(metrics["dialog_spacing"])

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", metrics["title_font"], QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Create a launcher for an installed app command or a website.")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        layout.addWidget(subtitle)

        type_label = QLabel("Type")
        type_label.setObjectName("dialogFieldLabel")
        layout.addWidget(type_label)

        self.type_select = QComboBox()
        self.type_select.setMinimumHeight(metrics["input_min_height"])
        self.type_select.addItems(["Application", "Website"])
        layout.addWidget(self.type_select)

        name_label = QLabel("Name")
        name_label.setObjectName("dialogFieldLabel")
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setMinimumHeight(metrics["input_min_height"])
        self.name_input.setPlaceholderText("Spotify, YouTube, Kodi...")
        layout.addWidget(self.name_input)

        self.value_label = QLabel("Launch command")
        self.value_label.setObjectName("dialogFieldLabel")
        layout.addWidget(self.value_label)

        self.value_input = QLineEdit()
        self.value_input.setMinimumHeight(metrics["input_min_height"])
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

        self.setStyleSheet(dialog_stylesheet(metrics))

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
        metrics = dialog_metrics()
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setFixedWidth(metrics["confirm_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(metrics["dialog_margin_x"], metrics["dialog_margin_y"], metrics["dialog_margin_x"], metrics["dialog_margin_y"])
        layout.setSpacing(metrics["dialog_spacing"])

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", metrics["title_font"], QFont.Bold))
        layout.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("dialogSubtitle")
        body.setWordWrap(True)
        body.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
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

        self.setStyleSheet(dialog_stylesheet(metrics))


class SettingsDialog(QDialog):
    wifi_scan_finished = Signal(object, str, str)

    def __init__(
        self,
        username_text="",
        auto_launch=None,
        app_options=None,
        wifi_networks=None,
        current_wifi="",
        wifi_refresh_callback=None,
        wifi_connect_callback=None,
        update_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        metrics = dialog_metrics()
        self.setWindowTitle("LinuxTV Settings")
        self.setModal(True)
        self.setFixedWidth(metrics["settings_width"])
        self.setFixedHeight(metrics["settings_height"])

        auto_launch = auto_launch or {}
        app_options = app_options or []
        wifi_networks = wifi_networks or []
        self.wifi_refresh_callback = wifi_refresh_callback
        self.wifi_connect_callback = wifi_connect_callback
        self.update_callback = update_callback
        self._wifi_scan_in_progress = False
        self._wifi_has_loaded = bool(wifi_networks or current_wifi)
        self.wifi_scan_finished.connect(self.handle_wifi_scan_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(metrics["dialog_margin_x"] + 2, metrics["dialog_margin_y"] + 2, metrics["dialog_margin_x"] + 2, metrics["dialog_margin_y"] + 2)
        layout.setSpacing(metrics["dialog_spacing"])
        self.section_buttons = {}
        self.section_panels = {}

        title = QLabel("Settings")
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Sans Serif", metrics["title_font"], QFont.Bold))
        layout.addWidget(title)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(metrics["nav_spacing"])
        for section_id, label in (
            ("auto", "Auto Open"),
            ("remote", "Remote Login"),
            ("wifi", "Wi-Fi"),
            ("update", "Update"),
        ):
            button = QPushButton(label)
            button.setProperty("tileVariant", "dialogSecondary")
            button.setProperty("sectionNav", "true")
            button.clicked.connect(lambda checked=False, current=section_id: self.show_section(current))
            nav_row.addWidget(button)
            self.section_buttons[section_id] = button
        layout.addLayout(nav_row)

        self.content_host = QWidget()
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 6, 0, 0)
        self.content_layout.setSpacing(0)
        layout.addWidget(self.content_host, 1)

        auto_panel = QWidget()
        auto_layout = QVBoxLayout(auto_panel)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(metrics["dialog_spacing"])

        auto_title = QLabel("Auto Open")
        auto_title.setObjectName("dialogSection")
        auto_title.setFont(QFont("Sans Serif", metrics["section_font"], QFont.Bold))
        auto_layout.addWidget(auto_title)

        auto_subtitle = QLabel("Choose which app or site opens automatically after LinuxTV sits idle.")
        auto_subtitle.setObjectName("dialogSubtitle")
        auto_subtitle.setWordWrap(True)
        auto_subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        auto_layout.addWidget(auto_subtitle)

        self.auto_launch_combo = QComboBox()
        self.auto_launch_combo.setMinimumHeight(metrics["input_min_height"])
        self._style_settings_combo_popup(self.auto_launch_combo)
        self.auto_launch_combo.addItem("Disabled", ("", ""))
        selected_kind = str(auto_launch.get("app_kind", "")).strip()
        selected_target = str(auto_launch.get("app_target", "")).strip()
        selected_index = 0
        for index, option in enumerate(app_options, start=1):
            self.auto_launch_combo.addItem(option["label"], (option["kind"], option["target"]))
            if option["kind"] == selected_kind and option["target"] == selected_target:
                selected_index = index
        self.auto_launch_combo.setCurrentIndex(selected_index)
        auto_layout.addWidget(self.auto_launch_combo)

        self.delay_input = QLineEdit()
        self.delay_input.setPlaceholderText("Idle delay in seconds")
        self.delay_input.setText(str(auto_launch.get("delay_seconds", AUTO_LAUNCH_IDLE_MS // 1000)))
        self.delay_input.setMinimumHeight(metrics["input_min_height"])
        auto_layout.addWidget(self.delay_input)

        auto_helper = QLabel("Pick Disabled to turn auto open off. Enter a whole number of seconds.")
        auto_helper.setObjectName("dialogSubtitle")
        auto_helper.setWordWrap(True)
        auto_helper.setFont(QFont("Sans Serif", metrics["helper_font"]))
        auto_layout.addWidget(auto_helper)

        remote_panel = QWidget()
        remote_layout = QVBoxLayout(remote_panel)
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.setSpacing(metrics["dialog_spacing"])

        remote_title = QLabel("Remote Login")
        remote_title.setObjectName("dialogSection")
        remote_title.setFont(QFont("Sans Serif", metrics["section_font"], QFont.Bold))
        remote_layout.addWidget(remote_title)

        subtitle = QLabel("Set the phone credentials required to control LinuxTV.")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        remote_layout.addWidget(subtitle)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setText(username_text)
        self.username_input.setMinimumHeight(metrics["input_min_height"])
        remote_layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(metrics["input_min_height"])
        remote_layout.addWidget(self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Confirm password")
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.setMinimumHeight(metrics["input_min_height"])
        remote_layout.addWidget(self.confirm_input)

        helper = QLabel("Leave all three fields empty to disable phone authentication.")
        helper.setObjectName("dialogSubtitle")
        helper.setWordWrap(True)
        helper.setFont(QFont("Sans Serif", metrics["helper_font"]))
        remote_layout.addWidget(helper)

        wifi_panel = QWidget()
        wifi_layout = QVBoxLayout(wifi_panel)
        wifi_layout.setContentsMargins(0, 0, 0, 0)
        wifi_layout.setSpacing(metrics["dialog_spacing"])

        wifi_title = QLabel("Wi-Fi")
        wifi_title.setObjectName("dialogSection")
        wifi_title.setFont(QFont("Sans Serif", metrics["section_font"], QFont.Bold))
        wifi_layout.addWidget(wifi_title)

        wifi_subtitle = QLabel("Scan for nearby networks, enter a password if needed, and connect without leaving LinuxTV.")
        wifi_subtitle.setObjectName("dialogSubtitle")
        wifi_subtitle.setWordWrap(True)
        wifi_subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        wifi_layout.addWidget(wifi_subtitle)

        self.wifi_combo = QComboBox()
        self.wifi_combo.setEditable(True)
        self.wifi_combo.setMinimumHeight(metrics["input_min_height"] + 2)
        self._style_settings_combo_popup(self.wifi_combo)
        self.wifi_combo.lineEdit().setPlaceholderText("Select or type a Wi-Fi network name")
        wifi_layout.addWidget(self.wifi_combo)

        self.wifi_password_input = QLineEdit()
        self.wifi_password_input.setPlaceholderText("Wi-Fi password")
        self.wifi_password_input.setEchoMode(QLineEdit.Password)
        self.wifi_password_input.setMinimumHeight(metrics["input_min_height"] + 2)
        wifi_layout.addWidget(self.wifi_password_input)

        wifi_button_row = QHBoxLayout()
        self.refresh_wifi_button = QPushButton("Refresh Networks")
        self.refresh_wifi_button.setProperty("tileVariant", "dialogSecondary")
        self.refresh_wifi_button.clicked.connect(self.refresh_wifi_networks)
        wifi_button_row.addWidget(self.refresh_wifi_button)

        self.connect_wifi_button = QPushButton("Connect Wi-Fi")
        self.connect_wifi_button.setProperty("tileVariant", "accent")
        self.connect_wifi_button.clicked.connect(self.connect_wifi)
        wifi_button_row.addWidget(self.connect_wifi_button)
        wifi_layout.addLayout(wifi_button_row)

        self.wifi_status_label = QLabel("")
        self.wifi_status_label.setObjectName("dialogStatus")
        self.wifi_status_label.setWordWrap(True)
        wifi_layout.addWidget(self.wifi_status_label)

        update_panel = QWidget()
        update_layout = QVBoxLayout(update_panel)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.setSpacing(metrics["dialog_spacing"])

        update_title = QLabel("Update LinuxTV")
        update_title.setObjectName("dialogSection")
        update_title.setFont(QFont("Sans Serif", metrics["section_font"], QFont.Bold))
        update_layout.addWidget(update_title)

        update_subtitle = QLabel("Pull the latest LinuxTV changes from GitHub and sync them into this device.")
        update_subtitle.setObjectName("dialogSubtitle")
        update_subtitle.setWordWrap(True)
        update_subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        update_layout.addWidget(update_subtitle)

        update_button = QPushButton("Update From GitHub")
        update_button.setProperty("tileVariant", "accent")
        update_button.clicked.connect(self.run_update_action)
        update_layout.addWidget(update_button)

        self.update_status_label = QLabel("")
        self.update_status_label.setObjectName("dialogStatus")
        self.update_status_label.setWordWrap(True)
        update_layout.addWidget(self.update_status_label)

        for section_id, panel in (
            ("auto", auto_panel),
            ("remote", remote_panel),
            ("wifi", wifi_panel),
            ("update", update_panel),
        ):
            self.section_panels[section_id] = panel
            self.content_layout.addWidget(panel)

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
        self.set_wifi_networks(wifi_networks, current_wifi)
        self.set_wifi_loading_state(False)
        if not self._wifi_has_loaded and self.wifi_refresh_callback:
            self.wifi_status_label.setText("Open this section to fetch nearby Wi-Fi networks.")
        self.setStyleSheet(dialog_stylesheet(metrics))
        self.show_section("auto")

    def _style_settings_combo_popup(self, combo: QComboBox):
        popup = combo.view()
        if popup is None:
            return
        popup.setStyleSheet(
            """
            background-color: #141a21;
            color: #edf2f7;
            border: 1px solid #2b3641;
            selection-background-color: #33c3a0;
            selection-color: #09110f;
            alternate-background-color: #10161d;
            """
        )

    def show_section(self, section_id: str):
        for key, panel in self.section_panels.items():
            panel.setVisible(key == section_id)
        for key, button in self.section_buttons.items():
            button.setProperty("tileVariant", "accent" if key == section_id else "dialogSecondary")
            button.style().unpolish(button)
            button.style().polish(button)
        if section_id == "wifi":
            QTimer.singleShot(0, self.ensure_wifi_networks_loaded)

    def set_wifi_loading_state(self, loading: bool, message=""):
        self._wifi_scan_in_progress = loading
        self.refresh_wifi_button.setEnabled(not loading and bool(self.wifi_refresh_callback))
        self.connect_wifi_button.setEnabled(not loading and bool(self.wifi_connect_callback))
        if loading and message:
            self.wifi_status_label.setText(message)

    def ensure_wifi_networks_loaded(self, force=False):
        if not self.wifi_refresh_callback:
            self.set_wifi_loading_state(False)
            self.wifi_status_label.setText("Wi-Fi scanning is not available on this system.")
            return
        if self._wifi_scan_in_progress:
            return
        if self._wifi_has_loaded and not force:
            return
        status_text = "Refreshing Wi-Fi networks..." if force else "Fetching nearby Wi-Fi networks..."
        self.set_wifi_loading_state(True, status_text)
        threading.Thread(
            target=self._run_wifi_scan,
            name="wifi-settings-scan",
            daemon=True,
        ).start()

    def _run_wifi_scan(self):
        try:
            networks, current_wifi, message = self.wifi_refresh_callback()
        except Exception as exc:
            logging.exception("Failed to refresh Wi-Fi networks from settings")
            networks, current_wifi, message = [], "", f"Could not scan for Wi-Fi networks: {exc}"
        self.wifi_scan_finished.emit(networks, current_wifi, message)

    def handle_wifi_scan_finished(self, wifi_networks, current_wifi, message):
        self.set_wifi_loading_state(False)
        self._wifi_has_loaded = True
        self.set_wifi_networks(wifi_networks or [], current_wifi)
        if message:
            self.wifi_status_label.setText(message)

    def set_wifi_networks(self, wifi_networks, current_wifi=""):
        current_text = self.wifi_combo.currentText().strip()
        self.wifi_combo.blockSignals(True)
        self.wifi_combo.clear()
        selected_index = -1
        for index, option in enumerate(wifi_networks):
            label = option.get("label", option.get("ssid", ""))
            ssid = option.get("ssid", "")
            self.wifi_combo.addItem(label, dict(option))
            if current_wifi and ssid == current_wifi:
                selected_index = index
        self.wifi_combo.blockSignals(False)

        if selected_index >= 0:
            self.wifi_combo.setCurrentIndex(selected_index)
            self.wifi_status_label.setText(f"Connected network: {current_wifi}")
            return

        if current_text:
            self.wifi_combo.setEditText(current_text)
        elif current_wifi:
            self.wifi_combo.setEditText(current_wifi)
            self.wifi_status_label.setText(f"Connected network: {current_wifi}")
        elif wifi_networks:
            self.wifi_combo.setCurrentIndex(0)
            self.wifi_status_label.setText("Choose a network and connect from here.")
        else:
            self.wifi_combo.setEditText("")
            self.wifi_status_label.setText("No Wi-Fi networks loaded yet. Open or refresh this section to scan.")

    def refresh_wifi_networks(self):
        self.ensure_wifi_networks_loaded(force=True)

    def connect_wifi(self):
        if self._wifi_scan_in_progress:
            self.wifi_status_label.setText("Still fetching nearby Wi-Fi networks. Try again in a moment.")
            return
        if not self.wifi_connect_callback:
            self.wifi_status_label.setText("Wi-Fi connection is not available on this system.")
            return
        selected_network = self.wifi_combo.currentData()
        if not isinstance(selected_network, dict):
            selected_network = {"ssid": self.wifi_combo.currentText().strip(), "security": ""}
        password = self.wifi_password_input.text()
        success, message, current_wifi = self.wifi_connect_callback(selected_network, password)
        if current_wifi:
            self.refresh_wifi_networks()
        self.wifi_status_label.setText(message)
        if success:
            self.wifi_password_input.clear()

    def run_update_action(self):
        if not self.update_callback:
            self.update_status_label.setText("Updater is not available on this system.")
            return
        success, message = self.update_callback()
        self.update_status_label.setText(message)

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
        self.tile_rows = []
        self.current_index = 0
        self.current_row = 0
        self.current_col = 0
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
        self._icon_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="icon-loader")
        self._icon_request_token = 0
        self._icon_bridge = IconUpdateBridge()
        self._icon_bridge.icon_ready.connect(self._apply_resolved_icon)
        self._scroll_anim = None
        self._row_scroll_anim = None

        self.process_monitor = QTimer(self)
        self.process_monitor.setInterval(500)
        self.process_monitor.timeout.connect(self.check_active_process)

        self.remote_action_timer = QTimer(self)
        self.remote_action_timer.setInterval(16)
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
        QTimer.singleShot(1500, self.start_startup_time_sync)
        QTimer.singleShot(15000, self.start_startup_time_sync)

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

    def start_startup_time_sync(self):
        threading.Thread(
            target=self._run_startup_time_sync,
            name="startup-time-sync",
            daemon=True,
        ).start()

    def _run_startup_time_sync(self):
        success, message = sync_system_time()
        if success:
            logging.info("Startup time sync: %s", message)
        else:
            logging.warning("Startup time sync failed: %s", message)

    def compute_ui_metrics(self):
        geometry = self.get_target_geometry()
        width = max(geometry.width(), 1280)
        height = max(geometry.height(), 720)
        compact = width <= 1600 or height <= 950
        if compact:
            return {
                "compact": True,
                "main_margin_x": 24,
                "main_margin_top": 20,
                "main_margin_bottom": 20,
                "main_spacing": 14,
                "hero_margin_x": 22,
                "hero_margin_y": 18,
                "hero_spacing": 6,
                "hero_title_font": 28,
                "hero_title_css": 28,
                "settings_button_size": 40,
                "settings_button_font": 16,
                "section_heading_font": 18,
                "footer_font": 12,
                "status_font": 12,
                "tile_stack_spacing": 14,
                "row_label_css": 18,
                "row_scroll_height": 212,
                "row_content_margin_x": 8,
                "row_content_margin_y": 6,
                "row_content_spacing": 18,
                "tile_width": 280,
                "tile_height": 152,
                "tile_font_size": 14,
                "tile_icon_size": 72,
                "tile_font_css": 14,
                "tile_padding_lr": 20,
                "tile_padding_top": 22,
                "tile_padding_bottom": 18,
                "tile_padding_top_subtitle": 14,
                "tile_padding_bottom_subtitle": 14,
                "action_button_size": 36,
                "action_button_font_css": 14,
                "footer_padding_y": 6,
                "cancel_button_min_width": 132,
            }
        return {
            "compact": False,
            "main_margin_x": 48,
            "main_margin_top": 40,
            "main_margin_bottom": 32,
            "main_spacing": 20,
            "hero_margin_x": 32,
            "hero_margin_y": 24,
            "hero_spacing": 8,
            "hero_title_font": 42,
            "hero_title_css": 36,
            "settings_button_size": 48,
            "settings_button_font": 20,
            "section_heading_font": 24,
            "footer_font": 15,
            "status_font": 14,
            "tile_stack_spacing": 22,
            "row_label_css": 24,
            "row_scroll_height": 290,
            "row_content_margin_x": 12,
            "row_content_margin_y": 8,
            "row_content_spacing": 28,
            "tile_width": 400,
            "tile_height": 230,
            "tile_font_size": 19,
            "tile_icon_size": 130,
            "tile_font_css": 18,
            "tile_padding_lr": 32,
            "tile_padding_top": 40,
            "tile_padding_bottom": 28,
            "tile_padding_top_subtitle": 18,
            "tile_padding_bottom_subtitle": 18,
            "action_button_size": 44,
            "action_button_font_css": 18,
            "footer_padding_y": 12,
            "cancel_button_min_width": 160,
        }

    def showEvent(self, event):
        super().showEvent(event)
        # Delay the reset until the window is actually visible so auto-open
        # also starts on a fresh system boot.
        QTimer.singleShot(0, self.reset_auto_launch_timer)

    def setup_ui(self):
        self.ui_metrics = self.compute_ui_metrics()
        central = QWidget()
        central.setObjectName("centralShell")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(
            self.ui_metrics["main_margin_x"],
            self.ui_metrics["main_margin_top"],
            self.ui_metrics["main_margin_x"],
            self.ui_metrics["main_margin_bottom"],
        )
        main_layout.setSpacing(self.ui_metrics["main_spacing"])

        hero = QWidget()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(
            self.ui_metrics["hero_margin_x"],
            self.ui_metrics["hero_margin_y"],
            self.ui_metrics["hero_margin_x"],
            self.ui_metrics["hero_margin_y"],
        )
        hero_layout.setSpacing(self.ui_metrics["hero_spacing"])

        hero_top_row = QHBoxLayout()
        hero_top_row.setContentsMargins(0, 0, 0, 0)
        hero_top_row.setSpacing(16)

        hero_top_row.addStretch(1)
        title = QLabel("LinuxTV")
        title.setObjectName("heroTitle")
        title.setFont(QFont("Sans Serif", self.ui_metrics["hero_title_font"], QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        hero_top_row.addWidget(title)
        hero_top_row.addStretch(1)

        settings_button = QToolButton()
        settings_button.setObjectName("settingsButton")
        settings_button.setText("⚙")
        settings_button.setToolTip("Open LinuxTV settings")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.setFixedSize(self.ui_metrics["settings_button_size"], self.ui_metrics["settings_button_size"])
        settings_button.setFont(QFont("Sans Serif", self.ui_metrics["settings_button_font"]))
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
        self.tile_stack = QVBoxLayout(container)
        self.tile_stack.setContentsMargins(8, 8, 8, 8)
        self.tile_stack.setSpacing(self.ui_metrics["tile_stack_spacing"])
        self.tile_stack.setAlignment(Qt.AlignTop)

        self.populate_tiles()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        footer = QLabel("Navigate with arrows • Select with Enter • Add apps with the Add App tile • Exit with Esc")
        footer.setObjectName("footerHint")
        footer.setWordWrap(True)
        footer.setFont(QFont("Sans Serif", self.ui_metrics["footer_font"]))
        footer.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(footer)

        auto_launch_status_row = QHBoxLayout()
        auto_launch_status_row.setContentsMargins(0, 0, 0, 0)
        auto_launch_status_row.setSpacing(12)
        auto_launch_status_row.addStretch(1)

        self.auto_launch_status_label = QLabel("")
        self.auto_launch_status_label.setObjectName("autoLaunchStatus")
        self.auto_launch_status_label.setWordWrap(True)
        self.auto_launch_status_label.setFont(QFont("Sans Serif", self.ui_metrics["status_font"]))
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
        # Install event filter to capture wheel events for touchpad scrolling
        central.installEventFilter(self)
        self.apply_theme()

        if self.tiles:
            self.focus_first_tile()
        self.reset_auto_launch_timer()

    def apply_theme(self):
        m = self.ui_metrics
        stylesheet = """
            QMainWindow {
                background: #0d0d0d;
            }
            QWidget#centralShell {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0a0a, stop:0.5 #111111, stop:1 #0d0d0d);
                color: #f5f5f5;
            }
            QWidget#heroCard {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a1a, stop:0.5 #222222, stop:1 #1a1a1a);
                border: 1px solid #333333;
                border-radius: 16px;
            }
            QToolButton#settingsButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a2a, stop:1 #1f1f1f);
                color: #e0e0e0;
                border: 1px solid #444444;
                border-radius: __SETTINGS_RADIUS__px;
                font-size: __SETTINGS_FONT__px;
                padding-bottom: 1px;
            }
            QToolButton#settingsButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e53935, stop:1 #c62828);
                border: 1px solid #ff5252;
                color: #ffffff;
            }
            QToolButton#settingsButton:pressed {
                background-color: #b71c1c;
                border: 1px solid #e53935;
            }
            QLabel#heroTitle {
                color: #ffffff;
                font-weight: bold;
                letter-spacing: 1px;
                font-size: __HERO_TITLE__px;
            }
            QScrollArea#tileScroll, QWidget#tileContainer {
                background: transparent;
                border: none;
            }
            QWidget[rowSection="true"] {
                background: transparent;
            }
            QLabel[rowHeading="true"] {
                color: #ffffff;
                font-size: __ROW_HEADING__px;
                font-weight: bold;
                padding: 12px 8px 8px 8px;
                letter-spacing: 0.5px;
            }
            QScrollArea[rowScroll="true"] {
                background: transparent;
                border: none;
            }
            QWidget[rowContent="true"] {
                background: transparent;
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
                    stop:0 #1e1e1e, stop:1 #151515);
                color: #e8e8e8;
                border: 2px solid #333333;
                border-radius: 16px;
                padding: __TILE_PADDING_BOTTOM__px __TILE_PADDING_LR__px;
                padding-left: __TILE_PADDING_LR__px;
                padding-right: __TILE_PADDING_LR__px;
                padding-top: __TILE_PADDING_TOP__px;
                padding-bottom: __TILE_PADDING_BOTTOM__px;
                text-align: left;
                font-size: __TILE_FONT__px;
                font-weight: 500;
            }
            QPushButton[tileVariant="default"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a2a, stop:1 #1e1e1e);
                border: 2px solid #e53935;
            }
            QPushButton[tileVariant="default"]:focus {
                border: 3px solid #ff5252;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e53935, stop:1 #c62828);
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton[tileVariant="accent"] {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e53935, stop:1 #c62828);
                color: #ffffff;
                border: 2px solid #ff5252;
                border-radius: 16px;
                padding: __TILE_PADDING_BOTTOM__px __TILE_PADDING_LR__px;
                padding-left: __TILE_PADDING_LR__px;
                padding-right: __TILE_PADDING_LR__px;
                padding-top: __TILE_PADDING_TOP__px;
                padding-bottom: __TILE_PADDING_BOTTOM__px;
                text-align: left;
                font-size: __TILE_FONT__px;
                font-weight: 600;
            }
            QPushButton[tileVariant="accent"]:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff5252, stop:1 #e53935);
                border: 2px solid #ff867f;
            }
            QPushButton[tileVariant="accent"]:focus {
                border: 3px solid #ffffff;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff5252, stop:1 #e53935);
            }
            QWidget#appCardShell {
                background: transparent;
            }
            QToolButton#editButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a2a, stop:1 #1f1f1f);
                color: #bdbdbd;
                border: 1px solid #444444;
                border-radius: 16px;
                font-size: 18px;
                padding-bottom: 2px;
            }
            QToolButton#editButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3a3a3a, stop:1 #2a2a2a);
                color: #ffffff;
                border: 1px solid #e53935;
            }
            QToolButton#editButton:pressed {
                background-color: #1f1f1f;
                border: 1px solid #ff5252;
            }
            QToolButton#deleteButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d1a1a, stop:1 #2d1212);
                color: #ff5252;
                border: 1px solid #c62828;
                border-radius: 16px;
                font-size: 18px;
            }
            QToolButton#deleteButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4d2424, stop:1 #3d1a1a);
                border: 1px solid #ff5252;
            }
            QToolButton#deleteButton:pressed {
                background-color: #2d1212;
                border: 1px solid #e53935;
            }
            QPushButton[hasSubtitle="true"] {
                padding-top: __TILE_SUBTITLE_TOP__px;
                padding-bottom: __TILE_SUBTITLE_BOTTOM__px;
            }
            QLabel#footerHint {
                color: #9e9e9e;
                padding: __FOOTER_PADDING_Y__px 20px;
                font-size: __FOOTER_FONT__px;
                letter-spacing: 0.3px;
            }
            QLabel#autoLaunchStatus {
                color: #ff5252;
                padding: 0 20px 12px 20px;
                font-size: __STATUS_FONT__px;
                font-weight: 500;
            }
            QPushButton#autoLaunchCancelButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a2a, stop:1 #1f1f1f);
                color: #e0e0e0;
                border: 1px solid #444444;
                border-radius: 16px;
                padding: 12px 20px;
                min-width: __CANCEL_WIDTH__px;
                font-size: __STATUS_FONT__px;
                font-weight: 500;
            }
            QPushButton#autoLaunchCancelButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e53935, stop:1 #c62828);
                border: 1px solid #ff5252;
                color: #ffffff;
            }
            QPushButton#autoLaunchCancelButton:pressed {
                background-color: #b71c1c;
                border: 1px solid #e53935;
            }
            """
        replacements = {
            "__SETTINGS_RADIUS__": str(max(14, m["settings_button_size"] // 2 - 4)),
            "__SETTINGS_FONT__": str(max(14, m["settings_button_font"])),
            "__HERO_TITLE__": str(m["hero_title_css"]),
            "__ROW_HEADING__": str(m["row_label_css"]),
            "__TILE_PADDING_BOTTOM__": str(m["tile_padding_bottom"]),
            "__TILE_PADDING_LR__": str(m["tile_padding_lr"]),
            "__TILE_PADDING_TOP__": str(m["tile_padding_top"]),
            "__TILE_FONT__": str(m["tile_font_css"]),
            "__TILE_SUBTITLE_TOP__": str(m["tile_padding_top_subtitle"]),
            "__TILE_SUBTITLE_BOTTOM__": str(m["tile_padding_bottom_subtitle"]),
            "__FOOTER_PADDING_Y__": str(m["footer_padding_y"]),
            "__FOOTER_FONT__": str(m["footer_font"]),
            "__STATUS_FONT__": str(m["status_font"]),
            "__CANCEL_WIDTH__": str(m["cancel_button_min_width"]),
        }
        for token, value in replacements.items():
            stylesheet = stylesheet.replace(token, value)
        self.setStyleSheet(stylesheet)

    def clear_tiles(self):
        while self.tile_stack.count():
            item = self.tile_stack.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def populate_tiles(self):
        self.clear_tiles()
        self.tiles = []
        self.tile_rows = []
        self.current_index = 0
        self.current_row = 0
        self.current_col = 0
        self._icon_request_token += 1
        request_token = self._icon_request_token

        categories = self.get_categorized_entries()
        for category_name, entries in categories:
            section = QWidget()
            section.setProperty("rowSection", "true")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(12)

            label = QLabel(category_name)
            label.setProperty("rowHeading", "true")
            section_layout.addWidget(label)

            row_scroll = QScrollArea()
            row_scroll.setProperty("rowScroll", "true")
            row_scroll.setFrameShape(QScrollArea.NoFrame)
            row_scroll.setWidgetResizable(False)
            row_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            row_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            row_scroll.setFixedHeight(self.ui_metrics["row_scroll_height"])

            row_widget = QWidget()
            row_widget.setProperty("rowContent", "true")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(
                self.ui_metrics["row_content_margin_x"],
                self.ui_metrics["row_content_margin_y"],
                self.ui_metrics["row_content_margin_x"],
                self.ui_metrics["row_content_margin_y"],
            )
            row_layout.setSpacing(self.ui_metrics["row_content_spacing"])

            row_tiles = []
            for entry in entries:
                app = entry["item"]
                tile = TileButton(
                    app.get("name", "Untitled"),
                    "",
                    entry["tooltip"],
                    subtitle=entry["subtitle"],
                    metrics=self.ui_metrics,
                )
                tile.entry_kind = entry["kind"]
                tile.entry_item = app
                tile.clicked.connect(lambda checked=False, item=app, kind=entry["kind"]: self.launch_app(item, kind))
                card = AppCard(
                    tile,
                    lambda checked=False, item=app, kind=entry["kind"]: self.prompt_edit_entry(kind, item),
                    lambda checked=False, item=app, kind=entry["kind"]: self.prompt_delete_entry(kind, item),
                    metrics=self.ui_metrics,
                )
                tile.card_shell = card
                tile.row_scroll = row_scroll
                tile.section_widget = section
                row_layout.addWidget(card)
                self.tiles.append(tile)
                row_tiles.append(tile)

                future = self._icon_pool.submit(self._resolve_icon, entry)
                future.add_done_callback(
                    lambda pending, token=request_token, button=tile: self._queue_icon_result(token, button, pending)
                )

            row_layout.addStretch(1)
            row_widget.adjustSize()
            row_scroll.setWidget(row_widget)
            section_layout.addWidget(row_scroll)
            self.tile_stack.addWidget(section)
            if row_tiles:
                self.tile_rows.append(row_tiles)

        add_tile = TileButton(
            "Add App",
            "",
            "Save a new app or site to config.yaml",
            variant="accent",
            subtitle="Add a command or website",
            metrics=self.ui_metrics,
        )
        add_tile.clicked.connect(self.prompt_add_entry)
        add_section = QWidget()
        add_section.setProperty("rowSection", "true")
        add_section_layout = QVBoxLayout(add_section)
        add_section_layout.setContentsMargins(0, 0, 0, 0)
        add_section_layout.setSpacing(12)
        add_label = QLabel("Library")
        add_label.setProperty("rowHeading", "true")
        add_section_layout.addWidget(add_label)
        add_row_scroll = QScrollArea()
        add_row_scroll.setProperty("rowScroll", "true")
        add_row_scroll.setFrameShape(QScrollArea.NoFrame)
        add_row_scroll.setWidgetResizable(False)
        add_row_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        add_row_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        add_row_scroll.setFixedHeight(self.ui_metrics["row_scroll_height"])
        add_row_widget = QWidget()
        add_row_widget.setProperty("rowContent", "true")
        add_row_layout = QHBoxLayout(add_row_widget)
        add_row_layout.setContentsMargins(
            self.ui_metrics["row_content_margin_x"],
            self.ui_metrics["row_content_margin_y"],
            self.ui_metrics["row_content_margin_x"],
            self.ui_metrics["row_content_margin_y"],
        )
        add_row_layout.setSpacing(self.ui_metrics["row_content_spacing"])
        add_card = AppCard(add_tile, show_actions=False, metrics=self.ui_metrics)
        add_tile.card_shell = add_card
        add_tile.row_scroll = add_row_scroll
        add_tile.section_widget = add_section
        add_row_layout.addWidget(add_card)
        add_row_layout.addStretch(1)
        add_row_widget.adjustSize()
        add_row_scroll.setWidget(add_row_widget)
        add_section_layout.addWidget(add_row_scroll)
        self.tile_stack.addWidget(add_section)
        self.tiles.append(add_tile)
        self.tile_rows.append([add_tile])

        self.tile_stack.addStretch(1)

        self.reset_auto_launch_timer()

    def get_categorized_entries(self):
        native_entries = []
        web_entries = []

        for app in self.config.get("native_apps", []):
            if not is_installed(app.get("cmd", "")):
                continue
            subtitle = app.get("cmd", "").split()[0] if app.get("cmd") else "Application"
            native_entries.append({
                "kind": "native",
                "item": app,
                "subtitle": subtitle,
                "tooltip": app.get("cmd", ""),
            })

        for app in self.config.get("web_apps", []):
            url = app.get("url", "")
            subtitle = url.replace("https://", "").replace("http://", "")
            web_entries.append({
                "kind": "web",
                "item": app,
                "subtitle": subtitle,
                "tooltip": url,
            })

        categories = []
        if native_entries:
            categories.append(("Native Apps", native_entries))
        if web_entries:
            categories.append(("Web Apps", web_entries))
        return categories

    def get_installed_apps(self):
        """Get list of installed apps for remote control app listing"""
        apps_list = []
        categories = self.get_categorized_entries()
        
        for category_name, entries in categories:
            for entry in entries:
                item = entry["item"]
                app_id = item.get("id", item.get("name", "")).lower().replace(" ", "_")
                app_name = item.get("name", "Unknown")
                
                # Determine icon based on app type
                icon_name = "application"
                if entry["kind"] == "web":
                    icon_name = "globe"
                
                apps_list.append({
                    "id": app_id,
                    "name": app_name,
                    "kind": entry["kind"],
                    "icon": icon_name,
                    "category": category_name
                })
        
        return apps_list

    def launch_app_by_id(self, app_id):
        """Launch an app by its ID from remote control"""
        categories = self.get_categorized_entries()
        
        for category_name, entries in categories:
            for entry in entries:
                item = entry["item"]
                item_id = item.get("id", item.get("name", "")).lower().replace(" ", "_")
                
                if item_id == app_id:
                    logging.info("Launching app: %s (%s)", app_id, entry["kind"])
                    self.launch_app(item, entry["kind"])
                    return
        
        logging.warning("App not found: %s", app_id)

    def add_native_app(self, name: str, command: str):
        """Add a native app to config and save it"""
        native_apps = self.config.get("native_apps", [])
        native_apps.append({
            "name": name,
            "cmd": command
        })
        self.config["native_apps"] = native_apps
        save_config(self.config_path, self.config)
        
        logging.info("Added native app: %s (%s)", name, command)
        
        # Refresh tiles immediately
        self.populate_tiles()

    def add_web_app(self, name: str, url: str):
        """Add a web app to config and save it"""
        web_apps = self.config.get("web_apps", [])
        web_apps.append({
            "name": name,
            "url": url
        })
        self.config["web_apps"] = web_apps
        save_config(self.config_path, self.config)
        
        logging.info("Added web app: %s (%s)", name, url)
        
        # Refresh tiles immediately
        self.populate_tiles()

    def remove_app_by_id(self, app_id: str):
        """Remove an app by its ID from config"""
        app_id_normalized = app_id.lower().replace(" ", "_")
        
        # Try to remove from native apps
        native_apps = self.config.get("native_apps", [])
        for i, app in enumerate(native_apps):
            item_id = app.get("id", app.get("name", "")).lower().replace(" ", "_")
            if item_id == app_id_normalized:
                app_name = app.get("name")
                native_apps.pop(i)
                self.config["native_apps"] = native_apps
                save_config(self.config_path, self.config)
                logging.info("Removed native app: %s", app_name)
                # Refresh tiles immediately
                self.populate_tiles()
                return
        
        # Try to remove from web apps
        web_apps = self.config.get("web_apps", [])
        for i, app in enumerate(web_apps):
            item_id = app.get("id", app.get("name", "")).lower().replace(" ", "_")
            if item_id == app_id_normalized:
                app_name = app.get("name")
                web_apps.pop(i)
                self.config["web_apps"] = web_apps
                save_config(self.config_path, self.config)
                logging.info("Removed web app: %s", app_name)
                # Refresh tiles immediately
                self.populate_tiles()
                return
        
        logging.warning("App not found for removal: %s", app_id)

    def get_launchable_entries(self):
        entries = []
        for _, category_entries in self.get_categorized_entries():
            entries.extend(category_entries)
        return entries

    def _resolve_icon(self, entry):
        app = entry["item"]
        if entry["kind"] == "native":
            return resolve_native_icon(app)
        return fetch_web_icon(app)

    def _queue_icon_result(self, request_token: int, tile: TileButton, future):
        icon_path = ""
        try:
            icon_path = future.result() or ""
        except Exception:
            logging.exception("Failed to resolve icon for %s", getattr(tile, "title", "tile"))
        self._icon_bridge.icon_ready.emit(request_token, tile, icon_path)

    def _apply_resolved_icon(self, request_token: int, tile: TileButton, icon_path: str):
        if request_token != self._icon_request_token or tile not in self.tiles:
            return
        tile.set_tile_icon(icon_path)

    def _flat_index_for_position(self, row: int, col: int):
        index = 0
        for row_idx, row_tiles in enumerate(self.tile_rows):
            if row_idx == row:
                return index + col
            index += len(row_tiles)
        return 0

    def current_tile(self):
        if not self.tile_rows:
            return None
        row = max(0, min(self.current_row, len(self.tile_rows) - 1))
        col = max(0, min(self.current_col, len(self.tile_rows[row]) - 1))
        return self.tile_rows[row][col]

    def focus_tile_at(self, row: int, col: int):
        if not self.tile_rows:
            return
        row = max(0, min(row, len(self.tile_rows) - 1))
        col = max(0, min(col, len(self.tile_rows[row]) - 1))
        self.current_row = row
        self.current_col = col
        self.current_index = self._flat_index_for_position(row, col)
        self.tile_rows[row][col].setFocus()

    def focus_first_tile(self):
        if not self.tile_rows:
            return
        self.focus_tile_at(0, 0)

    def focus_entry_tile(self, kind: str, item):
        for row_idx, row_tiles in enumerate(self.tile_rows):
            for col_idx, tile in enumerate(row_tiles):
                if tile.entry_kind == kind and tile.entry_item is item:
                    self.focus_tile_at(row_idx, col_idx)
                    return True
        return False

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
            self.focus_first_tile()
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
            self.focus_first_tile()

    def open_remote_settings(self):
        auth = self.config.get("auth", {})
        auto_launch = self.config.get("auto_launch", {})
        dialog = SettingsDialog(
            auth.get("username", ""),
            auto_launch,
            self.get_auto_launch_options(),
            [],
            "",
            self.scan_wifi_networks,
            self.connect_to_wifi,
            self.update_from_github,
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

    def scan_wifi_networks(self):
        nmcli = shutil.which("nmcli")
        if not nmcli:
            return [], "", "NetworkManager tools are not installed. Install `network-manager` to manage Wi-Fi here."

        current_wifi = ""
        try:
            current_result = subprocess.run(
                [nmcli, "--colors", "no", "--terse", "--fields", "NAME,TYPE", "connection", "show", "--active"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if current_result.returncode == 0:
                for line in current_result.stdout.splitlines():
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[1].strip() == "802-11-wireless":
                        current_wifi = parts[0].strip()
                        break
        except Exception:
            logging.exception("Failed to read active Wi-Fi connection")

        try:
            result = subprocess.run(
                [
                    nmcli,
                    "--colors",
                    "no",
                    "--escape",
                    "yes",
                    "--terse",
                    "--fields",
                    "IN-USE,SSID,SIGNAL,SECURITY",
                    "device",
                    "wifi",
                    "list",
                    "--rescan",
                    "yes",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except Exception as exc:
            logging.exception("Failed to scan Wi-Fi networks")
            return [], current_wifi, f"Could not scan for Wi-Fi networks: {exc}"

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Unknown error").strip()
            return [], current_wifi, f"Could not scan for Wi-Fi networks: {message}"

        networks = []
        seen_ssids = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split(":")
            if len(parts) < 4:
                continue

            in_use = parts[0].strip()
            security = parts[-1].strip() or "Open"
            signal_strength = parts[-2].strip() or "?"
            ssid = ":".join(parts[1:-2]).replace("\\:", ":").strip()
            if not ssid or ssid in seen_ssids:
                continue

            active = in_use == "*"
            label = f"{ssid}  |  {signal_strength}%  |  {security}"
            if active:
                label = f"{label}  |  Connected"
            networks.append(
                {
                    "ssid": ssid,
                    "label": label,
                    "security": security,
                    "signal": int(signal_strength) if signal_strength.isdigit() else -1,
                    "active": active,
                }
            )
            seen_ssids.add(ssid)

        if current_wifi and current_wifi not in seen_ssids:
            networks.insert(
                0,
                {
                    "ssid": current_wifi,
                    "label": f"{current_wifi}  |  Connected",
                    "security": "",
                    "signal": 101,
                    "active": True,
                },
            )

        networks.sort(key=lambda item: (0 if item.get("active") else 1, -(item.get("signal", -1)), item.get("ssid", "").lower()))
        for item in networks:
            item.pop("signal", None)
            item.pop("active", None)

        message = f"Found {len(networks)} network(s)." if networks else "No Wi-Fi networks found. Try Refresh Networks again."
        return networks, current_wifi, message

    def connect_to_wifi(self, network_info, password: str):
        if isinstance(network_info, dict):
            ssid = str(network_info.get("ssid", "")).strip()
            security = str(network_info.get("security", "")).strip()
        else:
            ssid = str(network_info or "").strip()
            security = ""
        if not ssid:
            return False, "Enter or choose a Wi-Fi network name first.", ""

        nmcli = shutil.which("nmcli")
        if not nmcli:
            return False, "NetworkManager tools are not installed on this device.", ""

        device_name = ""
        try:
            device_result = subprocess.run(
                [nmcli, "--colors", "no", "--terse", "--fields", "DEVICE,TYPE,STATE", "device", "status"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if device_result.returncode == 0:
                for line in device_result.stdout.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2 and parts[1].strip() == "wifi":
                        device_name = parts[0].strip()
                        break
        except Exception:
            logging.exception("Failed to inspect Wi-Fi device status")

        secure_network = bool(security and security.lower() not in ("", "--", "open"))

        # If a profile already exists, try bringing it up first.
        try:
            profile_result = subprocess.run(
                [nmcli, "--colors", "no", "--terse", "--fields", "NAME,TYPE", "connection", "show"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if profile_result.returncode == 0:
                for line in profile_result.stdout.splitlines():
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[0].strip() == ssid and parts[1].strip() == "802-11-wireless":
                        up_command = [nmcli, "connection", "up", ssid]
                        if device_name:
                            up_command.extend(["ifname", device_name])
                        up_result = subprocess.run(
                            up_command,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=45,
                        )
                        if up_result.returncode == 0:
                            return True, f"Connected to {ssid}.", ssid
                        break
        except Exception:
            logging.exception("Failed to try saved Wi-Fi connection profile")

        if secure_network and not password:
            return False, f"{ssid} needs a Wi-Fi password before it can connect.", ""

        command = [nmcli, "device", "wifi", "connect", ssid]
        if secure_network and password:
            command.extend(["password", password])
        if device_name:
            command.extend(["ifname", device_name])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
        except Exception as exc:
            logging.exception("Failed to connect to Wi-Fi")
            return False, f"Could not connect to {ssid}: {exc}", ""

        if result.returncode != 0 and not secure_network:
            try:
                hidden_fallback = [nmcli, "device", "wifi", "connect", ssid, "hidden", "yes"]
                if device_name:
                    hidden_fallback.extend(["ifname", device_name])
                result = subprocess.run(
                    hidden_fallback,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=45,
                )
            except Exception as exc:
                logging.exception("Failed to retry Wi-Fi connection")
                return False, f"Could not connect to {ssid}: {exc}", ""

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Unknown error").strip()
            return False, f"Could not connect to {ssid}: {message}", ""

        return True, f"Connected to {ssid}.", ssid

    def update_from_github(self):
        git = shutil.which("git")
        if not git:
            return False, "Git is not installed. Install `git` to enable in-app updates."

        app_root = Path(__file__).resolve().parent.parent
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            if (app_root / ".git").exists():
                result = subprocess.run(
                    [git, "-C", str(app_root), "pull", "--ff-only", "origin", "main"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                if result.returncode != 0:
                    message = (result.stderr or result.stdout or "Unknown error").strip()
                    return False, f"Update failed: {message}"
                output = (result.stdout or result.stderr or "").strip()
                if "Already up to date" in output:
                    return True, "LinuxTV is already up to date."
                return True, "LinuxTV was updated from GitHub. Restart the app to load the new version."

            with tempfile.TemporaryDirectory(prefix="linuxtv-update-") as temp_dir:
                clone_result = subprocess.run(
                    [git, "clone", "--depth", "1", UPDATE_REPO_URL, temp_dir],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
                if clone_result.returncode != 0:
                    message = (clone_result.stderr or clone_result.stdout or "Unknown error").strip()
                    return False, f"Update failed: {message}"

                source_root = Path(temp_dir)
                excluded = {".git", ".venv", ".linuxtv_venv", "__pycache__", ".pytest_cache", ".mypy_cache"}
                for child in source_root.iterdir():
                    if child.name in excluded:
                        continue
                    target = app_root / child.name
                    if child.is_dir():
                        if target.exists() and not target.is_dir():
                            target.unlink()
                        if not target.exists():
                            shutil.copytree(child, target)
                        else:
                            self._merge_directory(child, target, excluded)
                    else:
                        shutil.copy2(child, target)

            return True, "LinuxTV was updated from GitHub. Restart the app to load the new version."
        except Exception as exc:
            logging.exception("Failed to update LinuxTV from GitHub")
            return False, f"Update failed: {exc}"
        finally:
            QApplication.restoreOverrideCursor()

    def _merge_directory(self, source_dir: Path, target_dir: Path, excluded=None):
        excluded = excluded or set()
        target_dir.mkdir(parents=True, exist_ok=True)
        for child in source_dir.iterdir():
            if child.name in excluded:
                continue
            target = target_dir / child.name
            if child.is_dir():
                self._merge_directory(child, target, excluded)
            else:
                shutil.copy2(child, target)

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
        self.focus_entry_tile("native", native_apps[-1])
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
        self.focus_entry_tile("web", web_apps[-1])
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

    def wheelEvent(self, event):
        """Handle touchpad two-finger scrolling."""
        if not self.tiles:
            return
        
        self.reset_auto_launch_timer()
        
        # Get the angle delta - positive for up/left, negative for down/right
        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()
        
        # Vertical scrolling (up/down)
        if abs(delta_y) > abs(delta_x):
            if delta_y < 0:  # Scroll down
                self.navigate("DOWN")
            elif delta_y > 0:  # Scroll up
                self.navigate("UP")
        # Horizontal scrolling (left/right)
        else:
            if delta_x < 0:  # Scroll right
                self.navigate("RIGHT")
            elif delta_x > 0:  # Scroll left
                self.navigate("LEFT")
        
        event.accept()

    def eventFilter(self, obj, event):
        """Event filter to capture wheel events from child widgets."""
        if event.type() == QEvent.Wheel:
            # Forward wheel event to the window's wheelEvent
            self.wheelEvent(event)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        if hasattr(self, "ws_server") and self.ws_server:
            self.ws_server.stop()
        if hasattr(self, "input_grabber") and self.input_grabber:
            self.input_grabber.stop_grabbing()
        if hasattr(self, "_icon_pool") and self._icon_pool:
            self._icon_pool.shutdown(wait=False, cancel_futures=True)
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
                self.focus_first_tile()
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
            "PREVIOUS_TRACK",
            "NEXT_TRACK",
            "STOP_MEDIA",
        ):
            self.send_remote_key_to_active_window(action)
            return

        if action in ("PLAY_PAUSE",):
            self.send_remote_key_to_active_window(action)
            return

        if action in ("PREVIOUS_TRACK", "NEXT_TRACK", "STOP_MEDIA"):
            self.send_remote_key_to_active_window(action)
            return

        if action in ("CLOSE", "EXIT", "STOP", "CLOSE_APP") and self.active_process:
            self.close_active_app()
            return

        if action in ("SHUTDOWN", "REBOOT"):
            request_system_power_action(action)
            return

        if action in ("VOLUME_UP", "VOLUME_DOWN", "MUTE"):
            control_system_volume(action)
            return

        if action == "TOGGLE_FULLSCREEN":
            self.toggle_fullscreen()
            return

        if action in ("UP", "DOWN", "LEFT", "RIGHT"):
            self.navigate(action)
            return

        if action in ("SELECT", "OK"):
            self.activate_current()
            return

        if action == "BACK":
            # On launcher this returns to start tile
            self.focus_first_tile()
            return

        if action == "HOME":
            self.focus_first_tile()
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
            "PREVIOUS_TRACK": ["XF86AudioPrev"],
            "NEXT_TRACK": ["XF86AudioNext"],
            "STOP_MEDIA": ["XF86AudioStop"],
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
        # Only send the first key in the sequence (not all of them)
        key_name = key_sequences[0]
        subprocess.run([xdotool, "key", "--window", target_window, "--clearmodifiers", key_name], check=False)
        logging.info("Forwarded remote action %s to active window (key: %s)", action, key_name)

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
        # First try to close the tracked active process
        if self.active_process and self.active_process.poll() is None:
            logging.info("Closing tracked active app %s (pid=%s)", self.active_process_name, self.active_process.pid)
            try:
                os.killpg(self.active_process.pid, signal.SIGTERM)
                self.finish_active_process()
                return
            except Exception:
                logging.exception("Failed to terminate active app process group, trying xdotool")
                try:
                    self.active_process.terminate()
                    self.finish_active_process()
                    return
                except Exception:
                    logging.exception("Failed to terminate active app directly, trying xdotool")
        
        # If no tracked process or termination failed, try to close the active window
        logging.info("No tracked process or process already exited, trying to close active window")
        xdotool, active_window = self.active_system_window()
        
        if xdotool and active_window:
            # Don't close the launcher window itself
            if active_window in self.launcher_window_ids():
                logging.info("Active window is the launcher, showing launcher")
                self.show()
                self.raise_()
                self.activateWindow()
                return
            
            logging.info("Closing active window %s using xdotool", active_window)
            try:
                # Try to close the window gracefully
                subprocess.run([xdotool, "windowclose", active_window], check=False, timeout=3)
                
                # Also try sending Alt+F4 as fallback
                time.sleep(0.2)
                subprocess.run([xdotool, "key", "alt+F4"], check=False, timeout=3)
                
                # Clear the tracked process since we're closing via window
                self.finish_active_process()
            except Exception as e:
                logging.exception("Failed to close active window: %s", e)
        else:
            logging.warning("No active process or window found to close")

    def toggle_fullscreen(self):
        """Toggle fullscreen mode for the active window or launcher."""
        launcher_active = self.launcher_context_is_active()
        
        if launcher_active:
            # Toggle fullscreen for the launcher window itself
            if self.isFullScreen():
                logging.info("Exiting fullscreen for launcher")
                self.showNormal()
                self.apply_fullscreen_to_primary_screen()
            else:
                logging.info("Entering fullscreen for launcher")
                self.showFullScreen()
            return
        
        # Try to toggle fullscreen for the active window using xdotool
        xdotool, active_window = self.active_system_window()
        
        if xdotool and active_window:
            # Don't toggle the launcher window
            if active_window in self.launcher_window_ids():
                if self.isFullScreen():
                    self.showNormal()
                    self.apply_fullscreen_to_primary_screen()
                else:
                    self.showFullScreen()
                return
            
            logging.info("Toggling fullscreen for active window %s", active_window)
            try:
                # Send F11 key to toggle fullscreen (standard for most apps)
                subprocess.run([xdotool, "key", "F11"], check=False, timeout=3)
            except Exception as e:
                logging.exception("Failed to toggle fullscreen: %s", e)
        else:
            logging.warning("No active window found for fullscreen toggle")

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
        current_tile = self.current_tile()
        if current_tile:
            current_tile.setFocus()
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
        if not self.tile_rows:
            return

        if direction == "RIGHT":
            target_row = self.current_row
            target_col = min(self.current_col + 1, len(self.tile_rows[target_row]) - 1)
        elif direction == "LEFT":
            target_row = self.current_row
            target_col = max(self.current_col - 1, 0)
        elif direction == "DOWN":
            target_row = min(self.current_row + 1, len(self.tile_rows) - 1)
            target_col = min(self.current_col, len(self.tile_rows[target_row]) - 1)
        elif direction == "UP":
            target_row = max(self.current_row - 1, 0)
            target_col = min(self.current_col, len(self.tile_rows[target_row]) - 1)
        else:
            return

        self.focus_tile_at(target_row, target_col)
        self.ensure_current_tile_visible()
        self.reset_auto_launch_timer()

    def ensure_current_tile_visible(self):
        if not hasattr(self, "tile_scroll") or not self.tile_rows:
            return
        current_tile = self.current_tile()
        if not current_tile or not current_tile.card_shell:
            return

        section = current_tile.section_widget
        outer_scrollbar = self.tile_scroll.verticalScrollBar()
        if section is not None:
            target_y = max(0, section.y() - (self.tile_scroll.viewport().height() // 4))
            vertical_anim = QPropertyAnimation(outer_scrollbar, b"value", self)
            vertical_anim.setDuration(220)
            vertical_anim.setStartValue(outer_scrollbar.value())
            vertical_anim.setEndValue(target_y)
            vertical_anim.setEasingCurve(QEasingCurve.OutCubic)
            vertical_anim.start()
            self._scroll_anim = vertical_anim

        row_scroll = current_tile.row_scroll
        if row_scroll is not None:
            row_scrollbar = row_scroll.horizontalScrollBar()
            card_x = current_tile.card_shell.x()
            target_x = max(0, card_x - (row_scroll.viewport().width() // 5))
            horizontal_anim = QPropertyAnimation(row_scrollbar, b"value", self)
            horizontal_anim.setDuration(180)
            horizontal_anim.setStartValue(row_scrollbar.value())
            horizontal_anim.setEndValue(target_x)
            horizontal_anim.setEasingCurve(QEasingCurve.OutCubic)
            horizontal_anim.start()
            self._row_scroll_anim = horizontal_anim

    def activate_current(self):
        widget = self.current_tile()
        if widget is None:
            return
        self.auto_launch_timer.stop()
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
