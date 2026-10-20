# PersonOfInterest

PersonOfInterest é um NVR **local-first** para câmeras IP com visão computacional, tracking persistente, Face/Body ReID, PTZ, alertas, Web Push, gravação e o assistente local Tonho.

Câmeras, credenciais, embeddings, histórico, vídeos e regras permanecem no computador do usuário. Para acesso remoto, a recomendação é **Tailscale Serve**, sem publicar diretamente o servidor na internet.

> **Estado atual:** V5 em validação real. O fluxo principal continua sendo Git + `setup.ps1`/`start.ps1`. Os builds PyInstaller para Windows/Linux existem, mas devem ser testados no sistema operacional alvo antes de uma release pública.

---

## Principais recursos

- FastAPI + SQLite;
- go2rtc para restream local, WebRTC/MSE e talkback;
- descoberta e cadastro RTSP/ONVIF;
- YOLOX-Tiny para detecção de pessoas;
- tracking persistente com reassociação após oclusões curtas;
- PTZ manual, Home e auto-follow preditivo;
- YuNet + SFace para Face ReID;
- OSNet para Body ReID temporal, sempre como evidência provável;
- Biblioteca de Pessoas com referências confiáveis, quarentena e desativadas;
- memória persistente de falsos positivos por câmera;
- Timeline com filtros, incluindo visão separada de falsos positivos;
- retenção configurável de Timeline, imagens e referências automáticas;
- gravação contínua ou por evento, isolada do motor de visão;
- limites de retenção e espaço em disco;
- regras de alerta por pessoa/câmera/horário e regras espaciais;
- Web Push com pausa por dispositivo;
- campainha manual/espacial e comando de chegada pelo Tonho;
- Tonho com wake word, TTS, comandos locais e pesquisa web;
- PWA instalável em Android, iOS/iPadOS e desktop;
- autostart opcional do servidor no Windows;
- builds one-folder para Windows e Linux.

---

# 1. Instalação por Git — Windows

## Requisitos

- Windows 10/11;
- Python 3.11+;
- Git;
- internet na primeira instalação para dependências/modelos.

```powershell
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

O setup cria `.venv`, instala dependências, baixa go2rtc quando necessário, prepara `data/` e pergunta se o servidor deve iniciar automaticamente com o Windows.

Início manual:

```powershell
.\start.ps1
```

Somente servidor:

```powershell
.\start.ps1 -NoBrowser
```

Interface local:

```text
http://localhost:8080
```

A dependência `imageio-ffmpeg` fornece um FFmpeg utilizável pelo gravador quando não existe `ffmpeg` no PATH. Também é possível definir `FFMPEG_PATH` manualmente.

---

# 2. Atualizar uma instalação existente

```powershell
git fetch origin
git pull
```

Depois reinicie o servidor. Migrações novas são aditivas e executadas na inicialização.

Para ativar autostart em uma instalação já funcional:

```powershell
.\install-server-autostart.ps1
```

---

# 3. Autostart do servidor — Windows

Ativar:

```powershell
.\install-server-autostart.ps1
```

A tarefa `PersonOfInterest Server` executa:

```powershell
start.ps1 -NoBrowser
```

no logon do usuário. Antes de iniciar outra instância, o runner consulta `/api/health`.

Verificar:

```powershell
Get-ScheduledTask -TaskName "PersonOfInterest Server"
Get-ScheduledTaskInfo -TaskName "PersonOfInterest Server"
```

Log:

```text
data/logs/server-autostart.log
```

Remover:

```powershell
.\remove-server-autostart.ps1
```

Setup sem pergunta:

```powershell
.\setup.ps1 -ServerAutostart Enable
.\setup.ps1 -ServerAutostart Disable
```

---

# 4. Gerenciamento de armazenamento

A tela **Sistema → Gerenciamento da base** exibe uso da Timeline, gravações, referências e disco livre.

## Defaults seguros

A retenção destrutiva da Timeline vem **desativada por padrão**. A gravação de todas as câmeras também vem **desativada por padrão**.

Defaults iniciais:

```text
Retenção automática da Timeline: desativada
Timeline:                        30 dias
Máximo Timeline:                 10 GB
Faces automáticas / pessoa:      30
Bodies automáticos / pessoa:     50
Proteger referências manuais:    sim
Intervalo de limpeza:            15 min

Protótipos FP / câmera:           100
Exemplos / protótipo FP:         5

