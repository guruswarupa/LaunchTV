#!/bin/bash
# Script to update LinuxTV Live USB with new ISO while preserving persistence partition
# This script:
# 1. Backs up the persistence partition
# 2. Flashes the new ISO
# 3. Recreates the persistence partition
# 4. Restores the persistence data

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
echo "The persistence partition will be PRESERVED."
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
else
    echo "No persistence partition found."
    echo "This script will still work, but there's no data to preserve."
    HAS_PERSIST=false
fi

echo ""
echo "WARNING: The ISO partition will be ERASED and replaced."
if [ "$HAS_PERSIST" = true ]; then
    echo "The persistence partition WILL BE BACKED UP and RESTORED."
fi
echo ""
read -p "Type 'yes' to confirm and proceed: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Backup persistence if it exists
BACKUP_FILE=""
if [ "$HAS_PERSIST" = true ]; then
    echo ""
    echo "Step 1: Backing up persistence partition..."
    
    # Create temporary backup file
    BACKUP_FILE=$(mktemp /tmp/linuxtv-persist-backup-XXXXXX.img)
    echo "Backup location: $BACKUP_FILE"
    
    # Check if partition is mounted
    MOUNT_POINT=$(findmnt -n -o TARGET "$PERSIST_PART" 2>/dev/null || echo "")
    
    if [ -n "$MOUNT_POINT" ]; then
        echo "Partition is mounted at: $MOUNT_POINT"
        echo "Calculating used space..."
        USED_SPACE=$(df -BM "$MOUNT_POINT" | tail -1 | awk '{print $3}' | sed 's/M//')
        TOTAL_SPACE=$(df -BM "$MOUNT_POINT" | tail -1 | awk '{print $2}' | sed 's/M//')
        echo "Used: ${USED_SPACE}MB / ${TOTAL_SPACE}MB"
        echo ""
        
        # Unmount for clean backup
        echo "Unmounting persistence partition..."
        umount "$PERSIST_PART"
        sleep 2
    fi
    
    # Create compressed backup
    echo "Creating backup (this may take a few minutes)..."
    # Use dd with compression to backup only the partition
    dd if="$PERSIST_PART" bs=4M status=progress | gzip > "${BACKUP_FILE}.gz" 2>&1
    rm -f "$BACKUP_FILE"
    BACKUP_FILE="${BACKUP_FILE}.gz"
    
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | awk '{print $1}')
    echo "Backup complete! Size: $BACKUP_SIZE"
fi

# Unmount all partitions on the device
echo ""
echo "Step 2: Preparing device for update..."
for part in $(lsblk -lpn -o NAME "$USB_DEVICE" | tail -n +2); do
    echo "Unmounting $part..."
    umount "$part" 2>/dev/null || true
done
sleep 2

# Flash new ISO
echo ""
echo "Step 3: Flashing new ISO to $USB_DEVICE..."
dd if="$ISO_FILE" of="$USB_DEVICE" bs=4M status=progress oflag=sync
sync

# Wait for partition table to be recognized
echo "Waiting for system to recognize new partition table..."
sleep 3
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 2

# Get the end of the last ISO partition
echo ""
echo "Step 4: Analyzing new partition layout..."

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
echo "Step 5: Creating persistence partition..."

(
echo n
echo p
echo 3
echo "$NEW_START"
echo ""
echo w
) | fdisk "$USB_DEVICE" || echo "Note: fdisk finished with some warnings (normal for hybrid ISOs)"

# Wait for partition to be recognized
echo "Waiting for kernel to recognize new partition..."
sleep 5
partprobe "$USB_DEVICE" 2>/dev/null || true
sleep 3

# Get the new partition
NEW_PART=$(lsblk -lpn -o NAME,START "$USB_DEVICE" | grep -w "$NEW_START" | awk '{print $1}')

if [ -z "$NEW_PART" ]; then
    NEW_PART=$(lsblk -lpn -o NAME "$USB_DEVICE" | grep -v "^${USB_DEVICE}$" | tail -1)
fi

if [ ! -b "$NEW_PART" ]; then
    echo "Error: New partition was not created or not recognized."
    echo "Please unplug and re-plug the USB drive, then recreate persistence manually."
    exit 1
fi

echo "New persistence partition: $NEW_PART"

# Format as ext4
echo ""
echo "Step 6: Formatting persistence partition..."
mkfs.ext4 -F -L persistence "$NEW_PART"

# Restore backup if it exists
if [ "$HAS_PERSIST" = true ] && [ -f "$BACKUP_FILE" ]; then
    echo ""
    echo "Step 7: Restoring persistence data..."
    
    MOUNT_POINT=$(mktemp -d)
    mount "$NEW_PART" "$MOUNT_POINT"
    
    echo "Extracting backup to persistence partition..."
    gunzip -c "$BACKUP_FILE" | dd of="$NEW_PART" bs=4M status=progress 2>&1
    
    # Check if persistence.conf exists, if not create it
    echo "Verifying persistence configuration..."
    if [ ! -f "$MOUNT_POINT/persistence.conf" ]; then
        echo "/ union" > "$MOUNT_POINT/persistence.conf"
        echo "Created new persistence.conf"
    fi
    
    umount "$MOUNT_POINT"
    rmdir "$MOUNT_POINT"
    
    # Clean up backup file
    echo "Cleaning up backup file..."
    rm -f "$BACKUP_FILE"
    
    echo "Persistence data restored successfully!"
else
    # Create fresh persistence.conf
    echo ""
    echo "Step 7: Setting up fresh persistence..."
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
    echo "Your persistence data has been preserved."
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
