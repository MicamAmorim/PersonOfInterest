#!/usr/bin/env bash
set -eu
umask 077
runtime=${POI_LITE_HOME:-"$HOME/.local/share/poi-lite"}
name=${1:-poi-redmi-teste}
https_port=${POI_HTTPS_PORT:-443}
port=${POI_PORT:-8080}
cli="$runtime/bin/tailscale"
daemon="$runtime/bin/tailscaled"
state="$runtime/tailnet"

if [ ! -x "$cli" ] || [ ! -x "$daemon" ]; then
  echo 'Execute primeiro bash android/setup.sh dentro do Debian.' >&2
  exit 1
fi
if ! curl --fail --silent --max-time 4 "http://127.0.0.1:$port/api/health" >/dev/null; then
  echo 'Inicie primeiro bash android/run.sh usando o mesmo POI_PORT.' >&2
  exit 1
fi

mkdir -p -- "$state"
exec 9>"$state/daemon.lock"
if ! flock -n 9; then
  echo 'O Tailscale do POI já está rodando neste diretório.' >&2
  exit 1
fi

# A short guest path also fits Android's Unix socket limit with --shared-tmp.
temporary_socket=$(mktemp -d /tmp/poi-tailnet.XXXXXXXX)
socket="$temporary_socket/run.sock"
"$daemon" --tun=userspace-networking --state="$state/tailscaled.state" \
  --statedir="$state" --socket="$socket" &
pid=$!
login_pid=

cleanup() {
  if [ -n "$login_pid" ]; then
    kill "$login_pid" 2>/dev/null || true
    wait "$login_pid" 2>/dev/null || true
  fi
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f -- "$socket"
  rmdir -- "$temporary_socket"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for attempt in {1..40}; do
  if [ -S "$socket" ]; then break; fi
  if ! kill -0 "$pid" 2>/dev/null || [ "$attempt" -eq 40 ]; then
    echo 'O daemon do Tailscale não iniciou. No Termux, abra o Debian com --shared-tmp.' >&2
    exit 1
  fi
  sleep 0.25
done

"$cli" --socket="$socket" up --hostname="$name" --accept-dns=false --netfilter-mode=off &
login_pid=$!
wait "$login_pid"
login_pid=
"$cli" --socket="$socket" serve --bg --https="$https_port" "http://127.0.0.1:$port"
"$cli" --socket="$socket" serve status
wait "$pid"
