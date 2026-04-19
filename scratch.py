import subprocess

def scan_bt():
    subprocess.run(["bluetoothctl", "power", "on"], capture_output=True)
    subprocess.run(["timeout", "5", "bluetoothctl", "scan", "on"], capture_output=True)
    res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True)
    for line in res.stdout.splitlines():
        print(line)

scan_bt()
