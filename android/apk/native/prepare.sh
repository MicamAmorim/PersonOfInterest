#!/usr/bin/env bash
set -euo pipefail
cache=${POI_NATIVE_CACHE:-"$HOME/.cache/poi-apk-native"}
mkdir -p "$cache"
cd -- "$cache"

download() {
  local file=$1 url=$2 hash=$3
  if ! printf '%s  %s\n' "$hash" "$file" | sha256sum --check --status; then
    curl --fail --silent --show-error --location --proto '=https' --retry 2 --output "$file" "$url"
  fi
  printf '%s  %s\n' "$hash" "$file" | sha256sum --check
}

download ndk.zip https://dl.google.com/android/repository/android-ndk-r28c-linux.zip dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f
[[ -d android-ndk-r28c ]] || unzip -q -o ndk.zip
download go.tar.gz https://go.dev/dl/go1.27.4.linux-amd64.tar.gz 7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840
[[ -x go/bin/go ]] || tar -xzf go.tar.gz
download ffmpeg-9.1.tar.xz https://ffmpeg.org/releases/ffmpeg-9.1.tar.xz 1a4d394ae63d190a526cd052eb4415c156b5c5e2df37efab41a7de0b8fde2433
[[ -d ffmpeg-9.1 ]] || tar -xJf ffmpeg-9.1.tar.xz
[[ -d go2rtc-v1.9.15 ]] || git clone --depth 1 --branch v1.9.15 https://github.com/AlexxIT/go2rtc.git go2rtc-v1.9.15
[[ $(git -C go2rtc-v1.9.15 rev-parse HEAD) == 7c05066c90ab6ad1fccb506d5f0408aa31ebe60f ]]
