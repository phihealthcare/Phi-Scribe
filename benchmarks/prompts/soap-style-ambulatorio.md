## ESTILO AMBULATORIAL (OBRIGATÓRIO)

Produza o SOAP no formato de evolução ambulatorial abaixo. Cada seção (`soap.subjetivo`, `soap.objetivo`, etc.) é **uma única string** em português brasileiro; use `\n` para quebras de linha dentro do JSON.

### DADOS DO PRONTUÁRIO

Se a mensagem do usuário trouxer bloco **DADOS DO PRONTUÁRIO**, use-o **somente** para cabeçalho, medicamentos em uso e exames históricos que **não** foram ditos na transcrição. Não invente além do prontuário e da transcrição.

---

### `soap.subjetivo` — cabeçalho + narrativa (mesma string)

**Ordem obrigatória** (omitir blocos sem dados):

1. **Idade** (se conhecida): linha `67 anos.` — **sem nome próprio** do paciente.
2. **Antecedentes** (um por linha, prefixo `#`): `# IAM em 2022 - CRM 4 safenas + 1 mamaria`, `# HAS`, `# Nega alergias`, `# Tabagista`.
3. **Em uso:** (linha de título) depois um medicamento por linha com posologia: `Rosuvastatina 20mg 0-0-2`.
4. Linha em branco (`\n\n`).
5. **Narrativa clínica** iniciando com `Vem para reavaliação por...` ou `Vem por...` / `Refere...` / `Nega...`.

**Não coloque** em `subjetivo`: exame físico (BEG), labs com data, ECG, ecografia, hipóteses do médico ou condutas.

---

### `soap.objetivo` — exame + labs/ECG/imagem datados

Somente achados objetivos. Organize com **uma linha ou bloco por tipo**, nesta ordem quando houver dados:

1. Exame físico do atendimento (se verbalizado): `BEG, LOC, MUC, eupneica em AA, afebril`
2. Achados por sistema ou extremidades: `Extremidades aquecidas e bem perfundidas`
3. Laboratório: `Labs DD/MM/AAAA: Hb 14,8 // leuc 6830 // plaq 126000 // creat 1,21` (use `//` entre resultados na mesma data; linha separada por data)
4. ECG: `ECG DD/MM/AAAA: Bradicardia sinusal. BAV de primeiro grau.`
5. Imagem: `Ecografia aparelho urinário DD/MM/AAAA: <achados do laudo em prosa curta>`

Não invente BEG nem valores não verbalizados ou não constantes no prontuário/transcrição.

Se não houver dados objetivos: `Sem dados objetivos suficientes na transcrição.`

---

### `soap.avaliacao` — telegráfico

Uma hipótese ou problema por linha, linguagem do médico, preserve incerteza:

- `IRA vs DRC ??`
- `HAS controlada`

Não use parágrafos narrativos nem opinião do paciente.

---

### `soap.plano` — uma conduta por linha

Verbos do profissional, uma ação por linha (`\n`):

```
Solicito labs e EQU.
Reavaliação com exames.
Reforço ingesta hídrica.
Oriento sinais de alerta e alarme e busca por PA se necessário.
Orientações gerais.
```

Não invente retorno agendado se não foi dito.

---

### EXEMPLO DE REFERÊNCIA (estrutura — adapte ao caso real)

**subjetivo** (string única):

```
67 anos.

# IAM em 2022 - CRM 4 safenas + 1 mamaria
# HAS
# Nega alergias
# Tabagista

Em uso:
Rosuvastatina 20mg 0-0-2
AAS 100 mg 0-1-0
Losartana 50 mg 1-0-1

Vem para reavaliação por urina amarelada/alaranjada e aumento da creatinina. Refere estar ingerindo média de 1,5L de água ao dia, refere aumento da frequência urinária após aumentar ingesta hídrica. Traz ecografia para avaliação. Nega febre ou dor miccional.
```

**objetivo**:

```
BEG, LOC, MUC, eupneica em AA, afebril
Extremidades aquecidas e bem perfundidas

Labs 12/05/2026: Hb 14,8 // leuc 6830 // plaq 126000 // creat 1,21

ECG 09/03/2026: Bradicardia sinusal. BAV de primeiro Grau.

Ecografia aparelho urinário 28/05/2026: Rins com contornos e dimensões normais. Cistos corticais simples bilaterais. Bexiga sem lesões.
```

**avaliacao**: `IRA vs DRC ??`

**plano**:

```
Solicito labs e EQU.
Reavaliação com exames.
Reforço ingesta hídrica.
Oriento sinais de alerta e alarme e busca por PA se necessário.
Orientações gerais.
```
