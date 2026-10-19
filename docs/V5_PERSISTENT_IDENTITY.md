# V5 — Tracking persistente e identidade temporal

Esta branch implementa a reforma estrutural do pipeline de identidade do PersonOfInterest. O objetivo é deixar de decidir identidade a partir de um único frame e passar a manter uma entidade de track que acumula evidências ao longo da passagem da pessoa.

## Princípios da V5

- Um evento representa uma passagem coerente, não um frame.
- Perdas curtas do detector tentam reassociar o mesmo `track_id` antes de criar outro track.
- O evento guarda `trigger_snapshot` e `best_snapshot` separadamente.
- Face continua sendo evidência forte.
- Body ReID continua sendo apenas identidade provável.
- Body ReID usa várias observações do track e score agregado por pessoa.
- Uma referência corporal automática ligada à face só entra na galeria confiável quando o próprio track demonstra suporte temporal, qualidade e estabilidade.
- Classificação manual é autoridade humana e nunca dispara cumprimento do Tonho.
- Tonho consulta o estado vivo do tracker; não existe segundo YOLO concorrendo pela câmera.
- Os thresholds `BODY_REID_THRESHOLD=0.72` e `BODY_REID_MARGIN=0.045` permanecem congelados durante a reforma. Recalibrar somente depois de coletar diagnóstico V5.

## Migração do banco

A migração é aditiva. Na primeira inicialização da V5 são adicionados campos de ciclo do track aos eventos, campos de confiança/proveniência aos bodies e tabelas de observações/âncoras.

Nenhum evento antigo é apagado. Bodies `manual_verified*` permanecem confiáveis. Bodies automáticos `face_verified*` antigos ficam fora da galeria confiável até satisfazerem a regra temporal ou serem confirmados manualmente.

Antes do primeiro teste em máquina de produção, faça uma cópia de `data/person_of_interest.db`.

## Teste de aceitação em câmera real

### 1. Evento único e reassociação

1. Entre no campo da câmera.
2. Aguarde o track estabilizar.
3. Faça uma oclusão/perda de detecção por aproximadamente 1–3 segundos.
4. Reapareça no mesmo deslocamento.

Esperado: o mesmo `track_id` e o mesmo `event_id` continuam ativos. Uma nova passagem só deve surgir depois que a janela de reassociação expirar.

### 2. Face aparecendo depois

1. Entre de costas ou com o rosto fora do quadro.
2. Permaneça no mesmo track.
3. Mostre o rosto depois.

Esperado: o mesmo evento ganha `has_face`, `best_face` e pode mudar de desconhecido/provável para conhecido sem criar outro evento. Se já havia cluster desconhecido e uma face posterior casa com pessoa conhecida, o cluster é recalculado sem duplicar a amostra.

### 3. Body ReID temporal

1. Use uma pessoa com referências confiáveis.
2. Entre sem mostrar o rosto por vários frames.
3. Observe o overlay e a Timeline.

Esperado: Body ReID aparece somente como `Provável: Nome`. A decisão usa agregação de várias observações e várias âncoras da pessoa; uma única similaridade extrema não deve dominar a decisão.

### 4. Quarentena de `face_verified`

Abra **Identidade → Biblioteca de pessoas → Referências**.

Esperado: referências corporais aparecem como `confiável` ou `quarentena`. A quarentena é preservada no banco, mas não participa do matcher positivo.

### 5. Cadastro pela câmera

1. Abra **Identidade → Biblioteca de pessoas**.
2. Crie/abra uma pessoa.
3. Clique em **Capturar câmera**.
4. Se houver mais de um track, escolha explicitamente o track correto.
5. Capture `face`, `body` ou `both`.

Esperado: as referências manuais entram diretamente como âncoras confiáveis.

### 6. Importação de imagem

Use **Importar imagem** e selecione `face`, `body` ou `both`.

Esperado: a referência aparece na biblioteca e pode ser excluída individualmente sem apagar o histórico de eventos.

### 7. Classificação manual e Tonho

1. Gere um evento desconhecido.
2. Classifique manualmente esse evento como uma pessoa conhecida.

Esperado: a referência aprende a classificação, mas Tonho não fala/cumprimenta por causa da ação manual. O banco grava a identidade, `identity_origin=manual` e `assistant_eligible=0` na mesma transação.

### 8. Tonho usando visão ao vivo

Com a câmera ativa, teste:

- `Oi Tonho, quem sou eu?`
- `Oi Tonho, quem está aqui?`
- `Oi Tonho, quantas pessoas estão aqui agora?`
- `Oi Tonho, o que você está vendo?`

Esperado: a resposta usa tracks vivos e não os últimos eventos históricos do banco.

### 9. Hard-negative

Esperado: um único crop nunca pode marcar automaticamente um track como falso positivo. O hard-negative exige suporte temporal e não pode rejeitar um evento em que um rosto foi detectado.

### 10. Alertas

Esperado: eventos `collecting` não geram Web Push. Identidades conhecidas podem ser notificadas assim que consolidadas; desconhecidos aguardam o encerramento da passagem para permitir que uma face tardia refine o mesmo evento.

### 11. PTZ

Validar que as funções anteriores continuam operando:

- BB parcial/instável não injeta salto no PTZ;
- velocidade usa erro + velocidade estimada do alvo;
- velocidade é limitada por `autofollow_max_speed`;
- perda temporária não volta imediatamente ao Home;
- após aproximadamente 3 s sem alvo, retorna ao Home definido.

### 12. Linha direcional e regiões

Esperado: regras espaciais continuam usando o pé da bounding box, com permanência/dwell, entrada/saída e linha direcional.

### 13. Timeline

Esperado: exclusão individual, em lote e total continuam funcionando. Um track persistente aparece como um único evento coerente.

## Diagnóstico V5

O botão **Exportar diagnóstico** continua gerando o pacote de calibração e agora acrescenta:

- `body_trust_metadata.csv`
- `track_lifecycle_metadata.csv`

O `manifest.json` informa quantas referências corporais estão confiáveis, em quarentena e temporalmente agregadas. O pacote não inclui embeddings brutos nem imagens.

## Recalibração posterior

Somente depois de coletar dados reais com a V5 deve-se estudar novamente:

- `BODY_REID_THRESHOLD`
- `BODY_REID_MARGIN`
- quantidade de âncoras/top-k
- limites de qualidade/estabilidade para promoção automática

Os scores da V5 não são diretamente equivalentes aos scores antigos porque agora a unidade de decisão é o track + galeria agregada por pessoa.

## Rollback

A implementação está isolada na branch `feature/persistent-tracking-reid` e no PR #4. O `main` permanece intacto até a validação real.

Para voltar ao código anterior durante o teste, basta executar a versão do `main` com uma cópia pré-V5 do banco. Como a migração adiciona colunas/tabelas, o backup do SQLite é a forma recomendada de rollback de dados.
