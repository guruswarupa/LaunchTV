# LinuxTV Live USB - Complete Guide

## Writing the ISO to USB

### Method 1: Using `dd` (Linux/Mac)

**⚠️ WARNING: This will erase everything on the USB drive!**

1. **Insert your USB drive** (minimum 8GB recommended)

2. **Find your USB device name:**
   ```bash
   lsblk
   ```
   Look for your USB drive by size. It will be something like `/dev/sdb` or `/dev/sdc`.
   **DO NOT use a partition number like `/dev/sdb1` - use the whole device `/dev/sdb`**

3. **Write the ISO:**
   ```bash
   sudo dd if=LinuxTV.iso of=/dev/sdX bs=4M status=progress oflag=sync
   ```
   Replace `/dev/sdX` with your actual USB device (e.g., `/dev/sdb`)

4. **Wait for completion** - This may take 5-15 minutes depending on USB speed

5. **Safely remove:**
   ```bash
   sudo sync
   ```

### Method 2: Using Etcher (Recommended for beginners)

1. Download [Balena Etcher](https://www.balena.io/etcher/)
2. Open Etcher
3. Select the LinuxTV ISO file
4. Select your USB drive
5. Click "Flash!"

### Method 3: Using Ventoy (Multiple ISOs on one USB)

1. Download [Ventoy](https://www.ventoy.net/)
2. Install Ventoy to your USB drive
3. Copy the LinuxTV ISO file to the USB drive
4. Boot and select LinuxTV from Ventoy menu

## Setting Up Persistence (Optional)

After writing the ISO, you can set up persistence to save your changes:

```bash
sudo ./create-persistence.sh
```

**⚠️ IMPORTANT:**
- The script will create a **NEW partition** in the free space after the ISO
- It will **NOT** overwrite the bootable ISO partition
- After running the script, **unplug and re-plug** the USB drive
- The script is safe and preserves the bootable ISO

This will:
- Analyze the USB drive layout
- Create a new partition in the unused space
- Format it as ext4 with label "persistence"
- Enable persistence so your files and settings are saved

## Troubleshooting: USB Not Showing in BIOS/UEFI

### If your USB drive doesn't appear in the boot menu:

#### 1. **Check Secure Boot Settings**
   - Enter BIOS/UEFI setup (usually F2, F12, DEL, or ESC during boot)
   - Find "Secure Boot" option
   - **Disable Secure Boot**
   - Save and exit

#### 2. **Check Boot Mode**
   - The LinuxTV ISO supports both **UEFI** and **Legacy BIOS**
   - Try switching boot modes:
     - If currently in UEFI mode, try "Legacy" or "CSM" mode
     - If currently in Legacy mode, try "UEFI" mode
   - Save and reboot

#### 3. **Verify ISO was Written Correctly**
   ```bash
   # Check if USB is bootable
   sudo fdisk -l /dev/sdX
   
   # You should see partitions listed
   ```

#### 4. **Try a Different USB Port**
   - Use USB 2.0 port instead of USB 3.0 (or vice versa)
   - Avoid USB hubs - plug directly into motherboard
   - Try ports on the back of the computer

#### 5. **Try a Different USB Drive**
   - Some USB drives have compatibility issues
   - Try a different brand or model
   - Use a quality USB drive (SanDisk, Kingston, Samsung)

#### 6. **Re-write the ISO**
   Sometimes the write process fails:
   ```bash
   # First, verify the ISO
   sha256sum LinuxTV.iso
   
   # Re-write with verification
   sudo dd if=LinuxTV.iso of=/dev/sdX bs=4M status=progress oflag=sync
   sudo sync
   ```

#### 7. **Check Fast Boot**
   - In BIOS/UEFI, disable "Fast Boot"
   - This can prevent USB detection
   - Save and reboot

#### 8. **Enable USB Boot**
   - In BIOS/UEFI, look for:
     - "USB Boot" - Enable it
     - "Boot from USB" - Enable it
     - "External Device Boot" - Enable it
   - Save and exit

## Boot Options Explained

When you boot from the USB, you'll see:

1. **Boot LinuxTV Live (with Persistence)** - DEFAULT
   - Saves all your changes, files, and settings
   - Use this for regular usage

2. **Boot LinuxTV Live (No Persistence)**
   - Fresh session every time
   - Nothing is saved
   - Good for testing or troubleshooting

3. **Boot LinuxTV Live (fail-safe)**
   - Disables advanced features
   - Use if normal boot fails
   - Good for older hardware

## Default Login Credentials

- **Username:** linuxtv
- **Password:** linuxtv

## After Booting

Once LinuxTV boots:
1. The system will auto-login
2. Connect to WiFi using the network manager
3. Start using Kodi, VLC, or browse with Brave
4. Your changes will be saved (if using persistence)

## Need Help?

If you're still having issues:
1. Check the build log: `cat build.log`
2. Verify your ISO is not corrupted
3. Try the troubleshooting steps above
4. Test the USB on a different computer
