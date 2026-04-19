#!/bin/bash
# Script to flash ISO and create a persistence partition on LinuxTV Live USB

set -e

echo "=========================================="
echo "  LinuxTV Live USB Flashing & Persistence"
echo "=========================================="
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root"
    echo "Usage: sudo $0"
    exit 1
fi

ISO_FILE="live-image-amd64.hybrid.iso"

if [ ! -f "$ISO_FILE" ]; then
    echo "Error: ISO file $ISO_FILE not found in current directory."
    exit 1
fi

# Find USB devices
echo "Available disk devices:"
echo ""
lsblk -d -o NAME,SIZE,MODEL | grep -E '^sd|^vd|^nvme' || lsblk -d -o NAME,SIZE,MODEL
echo ""

echo "WARNING: This will ERASE EVERYTHING on your USB drive and then create a persistence partition."
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
echo "!!! THIS WILL DESTROY ALL DATA ON $USB_DEVICE !!!"
read -p "Type 'yes' to confirm and proceed: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Unmount any mounted partitions on the device
echo "Unmounting any existing partitions on $USB_DEVICE..."
for part in $(lsblk -lpn -o NAME "$USB_DEVICE" | tail -n +2); do
    umount "$part" 2>/dev/null || true
done

echo ""
echo "Flashing ISO to $USB_DEVICE..."
dd if="$ISO_FILE" of="$USB_DEVICE" bs=4M status=progress oflag=sync
sync

# We might need to wait for OS to recognize new partition table
sleep 3
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 2

# Now create persistence
echo ""
echo "Analyzing new partition layout..."

# We might need to wait for OS to recognize new partition table
sleep 3
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 2

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
    echo "Warning: Could not determine partition layout via lsblk. Trying fallback..."
    # Fallback to ISO file size if partitions aren't visible yet
    ISO_SIZE=$(stat -c%s "$ISO_FILE")
    LAST_SECTOR=$((ISO_SIZE / 512))
fi

echo "Last partition ends at sector: $LAST_SECTOR"

# Calculate start of new partition (1MB alignment for performance)
# 1MB = 2048 sectors
NEW_START=$(( (LAST_SECTOR / 2048 + 1) * 2048 ))
echo "New partition will start at sector: $NEW_START"

echo ""
echo "Creating persistence partition..."

# Use fdisk to create the partition. It is more lenient with hybrid ISOs than sfdisk or parted.
# n: new partition
# p: primary
# 3: partition number 3 (1 & 2 are used by ISO)
# $NEW_START: start sector
# <empty>: default to end of disk
# w: write Changes
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
# It should be the one starting at NEW_START or just the last one
PARTITION=$(lsblk -lpn -o NAME,START "$USB_DEVICE" | grep -w "$NEW_START" | awk '{print $1}')

if [ -z "$PARTITION" ]; then
    # Fallback: get the last partition
    PARTITION=$(lsblk -lpn -o NAME "$USB_DEVICE" | grep -v "^${USB_DEVICE}$" | tail -1)
fi

if [ ! -b "$PARTITION" ]; then
    echo "Error: New partition was not created or not recognized."
    echo "Please unplug and re-plug the USB drive, then run create-persistence.sh manually."
    exit 1
fi

echo "Using partition: $PARTITION"

# Wait for device node
sleep 2

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
echo "  Flashing & Persistence setup complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Please unplug and re-plug the USB drive now."
echo "This is necessary for the system to fully recognize all changes."
echo ""
echo "After re-plugging:"
echo "1. Boot from the USB drive"
echo "2. Select 'Boot LinuxTV Live (with Persistence)' from the menu"
echo "3. Your files and settings will be preserved across reboots"

