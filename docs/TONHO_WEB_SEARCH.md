# Tonho — data, hora e pesquisa na web

A V5.2 adiciona comandos de data e pesquisa na internet ao fluxo de voz do Tonho sem depender de API paga.

## Comandos

Exemplos suportados:

- `Oi, Tonho! Que horas são?`
- `Oi, Tonho! Que dia é hoje?`
- `Oi, Tonho! Qual a data e hora?`
- `Oi, Tonho! Pesquise na internet: qual é a altura da Torre Eiffel?`
- `Oi, Tonho! Pesquise no Google: quem criou a linguagem Python?`

A frase `no Google` é aceita apenas como linguagem natural do usuário; o backend não usa a API do Google.

A hora e a data usam o fuso horário configurado para a câmera em `camera_assistant_settings.timezone`.

## Fluxo falado da pesquisa

Quando o comando é reconhecido como pesquisa, Tonho fala primeiro:

`Certo, espera um momento, vou pesquisar.`

Depois consulta o provedor, resume os snippets mais relevantes e fala a resposta final. Os comandos de câmera/identidade continuam locais; apenas comandos explícitos de pesquisa são enviados para a internet.

## Provedor principal: SearXNG local

O projeto inclui uma instância privada de SearXNG em `docker-compose.yml` e a configuração `infra/searxng/settings.yml` habilita respostas JSON para uso interno do Tonho.

No modo Docker, o backend usa automaticamente:

`http://searxng:8080`

No fluxo Windows com `start.ps1`, o script `ensure-searxng.ps1` verifica `http://127.0.0.1:8888`. Se Docker estiver disponível e o serviço ainda não estiver ativo, ele executa automaticamente:

```powershell
docker compose up -d searxng
```

Quando a instância responde, `start.ps1` injeta `SEARXNG_URL=http://127.0.0.1:8888` no backend daquela execução.

A porta do SearXNG é publicada apenas em `127.0.0.1:8888`, portanto não fica exposta diretamente à rede local.

## Fallback gratuito

Se Docker não estiver instalado/ativo ou o SearXNG não responder, o Tonho usa diretamente o HTML do DuckDuckGo como fallback sem chave. Dessa forma a pesquisa continua disponível e não espera um timeout de um SearXNG inexistente.

Podem ser ajustados:

```powershell
$env:WEB_SEARCH_TIMEOUT_SECONDS="8"
$env:WEB_SEARCH_RESULT_COUNT="5"
```

Também é possível apontar para outra instância privada de SearXNG antes de iniciar o backend:

```powershell
$env:SEARXNG_URL="http://127.0.0.1:8888"
```

## Estado do Tonho

O estado do Wake Word/Tonho Lab informa:

- provedor em uso (`searxng` ou `duckduckgo`);
- se uma URL do SearXNG foi configurada;
- timeout;
- quantidade máxima de resultados consultados.

## Privacidade

Somente o texto depois de `Pesquise...` é enviado ao mecanismo de busca. Imagens, RTSP, embeddings, nomes da Biblioteca de Pessoas e estado da câmera não fazem parte da consulta.

## Limites do resumo

A implementação resume os snippets retornados pela pesquisa e informa os domínios consultados. Ela não envia o contexto da residência/câmera para um LLM remoto.
