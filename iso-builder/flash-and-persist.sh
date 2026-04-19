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

# Get the size of the disk in sectors
DISK_SECTORS=$(blockdev --getsz "$USB_DEVICE")
echo "Disk size: $DISK_SECTORS sectors"

# Find where the last partition ends
LAST_SECTOR=$(sfdisk -l "$USB_DEVICE" | grep -v '^Disk' | grep -v '^Units' | grep -v '^Sector' | grep '^/dev/' | awk '{print $3}' | sort -n | tail -1)

if [ -z "$LAST_SECTOR" ]; then
    echo "Error: Could not determine partition layout. Sometimes this happens right after dd."
    echo "Trying alternative method..."
    LAST_SECTOR=$(parted "$USB_DEVICE" unit s print -sm | grep -v 'Error' | tail -n 1 | awk -F: '{print $3}' | tr -d 's')
    if [ -z "$LAST_SECTOR" ]; then
        echo "Still failed. You may need to run create-persistence.sh separately after unplugging and replugging the drive."
        exit 1
    fi
fi

# parted might return e.g. "1234567" string. sfdisk gives sector start + length, which we need to be careful with.
# actually, let's use parted for reliability if sfdisk output format changed, or just use the logic from the original script
# Let's revert to original logic but be careful about header lines
LAST_SECTOR=$(sfdisk -l "$USB_DEVICE" | grep '^/dev/' | grep -v "$USB_DEVICE:" | awk '{
    for(i=1;i<=NF;i++) {
        if ($i ~ /^[0-9]+$/ && $(i-1) ~ /^[0-9]+$/ && $(i-2) == "*") { print $(i-1) + $i - 1; break }
        if ($i ~ /^[0-9]+$/ && $(i-1) ~ /^[0-9]+$/ && !($(i-2) ~ /^[0-9]+$/)) { print $i; break}
    }
}' | sort -n | tail -1)

# A more robust way to get the end sector of the last partition
LAST_SECTOR=$(parted -m "$USB_DEVICE" unit s print | tail -n 1 | awk -F: '{print $3}' | tr -d 's')

echo "Last partition ends at sector: $LAST_SECTOR"

# Calculate start of new partition (1MB alignment)
# 1MB = 2048 sectors (assuming 512 byte sectors)
NEW_START=$(( (LAST_SECTOR / 2048 + 1) * 2048 ))
echo "New partition will start at sector: $NEW_START"

echo ""
echo "Creating persistence partition..."

# Create new partition using the free space
echo "${NEW_START} " | sfdisk --append "$USB_DEVICE"

# We might need to wait for OS to recognize new partition
sleep 3
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 2

# Get the new partition name (should be the last partition)
PARTITION=$(lsblk -lpn -o NAME "$USB_DEVICE" | tail -1)

if [ ! -b "$PARTITION" ]; then
    echo "Error: New partition was not created"
    echo "Please re-plug the USB drive and run create-persistence.sh manually"
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

