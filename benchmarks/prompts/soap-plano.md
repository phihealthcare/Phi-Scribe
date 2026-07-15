# PLANO — somente esta seção

## JSON obrigatório (única resposta válida)

```json
{"plano_conduta": "uma conduta por linha em pt-BR, separadas por \\n", "alertas_revisao": []}
```

**Proibido:** `plan`, `plan_conduta`, `recommendations`, `next_steps`, chaves EMR ou texto em inglês.

## O que extrair

Condutas **verbalizadas pelo profissional**:
- Exames solicitados ("solicitamos", "vou pedir")
- Orientações ("reforçar ingesta hídrica", "passar na UPA se...")
- Reavaliação ("reavaliar com exames")

Uma conduta por linha. Ignore comentários do paciente (internet, farmácia, automedicação).

## Contexto

SUBJETIVO:
{{SUBJETIVO}}

OBJETIVO:
{{OBJETIVO}}

AVALIAÇÃO:
{{AVALIACAO}}

## Exemplo (pt-BR)

```json
{
  "plano_conduta": "Solicitar exames de sangue (creatinina seriada e painel renal)\nReavaliar com os exames\nReforçar ingesta hídrica (≥1,5 L/dia)\nOrientar procurar UPA se sintomas diferentes dos atuais\nSolicitar trazer exames antigos para comparar temporalidade",
  "alertas_revisao": []
}
```

{{TRANSCRICAO_CONDUTA}}
