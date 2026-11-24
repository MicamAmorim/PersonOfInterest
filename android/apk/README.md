# POI Server Android — beta controller

**Scope:** This APK is a supervisor for the existing Android Lite Termux + Debian backend, NOT an independent native Android server. It does not bundle Python, FFmpeg, go2rtc or Tailscale. The APK starts a foreground service, monitors http://127.0.0.1:8080/api/health, and requests server restart through the official Termux RUN_COMMAND API. It can restart after BOOT_COMPLETED (generally after first unlock), subject to MIUI battery restrictions.

## Redmi 9 installation

1. Keep the working Termux/Debian installation described in ../docs/ANDROID_LITE.md (repo root docs/ANDROID_LITE.md).
2. Edit ~/.termux/termux.properties and set allow-external-apps=true. Run termux-reload-settings.
3. Install the APK. In Android settings grant POI Server the Additional Permission Run commands in Termux environment (or tap the permission button in the app).
4. In MIUI enable autostart and unrestricted battery operation for BOTH Termux and POI Server.
5. Optionally specify the existing Tailscale node hostname and save. Then tap Iniciar e manter ativo.
6. Confirm localhost:8080/API health and the app notification with the screen off; restart the phone, unlock it, and verify the service restarts.

Security: Termux RUN_COMMAND permission allows extensive access to Termux. Grant it only to trusted applications. This build is experimental and has not been validated on a Redmi 9. Starting monitoring does not guarantee uninterrupted 24/7 recording; Android may still kill Termux. Stopping monitoring does not stop an already running recorder.

## Build and release

Run: gradle -p android/apk :app:assembleDebug

The workflow .github/workflows/android-apk.yml publishes a debug-signed prerelease APK on branch feature/android-apk-controller. Debug keys may differ between builds; uninstall the old beta before installing a newer beta if Android reports a signing conflict. A production release needs persistent signing keys and device tests.