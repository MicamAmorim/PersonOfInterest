# POI Server para Android

O APK reúne o backend do POI Lite, a interface web, o interpretador Python, o go2rtc, o FFmpeg e um nó Tailscale em userspace. O servidor usa o armazenamento privado do app para câmeras, gravações e estado da VPN.

## Instalar e iniciar

1. Instale `POI-Server-Android.apk` a partir de [GitHub Releases](https://github.com/MicamAmorim/PersonOfInterest/releases). O APK inclui ARM32 (`armeabi-v7a`) e ARM64 (`arm64-v8a`) e requer Android 8 ou posterior.
2. Abra **POI Server** e toque em **Iniciar servidor**. A notificação indica que o serviço está ativo. O app tenta iniciar novamente após o Android concluir a inicialização. Em aparelhos Xiaomi, habilite a inicialização automática do POI Server nas configurações do aparelho quando o MIUI exigir.
3. Toque em **Abrir POI neste aparelho** para abrir `http://127.0.0.1:18080`. O botão **Encontrar câmeras** procura na rede local do aparelho. Cadastre o fluxo RTSP para usar o vídeo ao vivo e a gravação contínua.
4. Para acessar pela VPN, salve um nome novo, como `poi-redmi-apk`, e toque em **Autorizar no Tailscale** quando o botão estiver ativo. Entre na tailnet e use **Abrir endereço HTTPS**. A URL privada também permite instalar a interface web como PWA em outros dispositivos conectados à mesma tailnet.

O APK tem seu próprio catálogo de câmeras. O endereço de um servidor Termux existente e o estado do nó Tailscale anterior pertencem à outra instalação.

## Compilar e publicar localmente

Use WSL Linux x86_64 com Git, Python 3, `curl`, `unzip`, `tar`, `xz`, GCC e `make`. A partir do repositório, prepare o NDK e as fontes, depois compile os executáveis para os dois ABIs.

```bash
bash android/apk/native/prepare.sh
bash android/apk/native/build.sh ffmpeg
bash android/apk/native/build.sh go
```

No Windows, use JDK 17 ou 21, Python 3.11, Gradle 8.9, Android SDK Platform 35 e Build Tools 36. Defina `JAVA_HOME` e disponibilize `java` no `PATH`. Use a mesma chave de assinatura em todas as versões deste APK. O arquivo de senha e a chave devem ficar fora do Git.

```powershell
./android/apk/release-local.ps1 -Gradle C:/Gradle/bin/gradle.bat -Python C:/Python311/python.exe `
  -Sdk C:/Android/Sdk -Keystore C:/Signing/poi-android.p12 -PasswordFile C:/Signing/key-password.txt
```

O script gera o APK assinado e o SHA-256 em `dist`. Após testar o APK e enviar o commit ao GitHub, use o mesmo comando com `-Publish -FfmpegSource <caminho-do-ffmpeg-9.1.tar.xz>`. O comando usa o `gh` autenticado para anexar os arquivos diretamente à Release.

O FFmpeg 9.1 é compilado a partir do arquivo oficial, com componentes LGPL e sem bibliotecas externas GPL. O código-fonte correspondente acompanha a Release. Os parâmetros do build estão em [`native/build.sh`](native/build.sh). O go2rtc utiliza a tag `v1.9.15` do projeto AlexxIT e o executável da VPN é construído com `tailscale.com/tsnet` v1.104.7. As dependências Python são empacotadas com Chaquopy.

O build local da VPN inclui o endpoint ACME na cópia do Tailscale usada pelo APK. O tsnet precisa dele para obter o certificado do hostname da tailnet. [Discussão upstream](https://github.com/tailscale/tailscale/issues/18245)
