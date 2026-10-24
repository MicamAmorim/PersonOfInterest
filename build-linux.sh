#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BUNDLE_MODELS=0
for arg in "$@"; do
  case "$arg" in
    --bundle-models) BUNDLE_MODELS=1 ;;
    *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "O build Linux deve ser executado no Linux. PyInstaller não faz cross-compile deste projeto." >&2
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) GO2RTC_ASSET="go2rtc_linux_amd64" ;;
  aarch64|arm64) GO2RTC_ASSET="go2rtc_linux_arm64" ;;
  *) echo "Arquitetura Linux ainda não suportada pelo script: $ARCH" >&2; exit 1 ;;
esac

echo "=== PersonOfInterest build — Linux $ARCH ==="

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.11+ não encontrado." >&2
  exit 1
fi

BUILD_VENV="$ROOT/.build-venv-linux"
BUILD_PYTHON="$BUILD_VENV/bin/python"
if [[ ! -x "$BUILD_PYTHON" ]]; then
  echo "Criando ambiente isolado de build..."
  "$PYTHON" -m venv "$BUILD_VENV"
fi

"$BUILD_PYTHON" -m pip install --upgrade pip
"$BUILD_PYTHON" -m pip install -r "$ROOT/backend/requirements.txt" -r "$ROOT/packaging/requirements-build.txt"

mkdir -p "$ROOT/bin"
GO2RTC="$ROOT/bin/go2rtc"
if [[ ! -x "$GO2RTC" ]]; then
  echo "Baixando $GO2RTC_ASSET para o pacote..."
  "$BUILD_PYTHON" - "$GO2RTC" "https://github.com/AlexxIT/go2rtc/releases/latest/download/$GO2RTC_ASSET" <<'PY'
import pathlib, sys, urllib.request
path = pathlib.Path(sys.argv[1])
url = sys.argv[2]
part = path.with_suffix('.part')
part.unlink(missing_ok=True)
request = urllib.request.Request(url, headers={'User-Agent': 'PersonOfInterest'})
with urllib.request.urlopen(request, timeout=120) as response, part.open('wb') as out:
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        out.write(chunk)
if part.stat().st_size < 1_000_000:
    part.unlink(missing_ok=True)
    raise SystemExit('download de go2rtc incompleto')
part.replace(path)
PY
  chmod +x "$GO2RTC"
fi

ensure_model() {
  local name="$1"
  local url="$2"
  local minimum="$3"
  local path="$ROOT/data/models/$name"
  mkdir -p "$(dirname "$path")"
  "$BUILD_PYTHON" - "$path" "$url" "$minimum" <<'PY'
import pathlib, sys, urllib.request
path = pathlib.Path(sys.argv[1])
url = sys.argv[2]
minimum = int(sys.argv[3])
if path.is_file() and path.stat().st_size >= minimum:
    raise SystemExit(0)
part = path.with_suffix(path.suffix + '.part')
part.unlink(missing_ok=True)
print(f'Baixando {path.name} para incluir no pacote...')
request = urllib.request.Request(url, headers={'User-Agent': 'PersonOfInterest'})
try:
    with urllib.request.urlopen(request, timeout=120) as response, part.open('wb') as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    if part.stat().st_size < minimum:
        raise RuntimeError('arquivo de modelo incompleto')
    part.replace(path)
except Exception:
    part.unlink(missing_ok=True)
    raise
PY
}

if [[ "$BUNDLE_MODELS" == "1" ]]; then
  ensure_model "yolox_tiny.onnx" "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx" 1000000
  ensure_model "face_detection_yunet_2023mar.onnx" "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" 150000
  ensure_model "face_recognition_sface_2021dec.onnx" "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface_2021dec.onnx" 10000000
  ensure_model "osnet_x0_25_msmt17.onnx" "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx?download=true" 700000
  export POI_BUNDLE_MODELS=1
else
  export POI_BUNDLE_MODELS=0
fi

echo "Empacotando com PyInstaller..."
"$BUILD_PYTHON" -m PyInstaller --clean --noconfirm "$ROOT/packaging/PersonOfInterest.spec"

EXE="$ROOT/dist/PersonOfInterest/PersonOfInterest"
if [[ ! -x "$EXE" ]]; then
  echo "Build concluído sem gerar $EXE" >&2
  exit 1
fi

echo
echo "Build Linux concluído."
echo "Executável: $EXE"
if [[ "$BUNDLE_MODELS" == "1" ]]; then
  echo "Modelos ONNX incluídos no pacote."
else
  echo "Modelos ONNX serão baixados uma única vez no primeiro uso."
fi
echo "Whisper continua baixando apenas os modelos selecionados pelo usuário quando necessário."
