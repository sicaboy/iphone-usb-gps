---
name: iphone-usb-gps
description: Use when the user asks to set, change, reset, or check simulated GPS on their iPhone connected by USB to this Mac, including “定位到东京”, “定位到纽约”, “恢复真实定位”, and “查看 iPhone 定位状态”.
---

# iPhone USB GPS

Run the installed commands on the Mac. If the shell cannot find one, use the matching executable in `~/.local/bin`. The CLI lives in the private [sicaboy/iphone-usb-gps](https://github.com/sicaboy/iphone-usb-gps) repository.

- Set or change location with `gps-set "东京"` or `gps-set -- "-33.8688,151.2093"`. Pass the user's place name, address, suburb and postcode together as one argument. Quote or pass it as data, never interpolate it into shell code. The command resolves place names and reuses a live session.
- Restore real location with `gps-reset`. This sends DVT clear, closes the owned session, and can recover a recorded session after the same phone is reconnected.
- Inspect USB connection, Developer Mode, PID, and target with `gps-status`.

Execute the corresponding command for a direct request. If it succeeds, report the matched location, coordinates or reset result. The DVT response and a live PID only establish the command and session state. Ask the user to check the blue dot in iPhone Apple Maps when actual location needs confirmation.

For connection errors, check `gps-status` and the session log path it prints. For a locked or untrusted phone, ask the user to unlock it and follow the trust prompt if needed. If Developer Mode is off, ask the user to enable it in Settings → Privacy & Security, restart, unlock and confirm. If the toggle is missing, use the repository's README to reveal it over USB. If the session disconnected, keep the recorded target available for recovery. Use the existing installation for routine requests. The CLI uses an on-demand userspace RSD/DVT tunnel and requires no sudo or permanent service.
