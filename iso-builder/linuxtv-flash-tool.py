#!/usr/bin/env python3
"""
LinuxTV Flash Tool - Cross-platform GUI application to flash LinuxTV ISO to USB
Supports Windows, macOS, and Linux
"""

import os
import sys
import subprocess
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except ImportError:
    print("Error: tkinter is required. Please install python3-tk package.")
    sys.exit(1)


class LinuxTVFlashTool:
    def __init__(self, root):
        self.root = root
        self.root.title("LinuxTV Flash Tool")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        self.iso_path = tk.StringVar()
        self.selected_drive = tk.StringVar()
        self.enable_persistence = tk.BooleanVar(value=True)
        self.is_flashing = False
        
        self.available_drives = []
        
        self.setup_ui()
        self.refresh_drives()
    
    def setup_ui(self):
        """Setup the user interface"""
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="LinuxTV Flash Tool",
            font=("Helvetica", 18, "bold")
        )
        title_label.pack(pady=(0, 20))
        
        # ISO Selection
        iso_frame = ttk.LabelFrame(main_frame, text="Step 1: Select ISO File", padding="10")
        iso_frame.pack(fill=tk.X, pady=(0, 10))
        
        iso_entry = ttk.Entry(iso_frame, textvariable=self.iso_path, width=50)
        iso_entry.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)
        
        iso_button = ttk.Button(iso_frame, text="Browse...", command=self.browse_iso)
        iso_button.pack(side=tk.RIGHT)
        
        # Drive Selection
        drive_frame = ttk.LabelFrame(main_frame, text="Step 2: Select USB Drive", padding="10")
        drive_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.drive_combo = ttk.Combobox(
            drive_frame,
            textvariable=self.selected_drive,
            width=47,
            state="readonly"
        )
        self.drive_combo.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)
        
        refresh_button = ttk.Button(
            drive_frame,
            text="Refresh",
            command=self.refresh_drives
        )
        refresh_button.pack(side=tk.RIGHT)
        
        # Options
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10")
        options_frame.pack(fill=tk.X, pady=(0, 10))
        
        persistence_check = ttk.Checkbutton(
            options_frame,
            text="Enable persistence (save your files and settings)",
            variable=self.enable_persistence
        )
        persistence_check.pack(anchor=tk.W)
        
        persistence_info = ttk.Label(
            options_frame,
            text="A partition will be created. On first boot, LinuxTV will automatically format it as ext4.",
            foreground="gray",
            font=("Helvetica", 9)
        )
        persistence_info.pack(anchor=tk.W, pady=(5, 0))
        
        # Flash Button
        self.flash_button = ttk.Button(
            main_frame,
            text="Flash LinuxTV to USB",
            command=self.start_flash,
            style="Accent.TButton"
        )
        self.flash_button.pack(fill=tk.X, pady=(0, 10))
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(0, 10))
        
        # Status
        self.status_label = ttk.Label(
            main_frame,
            text="Ready",
            font=("Helvetica", 10)
        )
        self.status_label.pack()
        
        # Warning
        warning_label = ttk.Label(
            main_frame,
            text="WARNING: This will erase all data on the selected USB drive!",
            foreground="red",
            font=("Helvetica", 9, "bold")
        )
        warning_label.pack(pady=(10, 0))
    
    def browse_iso(self):
        """Browse for ISO file"""
        filename = filedialog.askopenfilename(
            title="Select LinuxTV ISO",
            filetypes=[("ISO files", "*.iso"), ("All files", "*.*")]
        )
        if filename:
            self.iso_path.set(filename)
    
    def refresh_drives(self):
        """Refresh available drives"""
        self.available_drives = self.get_available_drives()
        
        if self.available_drives:
            drive_list = [f"{d['device']} - {d['name']} ({d['size']})" for d in self.available_drives]
            self.drive_combo['values'] = drive_list
            if drive_list:
                self.drive_combo.current(0)
        else:
            self.drive_combo['values'] = ["No USB drives found"]
            self.selected_drive.set("No USB drives found")
    
    def get_available_drives(self):
        """Get available USB drives based on OS"""
        drives = []
        
        try:
            if sys.platform == 'win32':
                # Windows - use PowerShell
                result = subprocess.run(
                    ['powershell', '-Command',
                     'Get-PhysicalDisk | Where-Object {$_.BusType -eq "USB"} | '
                     'Select-Object DeviceId, FriendlyName, Size | ConvertTo-Json'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    import json
                    disk_data = json.loads(result.stdout)
                    if isinstance(disk_data, dict):
                        disk_data = [disk_data]
                    for disk in disk_data:
                        size_gb = int(disk.get('Size', 0)) / (1024**3)
                        drives.append({
                            'device': f"\\\\.\\PhysicalDrive{disk['DeviceId']}",
                            'name': disk.get('FriendlyName', 'USB Drive'),
                            'size': f"{size_gb:.1f} GB"
                        })
            
            elif sys.platform == 'darwin':
                # macOS - use diskutil
                result = subprocess.run(
                    ['diskutil', 'list', '-plist'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    import plistlib
                    plist_data = plistlib.loads(result.stdout.encode())
                    for disk in plist_data.get('AllDisksAndPartitions', []):
                        if disk.get('Internal') is False and disk.get('DeviceSize', 0) > 0:
                            size_gb = disk['DeviceSize'] / (1024**3)
                            device = disk.get('DeviceIdentifier', '')
                            if 'disk' in device:
                                drives.append({
                                    'device': f"/dev/{device.split('s')[0]}",
                                    'name': disk.get('MediaName', 'USB Drive'),
                                    'size': f"{size_gb:.1f} GB"
                                })
            
            else:
                # Linux - use lsblk
                result = subprocess.run(
                    ['lsblk', '-d', '-n', '-o', 'NAME,SIZE,MODEL,TRAN'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        parts = line.split()
                        if len(parts) >= 2:
                            name = parts[0]
                            size = parts[1] if len(parts) > 1 else ""
                            model = ' '.join(parts[2:]) if len(parts) > 2 else "USB Drive"
                            if name.startswith(('sd', 'vd', 'nvme')):
                                drives.append({
                                    'device': f"/dev/{name}",
                                    'name': model.strip(),
                                    'size': size
                                })
        except Exception as e:
            print(f"Error getting drives: {e}")
        
        return drives
    
    def start_flash(self):
        """Start the flashing process"""
        if self.is_flashing:
            messagebox.showwarning("Warning", "Flash operation already in progress!")
            return
        
        # Validate inputs
        if not self.iso_path.get():
            messagebox.showerror("Error", "Please select an ISO file!")
            return
        
        if not os.path.exists(self.iso_path.get()):
            messagebox.showerror("Error", "ISO file not found!")
            return
        
        if not self.selected_drive.get() or "No USB drives found" in self.selected_drive.get():
            messagebox.showerror("Error", "Please select a USB drive!")
            return
        
        # Confirm
        drive_info = self.selected_drive.get()
        confirm = messagebox.askyesno(
            "Confirm",
            f"This will ERASE ALL DATA on the selected USB drive:\n\n"
            f"{drive_info}\n\n"
            f"Are you sure you want to continue?"
        )
        
        if not confirm:
            return
        
        # Start flashing in background thread
        self.is_flashing = True
        self.flash_button.config(state=tk.DISABLED)
        self.progress['value'] = 0
        
        thread = threading.Thread(target=self.flash_iso, daemon=True)
        thread.start()
    
    def flash_iso(self):
        """Flash ISO to USB drive"""
        try:
            iso_file = self.iso_path.get()
            drive_info = self.selected_drive.get()
            device = drive_info.split(' - ')[0]
            
            self.update_status("Starting flash process...")
            self.update_progress(10)
            
            if sys.platform == 'win32':
                self.flash_windows(iso_file, device)
            elif sys.platform == 'darwin':
                self.flash_macos(iso_file, device)
            else:
                self.flash_linux(iso_file, device)
            
            if self.enable_persistence.get():
                self.update_status("Creating persistence partition...")
                self.update_progress(90)
                self.create_persistence_partition(device)
            
            self.update_progress(100)
            self.update_status("Flash complete!")
            
            self.root.after(0, lambda: messagebox.showinfo(
                "Success",
                "LinuxTV has been successfully flashed to USB!\n\n"
                "You can now boot from this USB drive.\n"
                "If persistence is enabled, the partition will be\n"
                "automatically formatted on first boot."
            ))
        
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("Error", f"Flash failed:\n{str(e)}"))
        
        finally:
            self.is_flashing = False
            self.root.after(0, lambda: self.flash_button.config(state=tk.NORMAL))
    
    def flash_windows(self, iso_file, device):
        """Flash ISO on Windows using dd for Windows or raw write"""
        self.update_status("Writing ISO to USB (this may take 5-15 minutes)...")
        
        dd_path = self.find_dd_windows()
        
        if dd_path:
            cmd = [dd_path, f"if={iso_file}", f"of={device}", "bs=4M", "--progress"]
            process = subprocess.run(cmd, capture_output=True, text=True)
            if process.returncode != 0:
                raise Exception(f"dd failed: {process.stderr}")
        else:
            ps_script = f"""
            $iso = "{iso_file}"
            $drive = "{device}"
            $isoStream = [System.IO.File]::OpenRead($iso)
            $driveStream = [System.IO.File]::OpenWrite($drive)
            $buffer = New-Object byte[] 4194304
            while (($read = $isoStream.Read($buffer, 0, $buffer.Length)) -gt 0) {{
                $driveStream.Write($buffer, 0, $read)
            }}
            $isoStream.Close()
            $driveStream.Close()
            """
            process = subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True,
                text=True,
                timeout=3600
            )
            if process.returncode != 0:
                raise Exception(f"PowerShell write failed: {process.stderr}")
    
    def flash_macos(self, iso_file, device):
        """Flash ISO on macOS using dd"""
        self.update_status("Writing ISO to USB (this may take 5-15 minutes)...")
        
        disk_id = device.replace("/dev/", "")
        subprocess.run(['diskutil', 'unmountDisk', f"/dev/{disk_id}"], capture_output=True)
        
        raw_device = device.replace("/dev/disk", "/dev/rdisk")
        cmd = ['sudo', 'dd', f'if={iso_file}', f'of={raw_device}', 'bs=1m']
        
        process = subprocess.run(cmd, capture_output=True, timeout=3600)
        if process.returncode != 0:
            raise Exception(f"dd failed: {process.stderr.decode()}")
        
        subprocess.run(['sync'])
    
    def flash_linux(self, iso_file, device):
        """Flash ISO on Linux using dd"""
        self.update_status("Writing ISO to USB (this may take 5-15 minutes)...")
        
        cmd = ['sudo', 'dd', f'if={iso_file}', f'of={device}', 'bs=4M', 'status=progress', 'oflag=sync']
        
        process = subprocess.run(cmd, capture_output=True, timeout=3600)
        if process.returncode != 0:
            raise Exception(f"dd failed: {process.stderr.decode()}")
    
    def create_persistence_partition(self, device):
        """Create persistence partition (without formatting)"""
        self.update_status("Creating persistence partition...")
        
        if sys.platform == 'win32':
            self.create_persistence_windows(device)
        elif sys.platform == 'darwin':
            self.create_persistence_macos(device)
        else:
            self.create_persistence_linux(device)
    
    def create_persistence_windows(self, device):
        """Create persistence partition on Windows"""
        disk_number = device.replace("\\\\.\\PhysicalDrive", "")
        
        diskpart_script = f"""
select disk {disk_number}
create partition primary
exit
"""
        temp_file = Path(os.environ['TEMP']) / "linuxtv_diskpart.txt"
        temp_file.write_text(diskpart_script)
        
        process = subprocess.run(
            ['diskpart', '/s', str(temp_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        temp_file.unlink()
        
        if process.returncode != 0:
            print(f"Warning: Partition creation had issues: {process.stdout}")
    
    def create_persistence_macos(self, device):
        """Create persistence partition on macOS"""
        disk_id = device.replace("/dev/", "")
        
        cmd = ['sudo', 'diskutil', 'resizeVolume', f"/dev/{disk_id}s2", 'R',
               'Free Space', 'free',
               'LinuxTVPersistence', '0b']
        
        subprocess.run(cmd, capture_output=True, timeout=60)
    
    def create_persistence_linux(self, device):
        """Create persistence partition on Linux"""
        self.update_status("Waiting for disk to be recognized...")
        time.sleep(3)
        
        subprocess.run(['sudo', 'partprobe', device], capture_output=True)
        time.sleep(2)
        
        result = subprocess.run(
            ['lsblk', '-nplb', '-o', 'TYPE,START,SIZE', device],
            capture_output=True,
            text=True
        )
        
        last_sector = 0
        partition_count = 0
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if parts[0] == 'part' and len(parts) >= 3:
                start = int(parts[1])
                size = int(parts[2])
                end = start + (size // 512)
                if end > last_sector:
                    last_sector = end
                    partition_count += 1
        
        if partition_count == 0:
            self.update_status("Using alternative partition detection...")
            disk_result = subprocess.run(
                ['sudo', 'blockdev', '--getsz', device],
                capture_output=True,
                text=True
            )
            if disk_result.returncode == 0:
                last_sector = 8388608
            else:
                raise Exception("Could not detect disk partitions. Try unplugging and replugging the USB.")
        
        new_start = ((last_sector // 2048) + 1) * 2048
        
        self.update_status("Creating persistence partition...")
        
        fdisk_cmd = f"n\np\n3\n{new_start}\n\nw\n"
        process = subprocess.run(
            ['sudo', 'fdisk', device],
            input=fdisk_cmd,
            text=True,
            capture_output=True,
            timeout=60
        )
        
        if process.returncode != 0:
            print(f"fdisk output: {process.stdout}")
            print(f"fdisk stderr: {process.stderr}")
            if "Warning" not in process.stderr.decode():
                raise Exception(f"fdisk failed: {process.stderr}")
        
        self.update_status("Refreshing partition table...")
        subprocess.run(['sudo', 'partprobe', device], capture_output=True)
        subprocess.run(['sudo', 'blockdev', '--rereadpt', device], capture_output=True)
        time.sleep(3)
        
        # Verify partition was created
        verify_result = subprocess.run(
            ['lsblk', '-n', '-o', 'NAME', device],
            capture_output=True,
            text=True
        )
        
        partitions = [p.strip().lstrip('├─└│ ') for p in verify_result.stdout.strip().split('\n')]
        base_name = device.split('/')[-1]
        partition3 = f"{base_name}3"
        
        if partition3 in partitions:
            self.update_status("Persistence partition created successfully!")
            time.sleep(1)
        else:
            print(f"Warning: Partition verification failed. Partitions found: {partitions}")
            print(f"Looking for: {partition3}")
            self.update_status("Partition created (verify manually with lsblk)")
            time.sleep(1)
    
    def find_dd_windows(self):
        """Find dd executable on Windows"""
        possible_paths = [
            r"C:\Program Files\GnuWin32\bin\dd.exe",
            r"C:\Program Files (x86)\GnuWin32\bin\dd.exe",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def update_status(self, message):
        """Update status label"""
        self.root.after(0, lambda: self.status_label.config(text=message))
    
    def update_progress(self, value):
        """Update progress bar"""
        self.root.after(0, lambda: self.progress.config(value=value))


def main():
    root = tk.Tk()
    app = LinuxTVFlashTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
