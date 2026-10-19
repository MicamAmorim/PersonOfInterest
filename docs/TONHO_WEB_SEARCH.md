# Tonho — data, hora e pesquisa na web

A V5.2 adiciona comandos de data e pesquisa na internet ao fluxo de voz do Tonho.

## Comandos

Exemplos suportados:

- `Oi, Tonho! Que horas são?`
- `Oi, Tonho! Que dia é hoje?`
- `Oi, Tonho! Qual a data e hora?`
- `Oi, Tonho! Pesquise na internet: qual é a altura da Torre Eiffel?`
- `Oi, Tonho! Pesquise no Google: quem criou a linguagem Python?`

A hora e a data usam o fuso horário configurado para a câmera em `camera_assistant_settings.timezone`.

## Fluxo falado da pesquisa

Quando o comando é reconhecido como pesquisa, Tonho fala primeiro:

`Certo, vou pesquisar agora.`

Depois consulta o provedor, resume os snippets mais relevantes e fala a resposta final. Os comandos de câmera/identidade continuam locais; apenas comandos explícitos de pesquisa são enviados para a internet.

## Google Programmable Search

Quando estas variáveis estão configuradas, o Tonho usa a Custom Search JSON API do Google:

```powershell
$env:GOOGLE_CSE_API_KEY="SUA_CHAVE"
$env:GOOGLE_CSE_CX="SEU_SEARCH_ENGINE_ID"
```

Para persistir no Windows, defina as variáveis no ambiente do serviço/processo que inicia o backend.

Também podem ser ajustados:

```powershell
$env:WEB_SEARCH_TIMEOUT_SECONDS="8"
$env:WEB_SEARCH_RESULT_COUNT="5"
```

O backend lê as variáveis no startup. Reinicie o PersonOfInterest após alterá-las.

## Fallback

Sem `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX`, a pesquisa continua disponível usando a página HTML do DuckDuckGo como fallback sem chave. Se o Google estiver configurado mas falhar temporariamente, o mesmo fallback é tentado.

O estado do Wake Word/Tonho Lab informa:

- provedor atual;
- se o Google está configurado;
- timeout;
- quantidade de resultados consultados.

## Privacidade

Somente o texto depois de `Pesquise...` é enviado ao provedor de busca. Imagens, RTSP, embeddings, nomes da Biblioteca de Pessoas e estado da câmera não fazem parte da consulta.

## Limites do resumo

A primeira implementação é deliberadamente conservadora: o Tonho resume os snippets retornados pela busca e informa os domínios consultados. Ele não executa um segundo modelo de linguagem remoto nem envia o contexto da residência/câmera para um LLM externo.
