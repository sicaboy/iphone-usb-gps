#!/bin/sh
set -eu

root=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
bin_dir=${GPS_BIN_DIR:-"$HOME/.local/bin"}
case "$bin_dir" in
    /*) ;;
    *) printf '%s\n' 'GPS_BIN_DIR must be an absolute path.' >&2; exit 2 ;;
esac
if [ "$(uname -s)" != Darwin ] || ! command -v uv >/dev/null || ! xcrun --find swiftc >/dev/null 2>&1; then
    printf '%s\n' 'Installation requires macOS, uv, and the Xcode Command Line Tools.' >&2
    exit 1
fi
for name in gps-set gps-reset gps-status; do
    destination=$bin_dir/$name
    if [ -L "$destination" ]; then
        if [ "$(readlink "$destination")" = "$root/bin/gps" ]; then
            continue
        fi
        printf 'Existing command: %s\n' "$destination" >&2
        exit 1
    fi
    if [ -e "$destination" ]; then
        printf 'Existing command: %s\n' "$destination" >&2
        exit 1
    fi
done

cd "$root"
uv sync --locked --python 3.14
mkdir -p .build "$bin_dir"
swiftc -parse-as-library src/geocode.swift -o .build/geocode
for name in gps-set gps-reset gps-status; do
    destination=$bin_dir/$name
    if [ ! -L "$destination" ]; then
        ln -s "$root/bin/gps" "$destination"
    fi
done
printf 'Installed gps-set, gps-reset, and gps-status in %s\n' "$bin_dir"
case ":${PATH:-}:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add %s to your PATH.\n' "$bin_dir" ;;
esac
