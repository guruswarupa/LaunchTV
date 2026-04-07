# LinuxTV ISO Builder

Builds a custom Debian Trixie-based ISO with LinuxTV, Kodi, and Stremio pre-installed.

## Requirements

- Debian or Ubuntu host system
- Root access
- ~10GB free disk space
- Internet connection (for package downloads)

## Build

```bash
cd iso-builder
sudo ./build-iso.sh
```

## Output

The ISO will be created in the `iso-builder/` directory as a `.iso` file.
Flash it to a USB drive with:

```bash
sudo dd if=live-image-amd64.hybrid.iso of=/dev/sdX bs=4M status=progress
```

Test it in QEMU before flashing to hardware:

```bash
qemu-system-x86_64 -m 2048 -cdrom live-image-amd64.hybrid.iso -boot d
```

On boot, the menu should now show these visible top-level options:

- `Boot LinuxTV Live`
- `Install LinuxTV`
- `Advanced Options`

After selecting a boot option, the loading screen uses the Linux remote app icon on a plain black splash.

When you choose `Install LinuxTV`, the installer is preseeded to create:

- Username: `linuxtv`
- Password: `linuxtvbyguru`
- Root login: disabled

## Default credentials

- Username: `linuxtv`
- Password: `linuxtvbyguru`

## Pre-installed apps

- Kodi
- Stremio
- VLC
- Brave Browser

## Notes

- Stremio is installed during the chroot hook from its official Debian package URL.
- The Stremio version is defined near the top of `config/hooks/live/0100-setup-linuxtv.hook.chroot`.
- Build on a Debian or Ubuntu host system, or inside a Debian-based container or VM.
- The `--debian-installer live` live-build option keeps the resulting image installable from the live environment.
- LinuxTV's required Python runtime dependencies are baked into the image as Debian packages, and the runtime virtualenv lives under `/opt/linuxtv/.venv` so it survives installed-system boots.