Retenção de vídeos:              30 dias
Máximo de vídeos:                500 GB
Reserva livre do sistema:        10 GB
```

Todos esses valores podem ser alterados pela interface.

### Unidades de tempo

Retenção da Timeline e dos vídeos aceita minutos, horas, dias, semanas ou meses. Para o cálculo interno de retenção, `1 mês = 30 dias`.

A duração da gravação por evento aceita segundos, minutos, horas ou dias. A duração dos segmentos contínuos aceita minutos, horas ou dias.

## Como a limpeza funciona

Quando **Ativar retenção automática da Timeline** está marcado, o `StorageManager` pode:

1. remover eventos além da retenção configurada;
2. remover os eventos mais antigos se `events/ + faces/` ultrapassarem o limite da Timeline;
3. limitar referências automáticas de face/corpo por pessoa;
4. preservar referências/eventos manuais quando **Proteger referências manuais** estiver ligado;
5. remover snapshots/crops físicos vinculados aos eventos podados;
6. remover clusters desconhecidos que ficaram completamente órfãos.

A memória persistente de falsos positivos é independente da Timeline e não some quando o evento original expira.

## Limpeza manual

A interface oferece **Executar limpeza agora**, respeitando as políticas configuradas.

## Compactar o SQLite

Excluir linhas do SQLite não reduz necessariamente `person_of_interest.db` imediatamente. A tela oferece **Compactar banco**, executando checkpoint + `VACUUM` apenas sob comando explícito.

`VACUUM` nunca roda automaticamente em background. Se o banco estiver ocupado por outra escrita, a operação é cancelada e pode ser repetida depois, em vez de interferir no motor.

---

# 5. Memória persistente de falsos positivos

O sistema mantém os hard-negatives legados e adiciona protótipos persistentes, limitados e independentes da Timeline.

Quando o usuário marca manualmente uma detecção como falso positivo:

```text
evento marcado manualmente
        ↓
Body embedding + câmera + geometria
        ↓
protótipo negativo persistente
        ↓
propagação retroativa conservadora
        ↓
futuros matches fortes → false_positive
        ↓
sem Push
```

A propagação é conservadora. Ela considera aparência, câmera e, quando necessário, coerência espacial do bounding box. Eventos com identidade manual ou evidência facial útil não são indiscriminadamente transformados em falsos positivos.

### Proteção contra drift

Somente exemplos revisados manualmente atualizam o centróide do protótipo. Ocorrências automaticamente suprimidas **não treinam o protótipo**, evitando auto-reforço incorreto.

### Support

Um protótipo com várias confirmações manuais fornece suporte repetido ao ranker de hard-negatives, limitado a três votos. Nenhum threshold positivo do Body ReID é reduzido.

### Timeline separada

A Timeline passa a oferecer:

```text
Exibição
- Eventos normais
- Falsos positivos
- Todos
```

O modo normal exclui `identity_state = false_positive`.

### Desaprender

Em **Sistema → Falsos positivos aprendidos** é possível desativar um protótipo. A ação também retira do matcher os `body_negative_samples` legados correspondentes aos exemplos daquele protótipo. Portanto **Desaprender** não é apenas visual.

Reativar volta a utilizar o protótipo persistente.

### Consolidar históricos

O botão **Consolidar falsos positivos atuais** transforma falsos positivos manuais históricos em protótipos persistentes e reaplica somente correspondências retroativas muito fortes.

Arquivos de auditoria:

```text
data/false_positive_prototypes/
```

Embeddings/centróides ficam no SQLite; a imagem representativa serve apenas para auditoria visual.

---

# 6. Gravação NVR

A gravação é separada do detector/tracker/ReID:

```text
câmera RTSP
    ↓
  go2rtc
  ↙    ↘
visão   FFmpeg Recorder
```

O gravador lê o restream local do go2rtc e não usa frames processados pelo YOLO.

Para reduzir CPU:

- vídeo é mantido com `-c:v copy`;
- áudio, quando presente, é convertido para AAC 96 kbps para compatibilidade MP4 com câmeras que fornecem PCMA/PCMU.

## Modos por câmera

Em **Sistema → Gravação por câmera**:

```text
Desativada
Somente quando houver evento
Contínua 24/7
```

### Desativada

Default. Nenhum processo FFmpeg fica ativo para a câmera.

### Somente quando houver evento

Um novo evento inicia uma gravação pelo **Tempo após evento** configurado. Se outro evento ocorrer na mesma câmera enquanto a gravação ainda está ativa, o deadline é estendido.

Exemplo:

```text
Tempo após evento = 60 s
Evento 14:32:10 → grava aproximadamente até 14:33:10
Novo evento 14:32:50 → estende até aproximadamente 14:33:50
```

A implementação atual **não oferece pré-roll anterior ao evento**.

### Contínua 24/7

FFmpeg grava continuamente e segmenta os arquivos de acordo com **Duração dos arquivos**. Segmentos são preferíveis a um arquivo único de dias/semanas porque reduzem risco de corrupção e permitem retenção progressiva.

## Retenção de vídeo

Três limites são considerados:

1. idade máxima;
2. espaço máximo reservado aos vídeos;
3. espaço livre mínimo que deve permanecer no disco.

A condição mais restritiva vence. Arquivos que parecem estar sendo escritos naquele momento não são elegíveis para remoção.

Arquivos:

```text
data/recordings/
└── camera_<id>/
    └── YYYY/MM/DD/
        ├── continuous_....mp4
        └── event_....mp4
