#!/usr/bin/env bash
set -eu
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
runtime=${POI_LITE_HOME:-"$HOME/.local/share/poi-lite"}
python="$runtime/venv/bin/python"
go2rtc="$runtime/bin/go2rtc"
port=${POI_PORT:-8080}
bind=${POI_BIND:-127.0.0.1}

if [ ! -x "$python" ] || [ ! -x "$go2rtc" ]; then
  echo 'Execute primeiro bash android/setup.sh dentro do Debian.' >&2
  exit 1
fi

export DATA_DIR=${DATA_DIR:-"$runtime/data"}
export FRONTEND_DIR="$root/frontend"
export GO2RTC_API_URL=http://127.0.0.1:1984
export POI_PROFILE=lite
mkdir -p -- "$DATA_DIR"
exec 8>"$runtime/server.lock"
if ! flock -n 8; then
  echo 'O POI leve já está rodando neste diretório.' >&2
  exit 1
fi

if curl --silent --max-time 1 "$GO2RTC_API_URL/api/streams" >/dev/null; then
  echo 'A porta 1984 já está em uso. Pare o go2rtc anterior antes de iniciar este servidor.' >&2
  exit 1
fi

runtime_config="$runtime/go2rtc.yaml"
cat > "$runtime_config" <<'YAML'
api:
  listen: "127.0.0.1:1984"
rtsp:
  listen: "127.0.0.1:8554"
webrtc:
  listen: ""
streams: {}
YAML

"$go2rtc" -c "$runtime_config" &
go2rtc_pid=$!
backend_pid=
tailnet_pid=

cleanup() {
  if [ -n "$tailnet_pid" ]; then
    kill "$tailnet_pid" 2>/dev/null || true
    wait "$tailnet_pid" 2>/dev/null || true
  fi
  if [ -n "$backend_pid" ]; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
  kill "$go2rtc_pid" 2>/dev/null || true
  wait "$go2rtc_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for attempt in {1..25}; do
  if curl --fail --silent --max-time 1 "$GO2RTC_API_URL/api/streams" >/dev/null; then
    break
  fi
  if ! kill -0 "$go2rtc_pid" 2>/dev/null || [ "$attempt" -eq 25 ]; then
    echo 'O go2rtc não iniciou na porta 1984.' >&2
    exit 1
  fi
  sleep 0.2
done

cd -- "$root/backend"
"$python" -m uvicorn app.main_lite:app --host "$bind" --port "$port" --workers 1 \
  --ws websockets --ws-max-size 4096 --no-proxy-headers --no-access-log &
backend_pid=$!
processes=("$backend_pid" "$go2rtc_pid")
if [ -n "${POI_TAILSCALE_HOSTNAME:-}" ]; then
  (
    for attempt in {1..40}; do
      if curl --fail --silent --max-time 1 "http://127.0.0.1:$port/api/health" >/dev/null; then
        exec bash "$root/android/tailnet.sh" "$POI_TAILSCALE_HOSTNAME"
      fi
      sleep 0.25
    done
    echo 'O servidor não ficou disponível para o Tailscale.' >&2
    exit 1
  ) &
  tailnet_pid=$!
  processes+=("$tailnet_pid")
fi
wait -n "${processes[@]}"
