#!/usr/bin/env bash
set -eu

if ! command -v pkg >/dev/null || [ -z "${TERMUX_VERSION:-}" ]; then
  echo 'Execute este arquivo no Termux do Android, antes de entrar no Debian.' >&2
  exit 1
fi

if ! command -v proot-distro >/dev/null; then
  pkg update -y
  pkg install -y proot-distro
fi

container=poi-debian
# Go uses the reported kernel version to select the ARM32 futex syscall.
login=(proot-distro login --shared-tmp --kernel "$(uname -r)" "$container")
if ! "${login[@]}" -- true >/dev/null 2>&1; then
  if proot-distro install --help 2>&1 | grep -q -- '--architecture'; then
    case "$(dpkg --print-architecture)" in
      arm) proot-distro install --name "$container" --architecture linux/arm/v7 debian:trixie-slim ;;
      aarch64) proot-distro install --name "$container" --architecture linux/arm64 debian:trixie-slim ;;
      *) echo 'Este instalador do Termux espera um Android ARM32 ou ARM64.' >&2; exit 1 ;;
    esac
  else
    proot-distro install --override-alias "$container" debian
  fi
fi

if command -v termux-wake-lock >/dev/null; then
  termux-wake-lock || echo 'O Android não aceitou o bloqueio de suspensão do Termux.' >&2
fi
"${login[@]}" -- /bin/bash -lc '
  set -eu
  apt-get update
  apt-get install -y --no-install-recommends git python3 python3-venv ffmpeg curl ca-certificates util-linux
  repo="$HOME/PersonOfInterest"
  if [ -d "$repo/.git" ]; then
    git -C "$repo" pull --ff-only origin feature/android-lite
  else
    git clone --depth 1 --single-branch --branch feature/android-lite https://github.com/MicamAmorim/PersonOfInterest.git "$repo"
  fi
  cd -- "$repo"
  bash android/setup.sh
  exec bash android/run.sh
'
