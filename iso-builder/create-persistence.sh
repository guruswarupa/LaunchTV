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

# Find where the last partition ends
LAST_SECTOR=$(sfdisk -l "$USB_DEVICE" | tail -n +2 | awk '{print $3}' | sort -n | tail -1)

if [ -z "$LAST_SECTOR" ]; then
    echo "Error: Could not determine partition layout"
    exit 1
fi

echo "Last partition ends at sector: $LAST_SECTOR"

# Calculate start of new partition (1MB alignment)
NEW_START=$(( (LAST_SECTOR / 2048 + 1) * 2048 ))
echo "New partition will start at sector: $NEW_START"

echo ""
echo "Creating persistence partition..."

# Create new partition using the free space
echo "${NEW_START} " | sfdisk --append "$USB_DEVICE"

# Get the new partition name (should be the last partition)
PARTITION=$(lsblk -n -o NAME "$USB_DEVICE" | tail -1)
if [[ "$PARTITION" != *"/dev/"* ]]; then
    PARTITION="/dev/$PARTITION"
fi

if [ ! -b "$PARTITION" ]; then
    echo "Error: New partition was not created"
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
