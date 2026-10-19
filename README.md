# PersonOfInterest

PersonOfInterest é um NVR local-first para câmeras IP com visão computacional, tracking persistente, identificação facial/corporal, PTZ, alertas, Web Push e o assistente local Tonho.

O projeto foi desenhado para manter câmera, embeddings, histórico, credenciais e regras no computador do usuário. A exposição remota recomendada é via **Tailscale**, sem publicar diretamente o servidor na internet.

> Estado atual: desenvolvimento V5 em validação real. O fluxo principal do projeto continua sendo instalação por Git + `setup.ps1`/`start.ps1`. O empacotamento PyInstaller existe para gerar executáveis de distribuição, mas deve ser validado no sistema operacional alvo antes de uma release pública.

---

## Principais recursos

- FastAPI + SQLite
- go2rtc para restream local, WebRTC/MSE e talkback
- descoberta e cadastro de câmeras RTSP/ONVIF
- YOLOX-Tiny ONNX para detecção de pessoas
- tracking persistente com reassociação após oclusões curtas
- PTZ manual, Home e auto-follow com suavização/predição
- YuNet + SFace para Face ReID
- OSNet para Body ReID temporal, sempre tratado como evidência provável
- galeria de referências confiáveis, quarentena e desativadas
- hard-negatives para falsos positivos recorrentes
- Timeline com filtros e curadoria manual
- regras de alerta por pessoa/câmera/horário e regras espaciais
- Web Push
- campainha manual e acionada por alertas espaciais
- Tonho com wake word, conversa, TTS, comandos locais e pesquisa web
- PWA instalável em Android, iOS/iPadOS e navegadores desktop compatíveis
- suporte recomendado a acesso remoto por Tailscale Serve

Todos os dados locais sensíveis ficam fora do Git, em `data/` na instalação por código-fonte.

---

# 1. Instalação por Git — Windows

## Requisitos

- Windows 10/11
- Python 3.11+
- Git
- acesso à internet na primeira instalação para dependências/modelos

Clone o repositório:

```powershell
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
```

Execute o setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

O setup:

1. cria `.venv`;
2. instala as dependências Python;
3. baixa `go2rtc.exe` se necessário;
4. prepara `data/`;
5. pergunta opcionalmente se este computador deve iniciar o servidor automaticamente com o Windows.

Ao final, caso o autostart não tenha sido habilitado, inicie manualmente:

```powershell
.\start.ps1
```

Interface local:

```text
http://localhost:8080
```

## Setup não interativo quanto ao autostart

Para já habilitar o servidor automático:

```powershell
.\setup.ps1 -ServerAutostart Enable
```

Para instalar sem perguntar sobre autostart:

```powershell
.\setup.ps1 -ServerAutostart Disable
```

---

# 2. Atualizar uma instalação existente

```powershell
git fetch origin
git pull
```

Depois reinicie o servidor normalmente.

Se o ambiente já está completamente instalado e você quer apenas ativar inicialização automática, não precisa rodar o setup novamente:

```powershell
.\install-server-autostart.ps1
```

Esse é o fluxo recomendado para uma instalação já funcional.

---

# 3. Servidor automático no Windows

O PersonOfInterest pode iniciar em segundo plano quando o usuário entra no Windows.

A implementação usa o **Agendador de Tarefas do Windows** e não substitui o motor do projeto por um serviço separado. A tarefa simplesmente executa o mesmo `start.ps1` já usado manualmente, com `-NoBrowser`.

## Ativar

```powershell
.\install-server-autostart.ps1
```

O script registra a tarefa:

```text
PersonOfInterest Server
```

Ela executa:

```powershell
start.ps1 -NoBrowser
```

O instalador tenta iniciar a tarefa imediatamente. Para apenas registrar e deixar a primeira execução para o próximo logon:

```powershell
.\install-server-autostart.ps1 -NoStart
```

## Comportamento

Ao entrar no Windows:

```text
Windows login
    ↓
Task Scheduler
    ↓
server-autostart-runner.ps1
    ↓
/api/health já responde?
    ├─ sim → não cria segunda instância
    └─ não → start.ps1 -NoBrowser
                 ↓
            go2rtc + FastAPI + visão + Tonho
```

A tarefa:

- roda somente para o usuário que a instalou;
- não abre navegador;
- ignora uma segunda execução simultânea;
- tenta reiniciar até 3 vezes se o processo falhar;
- permite execução em notebook usando bateria;
- não exige que você mantenha um PowerShell aberto.

## Logs do autostart

```text
data/logs/server-autostart.log
```

Para acompanhar pelo PowerShell:

```powershell
Get-Content .\data\logs\server-autostart.log -Wait
```

## Verificar a tarefa

```powershell
Get-ScheduledTask -TaskName "PersonOfInterest Server"
Get-ScheduledTaskInfo -TaskName "PersonOfInterest Server"
```

