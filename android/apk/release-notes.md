## POI Server para Android 0.1.0

Primeira versão do servidor POI Lite empacotada em APK para Android ARM32 e ARM64. Abra **POI Server** e toque em **Iniciar servidor**. O app executa o servidor, o vídeo RTSP, a gravação contínua e a VPN dentro da própria instalação, com serviço em primeiro plano e inicialização após o boot.

Use **Encontrar câmeras** para cadastrar equipamentos na rede local. Para acesso privado por HTTPS, escolha um nome de nó e autorize o Tailscale pela interface do APK. O comando **Instalar app** na interface web instala o PWA no dispositivo visitante.

As câmeras, as gravações e o nó da VPN ficam no armazenamento privado do APK. Consulte [o guia de instalação e compilação](https://github.com/MicamAmorim/PersonOfInterest/tree/feature/android-apk-standalone/android/apk). O SHA-256 do APK e o código-fonte correspondente do FFmpeg 9.1 acompanham a Release.
