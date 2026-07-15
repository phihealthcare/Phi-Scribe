## FORMATO DA TRANSCRIÇÃO (sem diarização)

A transcrição é um **diálogo contínuo** entre profissional e paciente.
**Não há** rótulos Médico:/Paciente:/Falante.

### Como separar as seções SOAP sem rótulos

| Seção | De onde extrair | Sinais linguísticos |
|-------|-----------------|---------------------|
| **Subjetivo** | Fala do paciente | 1ª pessoa ("eu sinto", "minha urina"), respostas a perguntas, negações ("não", "nada disso"), relato de episódios passados |
| **Objetivo** | Achados medidos/observados/laudos citados | Valores numéricos, leitura de ecografia/ECG, "exame mostra", dimensões em cm, creatinina com valor |
| **Avaliação** | Hipóteses do profissional | "estou investigando", "pode ser", "versus", "não me faz pensar em", classificações explícitas |
| **Plano** | Condutas verbalizadas | "vou solicitar", "solicitamos", "reforçar", "reavaliar", "oriento", "passar na UPA" |

### Regras críticas

1. **Leia a transcrição inteira**, do início ao fim, antes de redigir. Não resuma só os últimos minutos.
2. **Prioridade clínica**: motivo da consulta, HDA, exames discutidos e conduta têm precedência sobre conversa de encerramento (internet, farmácia, anedotas).
3. **Pergunta do profissional ≠ sintoma.** "Teve febre?" não vira "nega febre" sem resposta clara.
4. **Reformulação do profissional** só entra no Subjetivo com confirmação do paciente.
5. **Atribuição incerta**: use "Relata..." / "Profissional verbaliza..." — não invente quem falou.
6. **Não exija** prefixos Paciente:/Médico: na saída SOAP; use narrativa clínica ("Vem para reavaliação...", "Solicito...").
7. Use timestamps nos `alertas_revisao` quando houver termo ASR incerto.

### Erros comuns (sem diarização) — NÃO reproduzir

| Errado | Correto |
|--------|---------|
| Subjetivo só com papo final (internet, remédios sem receita) | Incluir queixa principal, HDA e contexto clínico do início da consulta |
| Avaliação com "paciente apresenta preocupação..." | Só hipóteses **formuladas pelo profissional** |
| Objetivo com sintomas relatados | Laudos/ecografia com medidas; ou "Sem dados objetivos suficientes na transcrição." |
| Conduta inventada ("agendar retorno") | Só o que o profissional disse ("solicitamos os exames", "reforçar ingesta hídrica") |
