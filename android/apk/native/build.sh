#!/usr/bin/env bash
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cache=${POI_NATIVE_CACHE:-"$HOME/.cache/poi-apk-native"}
out="$source_dir/../app/build/generated/poiNative"
ndk="$cache/android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/bin"
go="$cache/go/bin/go"
jobs=${POI_NATIVE_JOBS:-6}
mkdir -p "$out"

build_media() {
  local abi=$1 arch=$2 compiler=$3
  local dir="$cache/ffmpeg-build-$abi"
  mkdir -p "$dir" "$out/$abi"
  cd -- "$dir"
  "$cache/ffmpeg-9.1/configure" \
    --target-os=android --arch="$arch" --enable-cross-compile \
    --cc="$ndk/$compiler" --ar="$ndk/llvm-ar" --nm="$ndk/llvm-nm" --strip="$ndk/llvm-strip" \
    --extra-ldflags='-Wl,-z,max-page-size=16384' --disable-autodetect --disable-doc \
    --disable-ffplay --disable-ffprobe --disable-avdevice --disable-everything \
    --enable-network --enable-small --enable-protocol=file,tcp,udp,rtp \
    --enable-demuxer=rtsp,mov --enable-muxer=rtp,segment,mp4 \
    --enable-parser=h264,hevc,aac --enable-decoder=h264,hevc,aac,pcm_mulaw,pcm_alaw \
    --enable-bsf=extract_extradata,aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb \
    --enable-filter=null,anull,format,aformat,buffer,abuffer,buffersink,abuffersink
  make -j "$jobs" ffmpeg
  install -m 755 ffmpeg "$out/$abi/libpoi_ffmpeg.so"
}

build_go() {
  local abi=$1 arch=$2 compiler=$3
  mkdir -p "$out/$abi"
  export GOOS=android GOARCH="$arch" GOARM=7 CGO_ENABLED=1 CC="$ndk/$compiler" GOTOOLCHAIN=local
  local ld='-s -w -extldflags=-Wl,-z,max-page-size=16384'
  cd -- "$cache/go2rtc-v1.9.15"
  "$go" build -trimpath -p "$jobs" -buildmode=pie -ldflags "$ld -checklinkname=0" -o "$out/$abi/libpoi_go2rtc.so" .
  cd -- "$source_dir/vpn"
  "$go" build -trimpath -p "$jobs" -mod=readonly -modfile="$cache/poi-acme/poi.mod" \
    -buildmode=pie -ldflags "$ld" -o "$out/$abi/libpoi_vpn.so" .
}

prepare_acme() {
  cd -- "$source_dir/vpn"
  # Tailscale excludes its ACME endpoint on standard Android clients. Include it only
  # in this embedded userspace server so browsers can validate the tailnet hostname.
  local acme="$cache/poi-acme"
  "$go" mod download -json tailscale.com | python3 "$source_dir/android-acme.py" "$acme"
  cp go.mod "$acme/poi.mod"
  cp go.sum "$acme/poi.sum"
  "$go" mod edit -modfile="$acme/poi.mod" -replace "tailscale.com=$acme/tailscale"
}

case "${1:?Informe ffmpeg ou go}" in
  ffmpeg)
    build_media armeabi-v7a arm armv7a-linux-androideabi26-clang
    build_media arm64-v8a aarch64 aarch64-linux-android26-clang
    ;;
  go)
    prepare_acme
    build_go armeabi-v7a arm armv7a-linux-androideabi26-clang
    build_go arm64-v8a arm64 aarch64-linux-android26-clang
    ;;
  *) exit 2 ;;
esac
