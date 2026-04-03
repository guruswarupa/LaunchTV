# LinuxTVRemote

LinuxTVRemote is the mobile controller for LinuxTV. It connects to the desktop launcher over WebSocket so you can authenticate once, navigate tiles, open items, return home, and close the currently running app from your phone.

## Start

```bash
npm install
npm run start
```

Open the project in Expo Go or a development build, then connect to the LinuxTV host with `IP:port` such as `192.168.1.100:8765`.

Set the remote username and password from the settings gear in the desktop launcher. On the phone, enter those credentials once and tap `Save & Sign In`; they are stored with `expo-secure-store` and reused automatically on future connects.

## Remote actions

- `UP`, `DOWN`, `LEFT`, `RIGHT`
- `SELECT`
- `BACK`
- `HOME`
- `CLOSE_APP`
- `SHUTDOWN`
- `REBOOT`

## App structure

- `app/(tabs)/index.tsx`: remote control screen
- `app/(tabs)/explore.tsx`: setup and pairing guide
- `app/_layout.tsx`: root navigation shell
