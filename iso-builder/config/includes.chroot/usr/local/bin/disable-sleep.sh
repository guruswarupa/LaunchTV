#!/bin/bash
# Disable screen blanking and sleep completely

# Disable X11 screen blanking (only if display is available)
if [ -n "$DISPLAY" ]; then
    xset -dpms
    xset s off
    xset s noblank
fi

# Disable console blanking
setterm -blank 0 -powerdown 0 -powersave 0 </dev/tty1 2>/dev/null || true

# Disable kernel console blanking
echo -ne "\033[9;0]" > /dev/tty1 2>/dev/null || true
echo -ne "\033[9;0]" > /dev/console 2>/dev/null || true

# Disable sleep states
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# Disable screen timeout in systemd
sed -i 's/#HandleLidSwitch=suspend/HandleLidSwitch=ignore/' /etc/systemd/logind.conf 2>/dev/null || true
sed -i 's/#IdleAction=suspend/IdleAction=ignore/' /etc/systemd/logind.conf 2>/dev/null || true

echo "Screen blanking and sleep disabled"
