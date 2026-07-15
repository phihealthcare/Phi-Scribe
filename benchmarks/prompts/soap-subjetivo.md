# SUBJETIVO — somente esta seção

## JSON obrigatório (única resposta válida)

```json
{"subjetivo": "texto narrativo em português brasileiro", "alertas_revisao": []}
```

**Proibido:** `patient_id`, `chief_complaint`, `history_of_present_illness`, `summary`, `response`, `SOAP`, `S/O/A/P`, chaves ou texto em inglês.

## O que extrair da transcrição

Diálogo contínuo sem rótulos Médico/Paciente. Leia **do início ao fim**.

Inclua no `subjetivo` (somente relato do paciente):
- Motivo da consulta e queixa principal
- HDA com **marcadores temporais** (há X dias/semanas, em DD/MM, episódio atual)
- Negações claras (disúria, febre, dor) — só se o paciente negou
- Medicamentos em uso, doses se ditas
- Episódios anteriores citados (UPA, internação)

**Não inclua:** laudos/ecografia, creatinina como achado, hipóteses do médico, condutas, exame físico.

## Formato ambulatorial (quando houver dados)

```
[idade se souber, ex.: 67 anos.]

[# antecedentes, um por linha, se ditos]
Em uso:
[medicamento + posologia, um por linha]

Vem para reavaliação por... Refere... Nega...
```

Sem nomes próprios — use "paciente", "profissional". Idade sim; nome não.

## Prioridade

Motivo da consulta e HDA **no início** da transcrição têm precedência sobre conversa final (internet, farmácia, anedotas).

## Exemplo (pt-BR)

```json
{
  "subjetivo": "Vem para reavaliação por urina concentrada/alaranjada e creatinina elevada. Refere xixi mais forte (amarelo-alaranjado) desde a consulta anterior, sem hematúria atual. Relata ingestão de ~1,5 L/dia e aumento da frequência urinária após aumentar líquidos. Nega disúria ou febre recente. Relata episódio de urina cor de Coca-Cola em 06/04 na UPA, tratado com ciprofloxacino, e gripe concomitante na mesma época. Em uso: losartana; 20 mg/dia de anti-inflamatório para dor nas pernas (reduziu dor ao subir escadas).",
  "alertas_revisao": []
}
```

{{TRANSCRICAO_SEGMENTADA}}
