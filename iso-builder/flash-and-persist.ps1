# PowerShell script to flash ISO and create a persistence partition on LinuxTV Live USB
# Run as Administrator in PowerShell

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  LinuxTV Live USB Flashing & Persistence" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$ISO_FILE = "live-image-amd64.hybrid.iso"

if (-not (Test-Path $ISO_FILE)) {
    Write-Host "Error: ISO file $ISO_FILE not found in current directory." -ForegroundColor Red
    Write-Host "Current directory: $(Get-Location)" -ForegroundColor Yellow
    exit 1
}

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Error: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Find physical disks
Write-Host "Available disk devices:" -ForegroundColor Yellow
Write-Host ""
Get-PhysicalDisk | Where-Object {$_.BusType -eq 'USB'} | Format-Table -AutoSize DeviceId, FriendlyName, Size
Write-Host ""

# Also show all disks
Write-Host "All disks (be careful to select the correct USB drive!):" -ForegroundColor Yellow
Get-Disk | Format-Table -AutoSize Number, FriendlyName, Size, PartitionStyle
Write-Host ""

Write-Host "WARNING: This will ERASE EVERYTHING on your USB drive!" -ForegroundColor Red
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

Write-Host "!!! THIS WILL DESTROY ALL DATA ON DISK $diskNumber !!!" -ForegroundColor Red
$confirm = Read-Host "Type 'yes' to confirm and proceed"

if ($confirm -ne "yes") {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

# Get disk path
$diskPath = "\\.\PhysicalDrive$diskNumber"

# Offline the disk first
Write-Host ""
Write-Host "Preparing disk $diskNumber..." -ForegroundColor Yellow
Set-Disk -Number $diskNumber -IsOffline $true
Start-Sleep -Seconds 2
Set-Disk -Number $diskNumber -IsOffline $false
Start-Sleep -Seconds 2

# Flash ISO using dd for Windows or raw write
Write-Host ""
Write-Host "Flashing ISO to disk $diskNumber..." -ForegroundColor Yellow
Write-Host "This may take several minutes..." -ForegroundColor Yellow

# Check if dd is available
if (Get-Command dd -ErrorAction SilentlyContinue) {
    dd if=$ISO_FILE of=$diskPath bs=4M status=progress
} else {
    # Use PowerShell to write ISO
    Write-Host "Using PowerShell to flash ISO..." -ForegroundColor Yellow
    
    $isoBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $ISO_FILE))
    Write-Host "ISO size: $([math]::Round($isoBytes.Length / 1GB, 2)) GB" -ForegroundColor Yellow
    
    $diskStream = [System.IO.File]::Open($diskPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $bufferSize = 4 * 1024 * 1024 # 4MB buffer
        $buffer = New-Object byte[] $bufferSize
        $isoStream = [System.IO.MemoryStream]::new($isoBytes)
        $totalRead = 0
        
        while (($bytesRead = $isoStream.Read($buffer, 0, $bufferSize)) -gt 0) {
            $diskStream.Write($buffer, 0, $bytesRead)
            $totalRead += $bytesRead
            $percent = [math]::Round(($totalRead / $isoBytes.Length) * 100, 1)
            Write-Host "`rProgress: $percent% ($([math]::Round($totalRead / 1MB, 1)) MB / $([math]::Round($isoBytes.Length / 1MB, 1)) MB)" -NoNewline
        }
        Write-Host ""
        $diskStream.Flush()
    }
    finally {
        $diskStream.Close()
    }
}

Write-Host "ISO flashed successfully!" -ForegroundColor Green

# Wait for partition table to be recognized
Start-Sleep -Seconds 5

# Rescan disks
Write-Host ""
Write-Host "Rescanning disks..." -ForegroundColor Yellow
Update-HostStorageCache
Start-Sleep -Seconds 3

# Now create persistence partition
Write-Host ""
Write-Host "Creating persistence partition..." -ForegroundColor Yellow

# Get the disk again after rescan
$disk = Get-Disk -Number $diskNumber
$lastPartition = Get-Partition -DiskNumber $diskNumber | Sort-Object PartitionNumber | Select-Object -Last 1
$partitionStart = $lastPartition.Offset / 512 + ($lastPartition.Size / 512)

# Align to 1MB (2048 sectors)
$newStart = [math]::Ceiling($partitionStart / 2048) * 2048
Write-Host "New partition will start at sector: $newStart" -ForegroundColor Yellow

# Create new partition
$newPartition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -StartTime $newStart
Write-Host "Partition created: $($newPartition.DriveLetter)" -ForegroundColor Green

# Format as ext4 (requires third-party tools on Windows)
Write-Host ""
Write-Host "Formatting partition..." -ForegroundColor Yellow
Write-Host "Note: Windows cannot natively format as ext4." -ForegroundColor Yellow
Write-Host "The partition has been created but needs to be formatted on Linux." -ForegroundColor Yellow
Write-Host ""
Write-Host "Options:" -ForegroundColor Cyan
Write-Host "1. Boot the USB now and it will auto-format on first use" -ForegroundColor White
Write-Host "2. Use a tool like 'MiniTool Partition Wizard' or 'EaseUS Partition Master' to format as ext4" -ForegroundColor White
Write-Host "3. Run this script on a Linux system" -ForegroundColor White

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Flashing & Partition setup complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "IMPORTANT: The persistence partition has been created." -ForegroundColor Yellow
Write-Host "To complete setup:" -ForegroundColor Yellow
Write-Host "1. Boot from the USB drive" -ForegroundColor White
Write-Host "2. Select 'Boot LinuxTV Live (with Persistence)' from the menu" -ForegroundColor White
Write-Host "3. The system will format the partition and create persistence.conf automatically" -ForegroundColor White
Write-Host "4. Your files and settings will be preserved across reboots" -ForegroundColor White
Write-Host ""
