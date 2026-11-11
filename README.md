# iPhone USB GPS

![iPhone USB GPS: set a fake iPhone location from a Mac over USB with gps-set](docs/images/social-preview.png)

[![Open source license: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE) · [简体中文](README.zh-CN.md)

Set a simulated iPhone location from a Mac over USB using DVT LocationSimulation. Enter latitude and longitude directly or search for a place with Apple Maps. Each new location reuses the live DVT session. If the phone disconnects, the tool keeps a local record so you can clear the simulation after reconnecting the same device.

## Install

You need macOS 26 or later, the Xcode Command Line Tools, and uv. The project uses Python 3.14 and pins [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) to 11.51.0. The USB connection targets iOS 17.4 or later. DVT requests and device location logs were checked on iOS 27.2.

```sh
git clone https://github.com/sicaboy/iphone-usb-gps.git
cd iphone-usb-gps
./install.sh
```

The installer creates a virtual environment and builds the Apple Maps search helper in the checkout. It links the commands into `~/.local/bin`. Add that directory to your PATH and keep the checkout in place. To use a different command directory, run `GPS_BIN_DIR=/absolute/path ./install.sh`.

## Use

1. Connect the iPhone by USB, unlock it, and confirm the trust prompt if shown.
2. On first use, enable Developer Mode in Settings → Privacy & Security. Restart, unlock the phone, and confirm that Developer Mode should be enabled.
3. Run a command below and use the location arrow in Apple Maps on the iPhone to check the blue dot.

```sh
gps-status
gps-set "Melbourne VIC, Australia"
gps-set "Tokyo"
gps-set -- "-33.8688,151.2093"
gps-reset
```

- `gps-set` sets a place or decimal coordinates in latitude, longitude order. Place queries go to Apple Maps. Coordinate input skips that lookup. Add a region, postal code, or country to distinguish similarly named places.
- `gps-status` reports the USB device, Developer Mode, session PID, and target. A DVT reply confirms the request. The blue dot confirms what Apple Maps displays.
- `gps-reset` sends a DVT clear request and closes the session. After a disconnect, reconnect and unlock the same iPhone before running it.

The first DVT connection may download a developer disk image and install it on the device after Apple signs it. The tool opens a userspace RSD/RemoteXPC tunnel on demand. It requires neither sudo nor a permanent service. Session state and logs are stored in `~/Library/Application Support/iphone-usb-gps/`.

### If the Developer Mode toggle is missing

Connect only the target iPhone, unlock it, and run this command from the checkout. Then reopen Settings → Privacy & Security on the phone.

```sh
.venv/bin/pymobiledevice3 amfi reveal-developer-mode
```

## FAQ

### How do I fake or change my iPhone's GPS location from a Mac?
Connect the iPhone by USB, enable Developer Mode, then run `gps-set "Tokyo"` or `gps-set -- "-33.8688,151.2093"`. See [Use](#use).

### Does it need a jailbreak, sudo or an app on the iPhone?
No. It uses DVT LocationSimulation through an on-demand userspace RSD/RemoteXPC tunnel, with no sudo and no permanent service.

### Which iOS and macOS versions are supported?
macOS 26 or later with the Xcode Command Line Tools and uv. The USB connection targets iOS 17.4 or later. DVT requests were checked on iOS 27.2.

### How do I go back to my real location?
Run `gps-reset`. It sends a DVT clear request and closes the session. After a disconnect, reconnect and unlock the same iPhone first.

### The Developer Mode toggle is missing. What now?
Connect only the target iPhone, unlock it, and run `.venv/bin/pymobiledevice3 amfi reveal-developer-mode` from the checkout. See [If the Developer Mode toggle is missing](#if-the-developer-mode-toggle-is-missing).

### How do I confirm the location changed?
Open Apple Maps on the iPhone and tap the location arrow. The blue dot shows what Apple Maps displays; a DVT reply only confirms the request.

## Codex Skill

Copy `skills/iphone-usb-gps` into `~/.codex/skills/`. In a new chat, ask to set the iPhone location to New York, check the iPhone GPS session, or restore its real location. The Skill calls the same commands.

## License

This project is available under [GPL-3.0-or-later](LICENSE).
