#!/bin/bash
# LinuxTV Flash Tool Launcher for macOS

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting LinuxTV Flash Tool..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required."
    echo "Please install Python from https://www.python.org/downloads/"
    exit 1
fi

# Run the flash tool
python3 "$SCRIPT_DIR/linuxtv-flash-tool.py"
