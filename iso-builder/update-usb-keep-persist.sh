#!/bin/bash
# Script to update LinuxTV Live USB with new ISO while preserving persistence partition
# This script:
# 1. Saves persistence partition metadata
# 2. Flashes the new ISO (overwrites partition table)
# 3. Recreates the persistence partition
# 4. No backup/restore needed - data stays intact!

set -e

echo "=========================================="
echo "  LinuxTV USB Update (Keep Persistence)"
echo "=========================================="
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root"
    echo "Usage: sudo $0"
    exit 1
fi

ISO_FILE="LinuxTV.iso"

if [ ! -f "$ISO_FILE" ]; then
    echo "Error: ISO file $ISO_FILE not found in current directory."
    echo "Please run this script from the iso-builder directory."
    exit 1
fi

# Find USB devices
echo "Available disk devices:"
echo ""
lsblk -d -o NAME,SIZE,MODEL | grep -E '^sd|^vd|^nvme' || lsblk -d -o NAME,SIZE,MODEL
echo ""

echo "This script will UPDATE your USB drive with the new ISO."
echo "The persistence partition will be PRESERVED (no backup needed)."
echo ""

# Ask for device
read -p "Enter USB device (e.g., /dev/sdb): " USB_DEVICE

# Validate device
if [ ! -b "$USB_DEVICE" ]; then
    echo "Error: $USB_DEVICE is not a valid block device"
    exit 1
fi

# Show current partitions
echo ""
echo "Current partitions on $USB_DEVICE:"
lsblk "$USB_DEVICE"
echo ""

# Check if there's a persistence partition
PERSIST_PART=$(lsblk -lpn -o NAME,LABEL "$USB_DEVICE" | grep "persistence" | awk '{print $1}')

if [ -n "$PERSIST_PART" ]; then
    echo "Found persistence partition: $PERSIST_PART"
    HAS_PERSIST=true
    
    # Get the START sector and SIZE of persistence partition
    PERSIST_START=$(lsblk -lpn -o NAME,START "$USB_DEVICE" | grep "$PERSIST_PART" | awk '{print $2}')
    PERSIST_SIZE_SECTORS=$(lsblk -lpn -o NAME,SIZE "$USB_DEVICE" | grep "$PERSIST_PART" | awk '{print $2}')
    PERSIST_SIZE_BYTES=$((PERSIST_SIZE_SECTORS * 512))
    
    echo "Persistence partition details:"
    echo "  Start sector: $PERSIST_START"
    echo "  Size: $((PERSIST_SIZE_SECTORS / 2048)) MB"
    echo ""
else
    echo "No persistence partition found."
    echo "This script will still work, but there's no data to preserve."
    HAS_PERSIST=false
fi

echo ""
echo "WARNING: The ISO partition will be ERASED and replaced."
if [ "$HAS_PERSIST" = true ]; then
    echo "The persistence partition will be RECREATED (data preserved, no backup needed)."
fi
echo ""
read -p "Type 'yes' to confirm and proceed: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Unmount all partitions on the device
echo ""
echo "Step 1: Preparing device for update..."
for part in $(lsblk -lpn -o NAME "$USB_DEVICE" | tail -n +2); do
    echo "Unmounting $part..."
    umount "$part" 2>/dev/null || true
done
sleep 2

# Flash new ISO
echo ""
echo "Step 2: Flashing new ISO to $USB_DEVICE..."
dd if="$ISO_FILE" of="$USB_DEVICE" bs=4M status=progress oflag=sync
sync

# Wait for partition table to be recognized
echo "Waiting for system to recognize new partition table..."
sleep 3
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 2

# Get the end of the last ISO partition
echo ""
echo "Step 3: Analyzing new partition layout..."

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
    echo "Warning: Could not determine partition layout. Trying fallback..."
    ISO_SIZE=$(stat -c%s "$ISO_FILE")
    LAST_SECTOR=$((ISO_SIZE / 512))
fi

echo "Last ISO partition ends at sector: $LAST_SECTOR"

# Calculate start of new partition (1MB alignment)
NEW_START=$(( (LAST_SECTOR / 2048 + 1) * 2048 ))
echo "New persistence partition will start at sector: $NEW_START"

