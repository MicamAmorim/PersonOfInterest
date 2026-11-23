#!/usr/bin/env bash
set -eu
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
runtime=${POI_LITE_HOME:-"$HOME/.local/share/poi-lite"}

case "$(uname -m)" in
  aarch64|arm64)
    arch=arm64
    go2rtc_hash=af416f22b21a24ab83b8d78642190b4932ae695b4e386853f11d1b0319781763
    tailscale_hash=d6bed2720310b328b861f943d7b4016c5358a9bad60575eb51e8143b79068484
    ;;
  x86_64|amd64)
    arch=amd64
    go2rtc_hash=20b46c6910734cb05ecefb234066f36868ff19b42ba1418a7a32e13a3e035712
    tailscale_hash=e56693ff74a64f2591b7e819c280635a100aae1ddfb0ef058fcd052b7cd8d16c
    ;;
  *) echo 'Use um ambiente Linux de 64 bits (ARM64 ou AMD64).' >&2; exit 1 ;;
esac

if ! command -v python3 >/dev/null || ! command -v ffmpeg >/dev/null || ! command -v curl >/dev/null || ! command -v flock >/dev/null; then
  echo 'Instale no Debian: apt update && apt install python3 python3-venv ffmpeg curl ca-certificates util-linux' >&2
  exit 1
fi

mkdir -p -- "$runtime/bin"
scratch=$(mktemp -d "$runtime/.setup.XXXXXXXX")
trap 'rm -f -- "$scratch/go2rtc" "$scratch/tailscale.tgz" "$scratch/tailscale" "$scratch/tailscaled"; rmdir -- "$scratch"' EXIT

python3 -m venv "$runtime/venv"
"$runtime/venv/bin/python" -m pip install --disable-pip-version-check -r "$root/backend/requirements-lite.txt"

download() {
  curl --fail --silent --show-error --location --proto '=https' --retry 2 --output "$1" "$2"
  printf '%s  %s\n' "$3" "$1" | sha256sum --check --status
}

if ! printf '%s  %s\n' "$go2rtc_hash" "$runtime/bin/go2rtc" | sha256sum --check --status; then
  download "$scratch/go2rtc" "https://github.com/AlexxIT/go2rtc/releases/download/v1.9.15/go2rtc_linux_$arch" "$go2rtc_hash"
  install -m 700 "$scratch/go2rtc" "$runtime/bin/go2rtc"
fi

tailscale_release=tailscale_1.104.7_$arch
if [ ! -x "$runtime/bin/tailscale" ] || [ ! -x "$runtime/bin/tailscaled" ]; then
  download "$scratch/tailscale.tgz" "https://pkgs.tailscale.com/stable/$tailscale_release.tgz" "$tailscale_hash"
  for binary in tailscale tailscaled; do
    tar -xzOf "$scratch/tailscale.tgz" "$tailscale_release/$binary" > "$scratch/$binary"
    install -m 700 "$scratch/$binary" "$runtime/bin/$binary"
  done
fi

printf 'Servidor leve preparado em %s\n' "$runtime"
