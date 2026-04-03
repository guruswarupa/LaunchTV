#!/usr/bin/env python3
import json
import logging
import os
import shutil
import subprocess
import sys
import asyncio
import threading
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

try:
    import websockets
except ImportError:
    websockets = None

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "LaunchTV"
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"

DEFAULT_CONFIG = {
    "native_apps": [
        {"name": "Kodi", "cmd": "kodi", "icon": "icons/kodi.png"},
        {"name": "Stremio", "cmd": "stremio", "icon": "icons/stremio.png"},
        {"name": "VLC", "cmd": "vlc", "icon": "icons/vlc.png"},
    ],
    "web_apps": [
        {"name": "YouTube", "url": "https://www.youtube.com/tv", "icon": "icons/youtube.png"},
        {"name": "Netflix", "url": "https://www.netflix.com/browse", "icon": "icons/netflix.png"},
        {"name": "Spotify Web", "url": "https://open.spotify.com", "icon": "icons/spotify.png"},
        {"name": "Prime Video", "url": "https://www.primevideo.com", "icon": "icons/primevideo.png"},
    ],
}

LINE_COUNT = 4
COLUMN_COUNT = 3


def resource_path(relpath: str) -> Path:
    base = Path(__file__).parent
    return (base / relpath).expanduser().resolve()


def load_config(path: Path):
    if not path.exists():
        logging.warning("Config not found at %s, using built-in defaults", path)
        return DEFAULT_CONFIG

    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yml", ".yaml"):
            if yaml is None:
                raise RuntimeError("pyyaml is required to load YAML config")
            return yaml.safe_load(text)
        if path.suffix.lower() == ".json":
            return json.loads(text)

        # fallback by heuristic
        if text.strip().startswith("{"):
            return json.loads(text)
        if yaml is None:
            raise RuntimeError("pyyaml is required to load YAML config")
        return yaml.safe_load(text)
    except Exception as e:
        logging.exception("Failed to load config '%s': %s", path, e)
        return DEFAULT_CONFIG


def find_browser():
    candidates = ["chromium", "chromium-browser", "brave-browser", "google-chrome", "firefox"]
    for exe in candidates:
        if shutil.which(exe):
            return exe
    return None


def is_installed(cmd_or_path: str) -> bool:
    if Path(cmd_or_path).is_absolute() and Path(cmd_or_path).exists():
        return True
    return shutil.which(cmd_or_path) is not None


class WebSocketControlServer(threading.Thread):
    def __init__(self, window, host="0.0.0.0", port=8765):
        super().__init__(daemon=True)
        self.window = window
        self.host = host
        self.port = port
        self.loop = None
        self.server = None
        self._stop_event = threading.Event()

    async def handler(self, websocket, path):
        logging.info("WebSocket connection from %s", websocket.remote_address)
        try:
            async for message in websocket:
                logging.info("Received remote action: %s", message)
                try:
                    payload = json.loads(message)
                    action = str(payload.get("action", "")).upper()
                except Exception:
                    action = None

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
    def __init__(self, name: str, icon_path: str, tooltip: str = ""):
        super().__init__(name)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(QSize(240, 140))
        self.setFont(QFont("Sans Serif", 18, QFont.Bold))
        if icon_path:
            path = resource_path(icon_path)
            if path.exists():
                self.setIcon(QIcon(str(path)))
                self.setIconSize(QSize(64, 64))
        self.setToolTip(tooltip)
        self.setStyleSheet(
            "QPushButton { background-color: #222; color: #eee; border: 2px solid #444; border-radius: 16px; padding: 16px; }"
            "QPushButton:focus { border: 2px solid #2a82ff; background-color: #2a2a2a; }"
            "QPushButton:hover { background-color: #333; }"
        )


