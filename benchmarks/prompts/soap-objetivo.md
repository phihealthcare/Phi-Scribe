# OBJETIVO — somente esta seção

## JSON obrigatório (única resposta válida)

```json
{"objetivo": "texto em português brasileiro, linhas separadas por \\n", "alertas_revisao": []}
```

**Proibido:** `patient_id`, `physical_exam`, `labs_and_imaging`, `medical_history`, `assessment`, `plan`, chaves EMR ou texto em inglês.

## O que extrair

Somente achados **objetivos** ditos pelo profissional ou lidos de laudo:
- Laudo de ecografia/ECG/labs com **medidas** (cm, valores, datas se houver)
- Exame físico verbalizado no atendimento
- Impressão objetiva breve do profissional sobre estabilidade (ex.: "paciente estável")

**Não inclua:** sintomas relatados pelo paciente, HDA, hipóteses, condutas, antecedentes.

## Formato ambulatorial

```
Ecografia aparelho urinário [data se houver]: Rins com dimensões normais (RD 11,6 cm, RE 11,5 cm). Cistos corticais bilaterais (até 4,3 cm à direita). Bexiga sem lesões.
Labs [data se houver]: creatinina alterada (valor se citado)
Profissional verbaliza estabilidade clínica no momento.
```

Se não houver dado objetivo na transcrição:
```json
{"objetivo": "Sem dados objetivos suficientes na transcrição.", "alertas_revisao": []}
```

## Exemplo (pt-BR)

```json
{
  "objetivo": "Ecografia renal: rins com contornos, textura e dimensões normais (RD 11,6 cm, RE 11,5 cm). Sistema coletor sem dilatação ou cálculos. Cistos corticais bilaterais (até 4,3 cm à direita, 1,5 cm à esquerda). Bexiga repleta, lisa, sem lesões.\nCreatinina alterada (valor seriado pendente).\nProfissional verbaliza que paciente está estável no momento.",
  "alertas_revisao": []
}
```

{{TRANSCRICAO_E_DADOS_OBJETIVOS}}