```

Logs:

```text
data/logs/recorder-camera-<id>.log
```

A interface mostra disponibilidade do FFmpeg, sessões ativas e erros por câmera.

---

# 7. Pausar notificações em um único aparelho

Em **Alertas → Notificações**, `Pausar neste dispositivo` altera somente o endpoint Web Push daquele navegador/PWA.

```text
PC servidor       enabled = 0
celular A          enabled = 1
celular B          enabled = 1
```

A pausa não altera regras globais nem chama `PushSubscription.unsubscribe()`. Retomar reutiliza a mesma inscrição.

---

# 8. Tailscale e PWA

Com o servidor rodando:

```powershell
.\tailscale-serve.ps1
```

Status:

```powershell
.\tailscale-serve.ps1 -Status
```

Desativar:

```powershell
.\tailscale-serve.ps1 -Off
```

Use a URL HTTPS `*.ts.net` no celular. Evite Funnel/publicação pública para instalações privadas.

### Android/Desktop

Chrome/Edge podem oferecer **Instalar app**.

### iPhone/iPad

Safari:

```text
Compartilhar → Adicionar à Tela de Início
```

A PWA é cliente e não pode executar `start.ps1`. No PC servidor, combine-a com o autostart do Windows.

---

# 9. Áudio e talkback

O viewer começa sem permissão permanente de microfone. Ouvir áudio é explícito e falar usa push-to-talk. Ao soltar, a implementação encerra o caminho de talkback antes de restaurar a visualização.

Talkback depende do firmware da câmera aceitar DVRIP/RTSP backchannel.

---

# 10. Build Windows

```powershell
.\build-windows.ps1
```

Saída:

```text
dist/PersonOfInterest/PersonOfInterest.exe
```

Com modelos ONNX embutidos:

```powershell
.\build-windows.ps1 -BundleModels
```

O build é **one-folder** e coleta também `imageio_ffmpeg` para o gravador.

Dados do executável:

```text
%LOCALAPPDATA%\PersonOfInterest\data
```

Pode ser substituído por `POI_DATA_DIR`.

---

# 11. Build Linux

PyInstaller não faz cross-compile Windows → Linux neste fluxo.

```bash
chmod +x build-linux.sh
./build-linux.sh
```

Com modelos:

```bash
./build-linux.sh --bundle-models
```

Saída:

```text
dist/PersonOfInterest/PersonOfInterest
```

Dados persistentes:

```text
$XDG_DATA_HOME/personofinterest/data
```

ou:

```text
~/.local/share/personofinterest/data
```

---

# 12. Dados locais

Instalação por Git:

```text
data/
├── person_of_interest.db
├── events/
├── faces/
├── body_anchors/
├── false_positive_prototypes/
├── recordings/
├── models/
├── assistant_audio/
├── vapid/
└── logs/
```

`data/` é ignorado pelo Git. Não publique essa pasta: ela pode conter credenciais, biometria, histórico, vídeos e material de Web Push.

---

# 13. Portas

```text
8080/tcp       API + frontend/PWA + WebSocket proxy
1984/tcp       go2rtc API local
8554/tcp       go2rtc RTSP local
8555/tcp+udp   WebRTC media transport
```

---

# 14. Validação

Sintaxe:

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
```

Testes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Testes unitários/estáticos não substituem validação no hardware real.

## Checklist de gravação

1. `Desativada` → nenhum FFmpeg da câmera;
2. `Somente evento` → evento cria MP4 e encerra no prazo;
3. eventos próximos estendem a sessão;
4. `Contínua` → segmentos são criados no intervalo configurado;
5. áudio/vídeo abrem corretamente;
6. retenção remove apenas arquivos elegíveis e não o segmento ativo;
7. reiniciar o sistema não grava eventos históricos.

## Checklist de falso positivo

1. marque manualmente um objeto recorrente;
2. confirme que aparece em **Falsos positivos aprendidos**;
3. confirme que futuras ocorrências fortes não geram Push;
4. confirme que a Timeline normal não as mostra;
5. use o filtro **Falsos positivos** para auditoria;
6. use **Desaprender** e confirme que novas detecções deixam de ser suprimidas por aquele protótipo.

---

# 15. Segurança e checkpoint desta reforma

Antes da reforma de armazenamento/gravação foi criado:

```text
backup/v5.7-before-storage-fp-recording-2026-10-20
```

Esse branch protege o **código** imediatamente anterior à reforma. Ele não substitui backup da pasta `data/`, pois banco, imagens e vídeos são deliberadamente ignorados pelo Git.

---

# 16. Princípios de arquitetura

As novas camadas seguem estes invariantes:

- gravação não controla tracker ou ReID;
- retenção atua depois da produção dos dados;
- limpeza destrutiva da Timeline é opt-in;
- gravação é `off` por padrão;
- referências manuais são protegidas por padrão;
- falsos positivos automáticos não treinam novos protótipos sozinhos;
- memória negativa persiste mesmo se a Timeline original for apagada;
- banco só é compactado por ação explícita;
- falha de gravação/armazenamento não deve impedir o motor principal de iniciar;
- Face ReID continua sendo a evidência forte;
- esta reforma não reduz thresholds positivos do Body ReID.
