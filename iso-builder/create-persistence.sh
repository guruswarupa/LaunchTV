#!/bin/bash
# Script to create a persistence partition on LinuxTV Live USB
# Run this script AFTER writing the ISO to USB

set -e

echo "=========================================="
echo "  LinuxTV Live USB Persistence Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root"
    echo "Usage: sudo $0"
    exit 1
fi

# Find USB devices
echo "Available disk devices:"
echo ""
lsblk -d -o NAME,SIZE,MODEL | grep -E '^sd|^vd|^nvme' || lsblk -d -o NAME,SIZE,MODEL
echo ""

echo "WARNING: This will create a persistence partition on your USB drive."
echo "Make sure you select the correct device!"
echo ""

# Ask for device
read -p "Enter USB device (e.g., /dev/sdb): " USB_DEVICE

# Validate device
if [ ! -b "$USB_DEVICE" ]; then
    echo "Error: $USB_DEVICE is not a valid block device"
    exit 1
fi

# Confirm
echo ""
echo "You selected: $USB_DEVICE"
lsblk "$USB_DEVICE"
echo ""
read -p "Is this correct? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Get the last partition number
echo ""
echo "Analyzing current partition layout..."

# Get the size of the disk in sectors
DISK_SECTORS=$(blockdev --getsz "$USB_DEVICE")
echo "Disk size: $DISK_SECTORS sectors"

# Get the end of the last partition using lsblk (much more robust than sfdisk/parted for hybrid ISOs)
# START is in 512-byte sectors, SIZE is in bytes.
LAST_SECTOR=$(lsblk -nplb -o TYPE,START,SIZE "$USB_DEVICE" | awk -v dev="$USB_DEVICE" '
    $1 == "part" {
        start = $2;
        size = $3;
        end = start + (size / 512);
        if (end > max_end) max_end = end;
    }
    END { print max_end }
')

if [ -z "$LAST_SECTOR" ] || [ "$LAST_SECTOR" -eq 0 ]; then
    echo "Error: Could not determine partition layout. Sometimes the kernel doesn't see partitions on hybrid ISOs."
    echo "Try unplugging and replugging the USB drive, then run this script again."
    exit 1
fi

echo "Last partition ends at sector: $LAST_SECTOR"

# Calculate start of new partition (1MB alignment for performance)
NEW_START=$(( (LAST_SECTOR / 2048 + 1) * 2048 ))
echo "New partition will start at sector: $NEW_START"

echo ""
echo "Creating persistence partition..."

# Use fdisk to create the partition. It is more lenient with hybrid ISOs than sfdisk or parted.
(
echo n
echo p
echo 3
echo "$NEW_START"
echo ""
echo w
) | fdisk "$USB_DEVICE" || echo "Note: fdisk finished with some warnings (normal for hybrid ISOs)"

# We might need to wait for OS to recognize new partition
echo "Waiting for kernel to recognize new partition..."
sleep 5
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 3

# Get the new partition name
PARTITION=$(lsblk -lpn -o NAME,START "$USB_DEVICE" | grep -w "$NEW_START" | awk '{print $1}')

if [ -z "$PARTITION" ]; then
    # Fallback: get the last partition
    PARTITION=$(lsblk -lpn -o NAME "$USB_DEVICE" | grep -v "^${USB_DEVICE}$" | tail -1)
fi

if [ ! -b "$PARTITION" ]; then
    echo "Error: New partition was not created or not recognized"
    echo "Please re-plug the USB drive and try again"
    exit 1
fi

echo "Using partition: $PARTITION"

# Format as ext4
echo "Formatting partition as ext4..."
mkfs.ext4 -F -L persistence "$PARTITION"

# Mount and create persistence.conf
echo "Setting up persistence..."
MOUNT_POINT=$(mktemp -d)
mount "$PARTITION" "$MOUNT_POINT"
echo "/ union" > "$MOUNT_POINT/persistence.conf"
umount "$MOUNT_POINT"
rmdir "$MOUNT_POINT"

echo ""
echo "=========================================="
echo "  Persistence setup complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Please unplug and re-plug the USB drive now."
echo "This is necessary for the system to recognize the new partition."
echo ""
echo "After re-plugging:"
echo "1. Boot from the USB drive"
echo "2. Select 'Boot LinuxTV Live (with Persistence)' from the menu"
echo "3. Your files and settings will be preserved across reboots"
echo ""
echo "Note: The first partition contains the Live ISO (read-only)."
echo "The new partition is for persistence (your saved data)."
