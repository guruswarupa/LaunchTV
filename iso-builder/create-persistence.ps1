# PowerShell script to create a persistence partition on LinuxTV Live USB
# Run this script AFTER writing the ISO to USB
# Run as Administrator in PowerShell

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  LinuxTV Live USB Persistence Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Error: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Find USB devices
Write-Host "Available USB disk devices:" -ForegroundColor Yellow
Write-Host ""
Get-PhysicalDisk | Where-Object {$_.BusType -eq 'USB'} | Format-Table -AutoSize DeviceId, FriendlyName, Size
Write-Host ""

Write-Host "All disks (be careful to select the correct USB drive!):" -ForegroundColor Yellow
Get-Disk | Format-Table -AutoSize Number, FriendlyName, Size, PartitionStyle
Write-Host ""

Write-Host "WARNING: This will create a persistence partition on your USB drive." -ForegroundColor Red
Write-Host "Make sure you select the correct disk!" -ForegroundColor Red
Write-Host ""

# Ask for disk number
$diskNumber = Read-Host "Enter USB disk number (e.g., 1)"

# Validate disk
$disk = Get-Disk -Number $diskNumber -ErrorAction SilentlyContinue
if (-not $disk) {
    Write-Host "Error: Disk number $diskNumber not found" -ForegroundColor Red
    exit 1
}

# Show disk details
Write-Host ""
Write-Host "You selected: Disk $diskNumber" -ForegroundColor Yellow
$disk | Format-List Number, FriendlyName, Size, PartitionStyle
Write-Host ""
Write-Host "Partitions:" -ForegroundColor Yellow
Get-Partition -DiskNumber $diskNumber | Format-Table -AutoSize PartitionNumber, Size, Type, DriveLetter
Write-Host ""

$confirm = Read-Host "Is this correct? Type 'yes' to continue"

if ($confirm -ne "yes") {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

# Get the last partition
Write-Host ""
Write-Host "Analyzing current partition layout..." -ForegroundColor Yellow

$partitions = Get-Partition -DiskNumber $diskNumber | Sort-Object PartitionNumber
$lastPartition = $partitions | Select-Object -Last 1

Write-Host "Last partition: Number $($lastPartition.PartitionNumber), Size $([math]::Round($lastPartition.Size / 1GB, 2)) GB" -ForegroundColor Yellow

# Calculate start of new partition (1MB alignment)
$partitionStartSectors = $lastPartition.Offset / 512 + ($lastPartition.Size / 512)
$newStart = [math]::Ceiling($partitionStartSectors / 2048) * 2048

Write-Host "New partition will start at sector: $newStart" -ForegroundColor Yellow

# Create new partition
Write-Host ""
Write-Host "Creating persistence partition..." -ForegroundColor Yellow

try {
    $newPartition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -StartTime $newStart
    Write-Host "Partition created successfully!" -ForegroundColor Green
    
    # Assign a drive letter if not already assigned
    if (-not $newPartition.DriveLetter) {
        $newPartition | Add-PartitionAccessPath -AssignDriveLetter
        $newPartition = Get-Partition -DiskNumber $diskNumber | Where-Object {$_.AccessPaths -match $newPartition.AccessPaths[0]}
    }
    
    Write-Host "Partition drive letter: $($newPartition.DriveLetter)" -ForegroundColor Green
}
catch {
    Write-Host "Warning: Partition creation had issues: $_" -ForegroundColor Yellow
    Write-Host "Trying alternative method..." -ForegroundColor Yellow
    
    # Try using diskpart
    $diskpartScript = @"
select disk $diskNumber
create partition primary
exit
"@
    
    $tempFile = [System.IO.Path]::GetTempFileName()
    Set-Content -Path $tempFile -Value $diskpartScript
    diskpart /s $tempFile
    Remove-Item $tempFile
    
    Start-Sleep -Seconds 3
    $newPartition = Get-Partition -DiskNumber $diskNumber | Sort-Object PartitionNumber | Select-Object -Last 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Persistence partition created!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "IMPORTANT NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "Windows cannot format partitions as ext4 natively." -ForegroundColor Red
Write-Host "You have these options:" -ForegroundColor Cyan
Write-Host ""
Write-Host "Option 1: Boot LinuxTV USB (Recommended)" -ForegroundColor White
Write-Host "  1. Safely eject the USB drive" -ForegroundColor Gray
Write-Host "  2. Boot from the USB drive" -ForegroundColor Gray
Write-Host "  3. Select 'Boot LinuxTV Live (with Persistence)'" -ForegroundColor Gray
Write-Host "  4. The system will automatically format and setup persistence" -ForegroundColor Gray
Write-Host ""
Write-Host "Option 2: Use Third-Party Windows Tools" -ForegroundColor White
Write-Host "  - MiniTool Partition Wizard (Free)" -ForegroundColor Gray
Write-Host "  - EaseUS Partition Master (Free)" -ForegroundColor Gray
Write-Host "  - AOMEI Partition Assistant (Free)" -ForegroundColor Gray
Write-Host "  Format the new partition as ext4 with label 'persistence'" -ForegroundColor Gray
Write-Host "  Then create a file 'persistence.conf' with content: / union" -ForegroundColor Gray
Write-Host ""
Write-Host "Option 3: Use WSL (Windows Subsystem for Linux)" -ForegroundColor White
Write-Host "  If you have WSL2 installed, you can format from WSL:" -ForegroundColor Gray
Write-Host "  wsl sudo mkfs.ext4 -L persistence /dev/sdX3" -ForegroundColor Gray
Write-Host ""