## Remover

```powershell
.\remove-server-autostart.ps1
```

A remoção exclui apenas a inicialização automática. Ela **não encerra** uma instância que já esteja rodando naquele momento.

> Por que no logon e não como serviço de sistema? Neste estágio isso evita credenciais administrativas, mantém acesso natural ao perfil/cache do usuário e reutiliza exatamente o mesmo caminho de inicialização que já é usado e testado manualmente. Um serviço nativo do Windows pode ser criado futuramente para instalações sem sessão de usuário.

---

# 4. Inicialização manual

Com navegador:

```powershell
.\start.ps1
```

Somente servidor:

```powershell
.\start.ps1 -NoBrowser
```

`start.ps1` também verifica dependências e garante os modelos ONNX locais necessários.

Modelos principais:

- `yolox_tiny.onnx`
- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`
- `osnet_x0_25_msmt17.onnx`

Os modelos Whisper são baixados pelo `faster-whisper` apenas quando o usuário seleciona um modelo que ainda não existe no cache local.

---

# 5. Tailscale e acesso remoto

O uso recomendado é manter o PersonOfInterest privado dentro da sua tailnet.

Com o servidor em execução:

```powershell
.\tailscale-serve.ps1
```

Ver status:

```powershell
.\tailscale-serve.ps1 -Status
```

Desativar:

```powershell
.\tailscale-serve.ps1 -Off
```

O script publica `localhost:8080` via HTTPS dentro da tailnet, normalmente em uma URL como:

```text
https://nome-do-pc.alguma-tailnet.ts.net
```

Não use `localhost` no celular: no celular, `localhost` aponta para o próprio aparelho.

Evite Tailscale Funnel/publicação pública para este tipo de instalação doméstica. Prefira Tailscale Serve + ACLs da tailnet.

---

# 6. PWA — instalar como aplicativo

PersonOfInterest é uma **Progressive Web App (PWA)**.

A PWA continua sendo um aplicativo web: ela não tem permissão para iniciar diretamente `start.ps1` ou executar processos do sistema operacional. Por isso, no computador servidor, o autostart do Windows é independente da PWA.

## Android / Chrome / Edge

Abra a URL HTTPS do Tailscale e use **Instalar app / Adicionar à tela inicial**. Quando o navegador expõe o prompt nativo, a própria interface do PersonOfInterest também pode oferecer o botão de instalação.

## iPhone / iPad

No Safari:

```text
Compartilhar → Adicionar à Tela de Início
```

Abra depois pelo ícone criado. Web Push no iOS deve ser configurado a partir do web app instalado quando suportado pela versão do sistema.

## Desktop

Chrome/Edge e outros navegadores compatíveis podem instalar a PWA. No computador que também é o servidor, use em conjunto com:

```powershell
.\install-server-autostart.ps1
```

Assim o backend sobe sozinho no login e o ícone da PWA funciona apenas como cliente/interface, que é a separação correta entre servidor e navegador.

---

# 7. Áudio e talkback

Por padrão:

- o navegador não recebe permissão permanente de microfone no viewer;
- ouvir a câmera é uma ação explícita;
- falar com a câmera usa push-to-talk;
- durante o push-to-talk a escuta local é suspensa;
- ao soltar o botão, tracks de microfone, WebRTC e WebSocket de talkback são encerrados.

Isso reduz loops acústicos e evita que áudio do PC/celular continue vazando para o alto-falante da câmera depois da fala.

Talkback continua dependendo do firmware individual da câmera aceitar DVRIP/RTSP backchannel.

---

# 8. Compilar executável Windows

O projeto inclui um build PyInstaller para gerar uma distribuição **one-folder**.

Isso é intencional: modelos, bibliotecas nativas, frontend e go2rtc tornam um `--onefile` muito grande e obrigariam extração temporária em toda execução.

## Build padrão

No Windows:

```powershell
.\build-windows.ps1
```

Saída:

```text
dist/PersonOfInterest/PersonOfInterest.exe
```

A pasta `dist/PersonOfInterest/` inteira faz parte da aplicação e deve ser distribuída junto com o `.exe`.

O pacote inclui:

- backend Python congelado pelo PyInstaller;
- frontend/PWA;
- dependências Python necessárias;
- go2rtc para Windows.

Por padrão os quatro modelos ONNX não são embutidos; eles são baixados uma única vez no primeiro uso do executável.

## Build Windows com modelos ONNX embutidos

```powershell
.\build-windows.ps1 -BundleModels
```

Isso aumenta bastante o tamanho da distribuição, mas permite que os modelos principais de visão já façam parte do pacote.

Os modelos Whisper **não** são empacotados, porque dependem da escolha por câmera/usuário e podem ser muito grandes. Eles continuam usando o cache normal do `faster-whisper`.

---

# 9. Compilar executável Linux

PyInstaller não faz cross-compile entre Windows e Linux neste fluxo. Para gerar o executável Linux, execute o build em um sistema Linux da mesma arquitetura desejada.

Arquiteturas atualmente tratadas pelo script:

- x86_64/amd64
- arm64/aarch64

Primeiro torne o script executável:

```bash
chmod +x build-linux.sh
```

Build padrão:

```bash
./build-linux.sh
```

Saída:

```text
dist/PersonOfInterest/PersonOfInterest
```

Com modelos ONNX incluídos:

```bash
./build-linux.sh --bundle-models
```

O script baixa o binário go2rtc adequado à arquitetura atual e usa um ambiente isolado `.build-venv-linux`.

---

# 10. Arquitetura do pacote executável

O build usa:

```text
packaging/launcher.py
packaging/PersonOfInterest.spec
packaging/requirements-build.txt
```

Fluxo do launcher empacotado:

```text
PersonOfInterest.exe / PersonOfInterest
        ↓