class LauncherWindow(QMainWindow):
    def __init__(self, config_path: Path):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.showFullScreen()
        self.browser_exe = find_browser()

        self.config = load_config(config_path)
        self.tiles = []
        self.current_index = 0

        self.ws_server = WebSocketControlServer(self)
        self.ws_server.start()

        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)

        header = QLabel("LaunchTV — Media Launcher")
        header.setFont(QFont("Sans Serif", 38, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: white; padding: 12px")
        main_layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setSpacing(14)

        self.populate_tiles()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        footer = QLabel("Arrows: move • Enter: launch • Esc: exit app\nConfig: config.yaml")
        footer.setFont(QFont("Sans Serif", 14))
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #ccc; padding: 8px")
        main_layout.addWidget(footer)

        self.setCentralWidget(central)

        if self.tiles:
            self.tiles[0].setFocus()

    def populate_tiles(self):
        row = 0
        col = 0

        native_apps = self.config.get("native_apps", [])
        web_apps = self.config.get("web_apps", [])

        filtered_native = [a for a in native_apps if is_installed(a.get("cmd", ""))]

        # Native section label
        if filtered_native:
            label = QLabel("Native Apps")
            label.setFont(QFont("Sans Serif", 26, QFont.Bold))
            label.setStyleSheet("color: #ccc; margin-top: 10px; margin-bottom: 10px")
            self.grid.addWidget(label, row, 0, 1, COLUMN_COUNT)
            row += 1

            for app in filtered_native:
                tile = TileButton(app.get("name", "Untitled"), app.get("icon", ""), app.get("cmd", ""))
                tile.clicked.connect(lambda checked=False, item=app, kind="native": self.launch_app(item, kind))
                self.grid.addWidget(tile, row, col)
                self.tiles.append(tile)
                col += 1
                if col >= COLUMN_COUNT:
                    col = 0
                    row += 1

            if col != 0:
                row += 1
                col = 0

        if web_apps:
            label = QLabel("Web Services")
            label.setFont(QFont("Sans Serif", 26, QFont.Bold))
            label.setStyleSheet("color: #ccc; margin-top: 20px; margin-bottom: 10px")
            self.grid.addWidget(label, row, 0, 1, COLUMN_COUNT)
            row += 1

            for app in web_apps:
                tile = TileButton(app.get("name", "Untitled"), app.get("icon", ""), app.get("url", ""))
                tile.clicked.connect(lambda checked=False, item=app, kind="web": self.launch_app(item, kind))
                self.grid.addWidget(tile, row, col)
                self.tiles.append(tile)
                col += 1
                if col >= COLUMN_COUNT:
                    col = 0
                    row += 1

    def keyPressEvent(self, event):
        if not self.tiles:
            return

        key = event.key()
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
        event.accept()

    def queue_remote_action(self, action):
        QTimer.singleShot(0, lambda: self.process_remote_action(action))

    def process_remote_action(self, action: str):
        action = action.upper()
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

        logging.warning("Unknown remote action: %s", action)

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

    def activate_current(self):
        if not self.tiles:
            return
        widget = self.tiles[self.current_index]
        if widget:
            widget.click()

    def launch_app(self, item, kind: str):
        command = None
        if kind == "native":
            cmd = item.get("cmd")
            if not cmd:
                logging.warning("Native item missing command: %s", item)
                return
            command = [cmd]

        if kind == "web":
            if not self.browser_exe:
                logging.error("No browser found for web app launch")
                return
            url = item.get("url")
            if not url:
                logging.warning("Web app missing URL: %s", item)
                return

            if "chromium" in self.browser_exe or "chrome" in self.browser_exe or "brave" in self.browser_exe:
                command = [
                    self.browser_exe,
                    "--kiosk",
                    "--app=%s" % url,
                    "--no-first-run",
                    "--disable-translate",
                    "--disable-infobars",
                    "--window-position=0,0",
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
            proc = subprocess.Popen(command)
            proc.wait()
        except Exception:
            logging.exception("App launch failed")
        finally:
            QApplication.restoreOverrideCursor()
            if self.tiles:
                self.tiles[self.current_index].setFocus()


def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    config_path = Path(os.getenv("LAUNCHTV_CONFIG", "~/.config/launchtv/config.yaml")).expanduser()
    if not config_path.exists():
        default = Path(__file__).parent / "config.yaml"
        if default.exists():
            config_path = default

    app = QApplication(sys.argv)
    app.setStyleSheet("QMainWindow { background-color: #000; }")

    window = LauncherWindow(config_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
