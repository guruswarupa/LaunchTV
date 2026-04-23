#!/bin/bash
# LinuxTV Flash Tool Launcher for Linux

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting LinuxTV Flash Tool..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required."
    echo "Install it with: sudo apt install python3 python3-tk"
    exit 1
fi

# Check if tkinter is available
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "Error: tkinter is required."
    echo "Install it with: sudo apt install python3-tk"
    exit 1
fi

# Run the flash tool
python3 "$SCRIPT_DIR/linuxtv-flash-tool.py"