# Create persistence partition
echo ""
echo "Step 4: Creating persistence partition..."

if [ "$HAS_PERSIST" = true ]; then
    echo "Recreating persistence partition at original location..."
    # Use the original start sector if available, otherwise use calculated position
    if [ -n "$PERSIST_START" ] && [ "$PERSIST_START" -gt "$NEW_START" ]; then
        PART_START=$PERSIST_START
        echo "Using original start sector: $PART_START"
    else
        PART_START=$NEW_START
        echo "Using calculated start sector: $PART_START"
    fi
else
    PART_START=$NEW_START
fi

(
echo n
echo p
echo 3
echo "$PART_START"
echo ""
echo w
) | fdisk "$USB_DEVICE" || echo "Note: fdisk finished with some warnings (normal for hybrid ISOs)"

# Wait for partition to be recognized
echo "Waiting for kernel to recognize new partition..."
sleep 5
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 3

# Get the new partition
NEW_PART=$(lsblk -lpn -o NAME,START "$USB_DEVICE" | grep -w "$PART_START" | awk '{print $1}')

if [ -z "$NEW_PART" ]; then
    NEW_PART=$(lsblk -lpn -o NAME "$USB_DEVICE" | grep -v "^${USB_DEVICE}$" | tail -1)
fi

if [ ! -b "$NEW_PART" ]; then
    echo "Error: New partition was not created or not recognized."
    echo "Please unplug and re-plug the USB drive, then recreate persistence manually."
    exit 1
fi

echo "New persistence partition: $NEW_PART"

# Skip formatting - just verify the partition has persistence.conf
if [ "$HAS_PERSIST" = true ]; then
    echo ""
    echo "Step 5: Verifying persistence partition..."
    
    MOUNT_POINT=$(mktemp -d)
    if mount "$NEW_PART" "$MOUNT_POINT" 2>/dev/null; then
        echo "Partition mounted successfully"
        
        # Check if persistence.conf exists
        if [ -f "$MOUNT_POINT/persistence.conf" ]; then
            echo "✓ persistence.conf found and preserved"
            cat "$MOUNT_POINT/persistence.conf"
        else
            echo "Warning: persistence.conf not found. Creating it..."
            echo "/ union" > "$MOUNT_POINT/persistence.conf"
            echo "Created new persistence.conf"
        fi
        
        umount "$MOUNT_POINT"
    else
        echo "Warning: Could not mount partition. It may need formatting."
        echo "This shouldn't happen if the partition was preserved correctly."
        echo ""
        echo "Formatting and creating fresh persistence..."
        mkfs.ext4 -F -L persistence "$NEW_PART"
        mount "$NEW_PART" "$MOUNT_POINT"
        echo "/ union" > "$MOUNT_POINT/persistence.conf"
        umount "$MOUNT_POINT"
    fi
    rmdir "$MOUNT_POINT"
else
    # Create fresh persistence
    echo ""
    echo "Step 5: Setting up fresh persistence..."
    mkfs.ext4 -F -L persistence "$NEW_PART"
    
    MOUNT_POINT=$(mktemp -d)
    mount "$NEW_PART" "$MOUNT_POINT"
    echo "/ union" > "$MOUNT_POINT/persistence.conf"
    umount "$MOUNT_POINT"
    rmdir "$MOUNT_POINT"
fi

echo ""
echo "=========================================="
echo "  Update Complete!"
echo "=========================================="
echo ""
echo "Your USB drive has been updated with the new ISO."
if [ "$HAS_PERSIST" = true ]; then
    echo "Your persistence data has been preserved (no backup/restore needed)."
else
    echo "A fresh persistence partition has been created."
fi
echo ""
echo "IMPORTANT: Please unplug and re-plug the USB drive now."
echo "This is necessary for the system to fully recognize all changes."
echo ""
echo "After re-plugging:"
echo "1. Boot from the USB drive"
echo "2. Select 'Boot LinuxTV Live (with Persistence)' from the menu"
echo "3. Your files and settings will be preserved"
echo ""
