# Servidor leve no Android

O perfil leve serve o PersonOfInterest com cadastro de câmeras RTSP, vídeo ao vivo, gravação contínua e reprodução. O backend usa FastAPI, SQLite, go2rtc e FFmpeg. Visão computacional, reconhecimento, gravação por evento, alertas por IA e Tonho ficam no servidor completo. Para vídeo ao vivo, selecione um fluxo H.264 na câmera. O servidor repassa o vídeo sem transcodificação por padrão. O instalador seleciona os binários para Debian ARM32 (`armhf`), ARM64 ou AMD64.

## Instalar no Redmi

No Termux, o [bootstrap da branch](../android/bootstrap.sh) prepara um Debian separado (`poi-debian`), clona o repositório e inicia o POI localmente:

```bash
curl -fL https://raw.githubusercontent.com/MicamAmorim/PersonOfInterest/feature/android-lite/android/bootstrap.sh -o poi.sh && bash poi.sh
```

Para preparar o ambiente manualmente:

1. Instale o [Termux](https://github.com/termux/termux-app#installation) de uma fonte oficial, abra o app e rode:

   ```bash
   pkg update
   pkg install proot-distro
   proot-distro install debian
   proot-distro login --shared-tmp debian
   ```

2. Dentro do Debian, instale os pacotes e clone a branch. Se o repositório pedir autenticação, use a sessão GitHub do proprietário e mantenha as credenciais fora da URL e dos arquivos do projeto.

   ```bash
   apt update
   apt install git python3 python3-venv ffmpeg curl ca-certificates util-linux
   git clone --single-branch --branch feature/android-lite https://github.com/MicamAmorim/PersonOfInterest.git
   cd PersonOfInterest
   bash android/setup.sh
   bash android/run.sh
   ```

3. No navegador do próprio telefone, abra `http://127.0.0.1:8080`. Cadastre a câmera com seu endereço RTSP e selecione-a em **Ao vivo**. Para testar gravação, selecione **Contínua** na aba **Câmeras**. O perfil pausa a gravação quando o espaço livre cai abaixo de 2 GiB. O banco e os arquivos ficam na pasta privada `~/.local/share/poi-lite/data` do Debian.

O servidor e o go2rtc escutam em loopback por padrão. Mantenha os processos do Termux ativos e teste o acesso com a tela bloqueada antes de usar o aparelho como gravador. Se o Android suspender o processo, siga a documentação do [Termux:Boot](https://github.com/termux/termux-boot) para inicialização e `termux-wake-lock`.

## Acessar via Tailscale

Com o servidor rodando, abra outra sessão no Termux e rode:

```bash
proot-distro login --shared-tmp poi-debian
cd PersonOfInterest
bash android/tailnet.sh poi-redmi-teste
```

Na instalação manual, substitua `poi-debian` por `debian`.

O script inicia um nó Tailscale em modo userspace, com estado próprio. Abra o link de autenticação exibido na primeira execução, aprove o nó na tailnet e confira a URL mostrada por **Serve**. O acesso fica restrito à tailnet e às regras dela. A configuração pressupõe MagicDNS e certificados HTTPS habilitados. Teste o site e o vídeo a partir de outro dispositivo conectado à VPN, enquanto o PC ainda atende os usuários pelo endereço de produção. [Userspace networking](https://tailscale.com/docs/concepts/userspace-networking) · [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)

Nas próximas inicializações, um comando pode subir ambos os serviços. Pare as duas sessões de teste antes de usar esse modo.

```bash
POI_TAILSCALE_HOSTNAME=poi-redmi-teste bash android/run.sh
```

## Manter o endereço dos apps já instalados

O PWA usa a origem do navegador, formada por esquema, nome de host e porta. O perfil leve mantém o identificador do manifesto e o caminho inicial `/`. Se os dispositivos abriram o app pelo `https://<nome>.<tailnet>.ts.net` do PC, conserve essa URL. O Redmi pode ter outro IP `100.x`.

1. Depois de validar o Redmi no endereço temporário, anote os serviços e portas que o PC publica com `tailscale serve status`. A mudança de nome também afeta outros serviços no mesmo hostname.
2. Planeje a troca desses serviços. Na console da tailnet, renomeie o nó antigo para liberar o nome, atribua o nome original ao nó do Redmi e reinicie `android/tailnet.sh` com esse nome. Preserve a porta HTTPS anterior com `POI_HTTPS_PORT` se ela for diferente de `443`.
3. Abra o atalho já instalado em outro dispositivo e recarregue a página para atualizar o service worker. Confirme o vídeo ao vivo pela URL original antes de desligar o PC. Para voltar, devolva o nome original ao nó do PC.

Se o atalho foi instalado usando um IP literal em vez do nome HTTPS, esse IP faz parte do endereço a preservar. Uma eventual troca de IP é uma operação administrativa da tailnet e precisa ser combinada à parte. A troca de endereço preserva o atalho, enquanto as câmeras cadastradas e gravações pertencem ao banco e ao armazenamento de cada instalação. [MagicDNS](https://tailscale.com/docs/features/magicdns) · [Como o Tailscale atribui IPs](https://tailscale.com/docs/concepts/ip-and-dns-addresses)
