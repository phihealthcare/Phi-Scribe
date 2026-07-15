# AVALIAÇÃO — somente esta seção

## JSON obrigatório (única resposta válida)

```json
{"avaliacao": "problema por linha em pt-BR", "alertas_revisao": []}
```

**Proibido:** `assessment`, `patient_concerns`, `potential_diagnoses`, `plan`, `summary`, chaves EMR ou texto em inglês.

## O que extrair

Hipóteses e problemas **formulados pelo profissional** na transcrição:
- "estou investigando...", "pode ser...", "versus", "não me faz pensar em..."
- Classificações explícitas (IRA vs DRC, etc.)

Uma linha por item. Preserve incerteza: `IRA vs DRC ??`

**Não inclua:** preocupações do paciente, condutas, laudos completos, achados que o médico não classificou como problema.

## Contexto das seções anteriores

Use Subjetivo e Objetivo abaixo apenas como referência — a Avaliação vem da **fala do profissional** na transcrição.

SUBJETIVO:
{{SUBJETIVO}}

OBJETIVO:
{{OBJETIVO}}

## Exemplo (pt-BR)

```json
{
  "avaliacao": "Investigação IRA vs DRC\nCreatinina elevada a esclarecer (temporalidade)\nCistos corticais — achado incidental\nHematuria prévia — temporalidade a definir",
  "alertas_revisao": []
}
```

Se o profissional não formular hipótese clara:
```json
{"avaliacao": "Avaliação não explicitada de forma suficiente na consulta.", "alertas_revisao": []}
```

{{TRANSCRICAO_AVALIACAO}}