servidor já responde em :8080?
        ├─ sim → abre a interface e não duplica o servidor
        └─ não
             ↓
        garante modelos
             ↓
        inicia go2rtc
             ↓
        inicia FastAPI/uvicorn
             ↓
        abre navegador (exceto --no-browser)
```

Opções do executável:

```text
--no-browser
--port 8080
```

## Dados persistentes do pacote

Para não armazenar banco/credenciais dentro da pasta PyInstaller, a versão empacotada usa por padrão:

Windows:

```text
%LOCALAPPDATA%\PersonOfInterest\data
```

Linux:

```text
$XDG_DATA_HOME/personofinterest/data
```

ou, quando `XDG_DATA_HOME` não está definido:

```text
~/.local/share/personofinterest/data
```

É possível substituir o local explicitamente:

Windows:

```powershell
$env:POI_DATA_DIR = "D:\PersonOfInterestData"
.\PersonOfInterest.exe
```

Linux:

```bash
POI_DATA_DIR=/srv/personofinterest/data ./PersonOfInterest
```

## SearXNG no pacote

O executável não embute Docker/SearXNG. Caso `SEARXNG_URL` esteja configurado no ambiente, Tonho pode continuar usando o serviço externo/local correspondente. Caso contrário, os fallbacks gratuitos existentes permanecem disponíveis.

---

# 11. Estrutura dos dados na instalação por Git

```text
data/
├── person_of_interest.db
├── events/
├── faces/
├── models/
├── assistant_audio/
├── vapid/
└── logs/
```

Esses dados são ignorados pelo Git.

Nunca publique `data/` em um repositório público: ele pode conter credenciais de câmera, dados biométricos, histórico e material de Web Push.

---

# 12. Portas locais

```text
8080/tcp       API + frontend/PWA + WebSocket proxy
1984/tcp       go2rtc API local
8554/tcp       go2rtc RTSP local
8555/tcp+udp   WebRTC media transport
```

Com Tailscale Serve, o navegador usa HTTPS pela URL `*.ts.net` enquanto o backend continua local.

---

# 13. Desenvolvimento e validação

Compilar sintaxe do backend:

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
```

Executar testes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

No Linux, use o Python da venv correspondente.

Para mudanças envolvendo câmera, PTZ, talkback, WebRTC, Face/Body ReID e wake word, testes unitários não substituem validação no hardware real.

---

# 14. Build vs. instalador

Os scripts `build-windows.ps1` e `build-linux.sh` geram executáveis/distribuições, mas **não são ainda um instalador gráfico**.

Hoje existem três fluxos diferentes:

```text
Desenvolvimento / Git
    → setup.ps1 + start.ps1

Servidor Windows permanente via Git
    → install-server-autostart.ps1

Distribuição compilada
    → build-windows.ps1 / build-linux.sh
```

Um futuro `PersonOfInterest-Setup.exe` poderá reutilizar essas mesmas rotinas para:

- escolher Cliente ou Servidor;
- copiar o build compilado;
- criar atalhos;
- registrar autostart;
- configurar Tailscale;
- instalar/desinstalar de forma tradicional.

A lógica de servidor automático foi separada justamente para que esse futuro instalador possa reaproveitá-la sem reescrever o motor do projeto.

---

# 15. Privacidade e segurança

Face embeddings e amostras corporais são identificadores biométricos/sensíveis. Recomendações:

- mantenha `data/` privado;
- use senhas fortes nas câmeras;
- não exponha RTSP/go2rtc diretamente à internet;
- use Tailscale ACLs;
- proteja backups do SQLite e das imagens;
- revise quem tem acesso à tailnet;
- não versiona `.env`, banco, VAPID privado ou credenciais.

PersonOfInterest foi desenhado para execução local; manter essa fronteira reduz significativamente a superfície de exposição.
