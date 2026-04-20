import sys
from pathlib import Path

def modify_launcher():
    path = Path(__file__).parent / "linuxtvdesktop" / "launcher.py"
    with open(path, "r") as f:
        content = f.read()

    # 1. SettingsDialog signature
    old_init_sig = """    wifi_scan_finished = Signal(object, str, str)

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
    ):"""
    new_init_sig = """    wifi_scan_finished = Signal(object, str, str)
    bluetooth_scan_finished = Signal(object, str, str)

    def __init__(
        self,
        username_text="",
        auto_launch=None,
        app_options=None,
        wifi_networks=None,
        current_wifi="",
        wifi_refresh_callback=None,
        wifi_connect_callback=None,
        bluetooth_devices=None,
        current_bluetooth="",
        bluetooth_refresh_callback=None,
        bluetooth_connect_callback=None,
        update_callback=None,
        parent=None,
    ):"""
    content = content.replace(old_init_sig, new_init_sig)
    
    # 2. Callbacks & state variables
    old_state = """        self.wifi_refresh_callback = wifi_refresh_callback
        self.wifi_connect_callback = wifi_connect_callback
        self.update_callback = update_callback
        self._wifi_scan_in_progress = False
        self._wifi_has_loaded = bool(wifi_networks or current_wifi)
        self.wifi_scan_finished.connect(self.handle_wifi_scan_finished)"""
    new_state = """        self.wifi_refresh_callback = wifi_refresh_callback
        self.wifi_connect_callback = wifi_connect_callback
        self.bluetooth_refresh_callback = bluetooth_refresh_callback
        self.bluetooth_connect_callback = bluetooth_connect_callback
        self.update_callback = update_callback
        self._wifi_scan_in_progress = False
        self._wifi_has_loaded = bool(wifi_networks or current_wifi)
        self.wifi_scan_finished.connect(self.handle_wifi_scan_finished)
        self._bluetooth_scan_in_progress = False
        self._bluetooth_has_loaded = bool(bluetooth_devices or current_bluetooth)
        self.bluetooth_scan_finished.connect(self.handle_bluetooth_scan_finished)"""
    content = content.replace(old_state, new_state)
    
    # 3. Nav row
    old_nav = """        for section_id, label in (
            ("auto", "Auto Open"),
            ("remote", "Remote Login"),
            ("wifi", "Wi-Fi"),
            ("update", "Update"),
        ):"""
    new_nav = """        for section_id, label in (
            ("auto", "Auto Open"),
            ("remote", "Remote Login"),
            ("wifi", "Wi-Fi"),
            ("bluetooth", "Bluetooth"),
            ("update", "Update"),
        ):"""
    content = content.replace(old_nav, new_nav)
    
    # 4. Bluetooth panel creation
    old_panel_insert = """        self.wifi_status_label = QLabel("")
        self.wifi_status_label.setObjectName("dialogStatus")
        self.wifi_status_label.setWordWrap(True)
        wifi_layout.addWidget(self.wifi_status_label)

        update_panel = QWidget()"""
    new_panel_insert = """        self.wifi_status_label = QLabel("")
        self.wifi_status_label.setObjectName("dialogStatus")
        self.wifi_status_label.setWordWrap(True)
        wifi_layout.addWidget(self.wifi_status_label)

        bluetooth_panel = QWidget()
        bluetooth_layout = QVBoxLayout(bluetooth_panel)
        bluetooth_layout.setContentsMargins(0, 0, 0, 0)
        bluetooth_layout.setSpacing(metrics["dialog_spacing"])

        bluetooth_title = QLabel("Bluetooth")
        bluetooth_title.setObjectName("dialogSection")
        bluetooth_title.setFont(QFont("Sans Serif", metrics["section_font"], QFont.Bold))
        bluetooth_layout.addWidget(bluetooth_title)

        bluetooth_subtitle = QLabel("Scan for nearby Bluetooth devices and connect without leaving LinuxTV.")
        bluetooth_subtitle.setObjectName("dialogSubtitle")
        bluetooth_subtitle.setWordWrap(True)
        bluetooth_subtitle.setFont(QFont("Sans Serif", metrics["subtitle_font"]))
        bluetooth_layout.addWidget(bluetooth_subtitle)

        self.bluetooth_combo = QComboBox()
        self.bluetooth_combo.setEditable(True)
        self.bluetooth_combo.setMinimumHeight(metrics["input_min_height"] + 2)
        self._style_settings_combo_popup(self.bluetooth_combo)
        self.bluetooth_combo.lineEdit().setPlaceholderText("Select or type a Bluetooth device or MAC address")
        bluetooth_layout.addWidget(self.bluetooth_combo)

        bluetooth_button_row = QHBoxLayout()
        self.refresh_bluetooth_button = QPushButton("Refresh Devices")
        self.refresh_bluetooth_button.setProperty("tileVariant", "dialogSecondary")
        self.refresh_bluetooth_button.clicked.connect(self.refresh_bluetooth_devices)
        bluetooth_button_row.addWidget(self.refresh_bluetooth_button)

        self.connect_bluetooth_button = QPushButton("Connect Device")
        self.connect_bluetooth_button.setProperty("tileVariant", "accent")
        self.connect_bluetooth_button.clicked.connect(self.connect_bluetooth)
        bluetooth_button_row.addWidget(self.connect_bluetooth_button)
        bluetooth_layout.addLayout(bluetooth_button_row)

        self.bluetooth_status_label = QLabel("")
        self.bluetooth_status_label.setObjectName("dialogStatus")
        self.bluetooth_status_label.setWordWrap(True)
        bluetooth_layout.addWidget(self.bluetooth_status_label)

        update_panel = QWidget()"""
    content = content.replace(old_panel_insert, new_panel_insert)
    
    # 5. panel tuple list
    old_panel_tuple = """        for section_id, panel in (
            ("auto", auto_panel),
            ("remote", remote_panel),
            ("wifi", wifi_panel),
            ("update", update_panel),
        ):"""
    new_panel_tuple = """        for section_id, panel in (
            ("auto", auto_panel),
            ("remote", remote_panel),
            ("wifi", wifi_panel),
            ("bluetooth", bluetooth_panel),
            ("update", update_panel),
        ):"""
    content = content.replace(old_panel_tuple, new_panel_tuple)
    
    # 6. __init__ ending (networks loaded info)
    old_networks_loaded = """        self.set_wifi_networks(wifi_networks, current_wifi)
        self.set_wifi_loading_state(False)
        if not self._wifi_has_loaded and self.wifi_refresh_callback:
            self.wifi_status_label.setText("Open this section to fetch nearby Wi-Fi networks.")
        self.setStyleSheet(dialog_stylesheet(metrics))"""
    new_networks_loaded = """        self.set_wifi_networks(wifi_networks, current_wifi)
        self.set_wifi_loading_state(False)
        if not self._wifi_has_loaded and self.wifi_refresh_callback:
            self.wifi_status_label.setText("Open this section to fetch nearby Wi-Fi networks.")

        self.set_bluetooth_devices(bluetooth_devices or [], current_bluetooth)
        self.set_bluetooth_loading_state(False)
        if not self._bluetooth_has_loaded and self.bluetooth_refresh_callback:
            self.bluetooth_status_label.setText("Open this section to fetch nearby Bluetooth devices.")

        self.setStyleSheet(dialog_stylesheet(metrics))"""
    content = content.replace(old_networks_loaded, new_networks_loaded)
    
    # 7. show_section logic
    old_show_sec = """        if section_id == "wifi":
            QTimer.singleShot(0, self.ensure_wifi_networks_loaded)"""
    new_show_sec = """        if section_id == "wifi":
            QTimer.singleShot(0, self.ensure_wifi_networks_loaded)
        elif section_id == "bluetooth":
            QTimer.singleShot(0, self.ensure_bluetooth_devices_loaded)"""
    content = content.replace(old_show_sec, new_show_sec)

    # 8. Bluetooth methods added after connect_wifi
    old_connect_wifi = """    def connect_wifi(self):
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
            self.wifi_password_input.clear()"""
            
    new_bluetooth_methods = """    def connect_wifi(self):
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

    def set_bluetooth_loading_state(self, loading: bool, message=""):
        self._bluetooth_scan_in_progress = loading
        self.refresh_bluetooth_button.setEnabled(not loading and bool(self.bluetooth_refresh_callback))
        self.connect_bluetooth_button.setEnabled(not loading and bool(self.bluetooth_connect_callback))
        if loading and message:
            self.bluetooth_status_label.setText(message)

    def ensure_bluetooth_devices_loaded(self, force=False):
        if not self.bluetooth_refresh_callback:
            self.set_bluetooth_loading_state(False)
            self.bluetooth_status_label.setText("Bluetooth scanning is not available on this system.")
            return
        if self._bluetooth_scan_in_progress:
            return
        if self._bluetooth_has_loaded and not force:
            return
        status_text = "Refreshing Bluetooth devices..." if force else "Fetching nearby Bluetooth devices..."
        self.set_bluetooth_loading_state(True, status_text)
        import threading
        threading.Thread(
            target=self._run_bluetooth_scan,
            name="bluetooth-settings-scan",
            daemon=True,
        ).start()

    def _run_bluetooth_scan(self):
        import logging
        try:
            devices, current_bluetooth, message = self.bluetooth_refresh_callback()
        except Exception as exc:
            logging.exception("Failed to refresh Bluetooth devices from settings")
            devices, current_bluetooth, message = [], "", f"Could not scan for Bluetooth devices: {exc}"
        self.bluetooth_scan_finished.emit(devices, current_bluetooth, message)

    def handle_bluetooth_scan_finished(self, bluetooth_devices, current_bluetooth, message):
        self.set_bluetooth_loading_state(False)
        self._bluetooth_has_loaded = True
        self.set_bluetooth_devices(bluetooth_devices or [], current_bluetooth)
        if message:
            self.bluetooth_status_label.setText(message)

    def set_bluetooth_devices(self, bluetooth_devices, current_bluetooth=""):
        current_text = self.bluetooth_combo.currentText().strip()
        self.bluetooth_combo.blockSignals(True)
        self.bluetooth_combo.clear()
        selected_index = -1
        for index, option in enumerate(bluetooth_devices):
            label = option.get("label", option.get("name", ""))
            mac = option.get("mac", "")
            self.bluetooth_combo.addItem(label, dict(option))
            if current_bluetooth and mac == current_bluetooth:
                selected_index = index
        self.bluetooth_combo.blockSignals(False)

        if selected_index >= 0:
            self.bluetooth_combo.setCurrentIndex(selected_index)
            self.bluetooth_status_label.setText(f"Connected device: {current_bluetooth}")
            return

        if current_text:
            self.bluetooth_combo.setEditText(current_text)
        elif current_bluetooth:
            self.bluetooth_combo.setEditText(current_bluetooth)
            self.bluetooth_status_label.setText(f"Connected device: {current_bluetooth}")
        elif bluetooth_devices:
            self.bluetooth_combo.setCurrentIndex(0)
            self.bluetooth_status_label.setText("Choose a device and connect from here.")
        else:
            self.bluetooth_combo.setEditText("")
            self.bluetooth_status_label.setText("No Bluetooth devices loaded yet. Open or refresh this section to scan.")

    def refresh_bluetooth_devices(self):
        self.ensure_bluetooth_devices_loaded(force=True)

    def connect_bluetooth(self):
        if self._bluetooth_scan_in_progress:
            self.bluetooth_status_label.setText("Still fetching nearby Bluetooth devices. Try again in a moment.")
            return
        if not self.bluetooth_connect_callback:
            self.bluetooth_status_label.setText("Bluetooth connection is not available on this system.")
            return
        selected_device = self.bluetooth_combo.currentData()
        if not isinstance(selected_device, dict):
            # If the user typed manually or its not a structured item
            selected_device = {"mac": self.bluetooth_combo.currentText().strip()}
        success, message, current_bluetooth = self.bluetooth_connect_callback(selected_device)
        if current_bluetooth:
             self.refresh_bluetooth_devices()
        self.bluetooth_status_label.setText(message)"""
    content = content.replace(old_connect_wifi, new_bluetooth_methods)

    # 9. open_remote_settings instantiation
    old_open_remote = """        dialog = SettingsDialog(
            auth.get("username", ""),
            auto_launch,
            self.get_auto_launch_options(),
            [],
            "",
            self.scan_wifi_networks,
            self.connect_to_wifi,
            self.update_from_github,
            self,
        )"""
    new_open_remote = """        dialog = SettingsDialog(
            auth.get("username", ""),
            auto_launch,
            self.get_auto_launch_options(),
            [],
            "",
            self.scan_wifi_networks,
            self.connect_to_wifi,
            [],
            "",
            self.scan_bluetooth_devices,
            self.connect_to_bluetooth,
            self.update_from_github,
            self,
        )"""
    content = content.replace(old_open_remote, new_open_remote)
    
    # 10. scan_bluetooth and connect_to_bluetooth
    old_update_from_github = """    def update_from_github(self):
        git = shutil.which("git")"""
    new_bluetooth_launcher = """    def scan_bluetooth_devices(self):
        bluetoothctl = shutil.which("bluetoothctl")
        if not bluetoothctl:
            return [], "", "bluetoothctl is not installed. Install `bluez` to manage Bluetooth here."
        
        current_bluetooth = ""
        devices = []
        try:
            # Power on first
            subprocess.run([bluetoothctl, "power", "on"], capture_output=True, check=False)
            # Scan for a short time
            subprocess.run(["timeout", "4", bluetoothctl, "scan", "on"], capture_output=True, check=False)
            
            result = subprocess.run(
                [bluetoothctl, "devices"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split(" ", 2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        mac = parts[1]
                        name = parts[2]
                        # Assume no signal strength easily available without more complicated DBus
                        devices.append({
                            "mac": mac,
                            "name": name,
                            "label": f"{name} ({mac})"
                        })
        except Exception as exc:
            import logging
            logging.exception("Failed to scan Bluetooth devices")
            return [], "", f"Could not scan: {exc}"
            
        message = f"Found {len(devices)} device(s)." if devices else "No Bluetooth devices found."
        return devices, current_bluetooth, message

    def connect_to_bluetooth(self, device_info):
        if isinstance(device_info, dict):
            mac = str(device_info.get("mac", "")).strip()
        else:
            mac = str(device_info or "").strip()
        if not mac:
            return False, "Enter or choose a Bluetooth MAC address first.", ""

        bluetoothctl = shutil.which("bluetoothctl")
        if not bluetoothctl:
            return False, "bluetoothctl is not installed on this device.", ""
            
        try:
            # First try to pair to avoid pairing prompts hanging connection
            subprocess.run([bluetoothctl, "pair", mac], capture_output=True, text=True, check=False, timeout=15)
            # Then connect
            result = subprocess.run(
                [bluetoothctl, "connect", mac],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if result.returncode == 0 and "Connection successful" in result.stdout:
                return True, f"Connected to {mac}.", mac
            elif result.returncode == 0 and result.stdout.strip() == "": # Some versions might not output
                pass
            
            # Check info if connected
            info_res = subprocess.run(
                [bluetoothctl, "info", mac],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if "Connected: yes" in info_res.stdout:
                return True, f"Connected to {mac}.", mac
                
        except Exception as exc:
            import logging
            logging.exception("Failed to connect to Bluetooth")
            return False, f"Could not connect to {mac}: {exc}", ""

        message = (result.stderr or result.stdout or "Unknown error").strip()
        return False, f"Could not connect to {mac}: {message[-100:]}", ""

    def update_from_github(self):
        git = shutil.which("git")"""
    content = content.replace(old_update_from_github, new_bluetooth_launcher)

    with open(path, "w") as f:
        f.write(content)

modify_launcher()
