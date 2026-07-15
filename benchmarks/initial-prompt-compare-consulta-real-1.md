# Initial prompt comparison — consulta-real-1

Whisper `large-v3` · batched · int8 · batch=4 · beam=1 · same pre-processed WAV.

| | |
|---|---|
| **Audio** | `uploads/processed/c07ffd25-6ebb-4262-a573-c91760d84f6e.wav` |
| **File id** | `c07ffd25-6ebb-4262-a573-c91760d84f6e` |
| **Reference** | `benchmarks/references/consulta-real-1.txt` |
| **Run** | `20260706T182916Z` |
| **Raw output** | `benchmarks/results/initial-prompt-compare-consulta-real-1/20260706T182916Z/` |

---

## Results (ranked by WER)

| Rank | Variant | WER | CER | Words | Time (s) | Prompt chars |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | **No `initial_prompt`** | **29.93%** | **21.98%** | 1,846 | 25.3 | 0 |
| 2 | Hotwords file (`whisper-initial-hotwords.txt`) | 30.61% | 22.53% | 1,870 | 25.8 | 549 |
| 3 | `.env` inline `WHISPER_FASTER_INITIAL_PROMPT` | 34.06% | 25.83% | 1,769 | 25.1 | 459 |

**Winner for this reference: no initial prompt** (−0.68 pp WER vs hotwords, −4.13 pp vs `.env`).

Wall time is essentially the same (~25 s) across all three.

---

## Conclusion

| Question | Answer |
|----------|--------|
| Do hotwords improve WER here? | **Not vs no prompt.** Hotwords file is +0.68 pp worse than omitting `initial_prompt`. |
| Does `.env` prompt help? | **No — it is the worst.** 34.06% WER; ~100 fewer words transcribed than hotwords. |
| `.env` vs hotwords file? | Different lists (34 vs 43 terms). `.env` is missing terms like `advil`, `hospital`, `umbigo`; hotwords file lacks `infecção`. |

### Why `.env` underperforms

The inline `.env` prompt captures **fewer words** (1,769 vs 1,870 with hotwords). Likely omissions / different segment boundaries in the long consult (~14 min). The pipeline run `06_transcribe_02_whisper.json` matches the `.env` result (34.06% WER).

### Why no prompt wins slightly

Without biasing vocabulary, Whisper may stay closer to the **colloquial reference** (`criatina`, `Tô`, paraphrased laudo). Hotwords nudge toward clinical spellings (`creatinina`, `ciprofloxacina`) that **count as errors** against `consulta-real-1.txt`.

---

## Pairwise transcript distance

| A | B | WER (A as reference) |
|---|---|---:|
| no prompt | hotwords | 6.93% |
| no prompt | `.env` | 11.32% |
| hotwords | `.env` | 7.59% |

---

## Prompt sources

**Hotwords file** (`benchmarks/prompts/whisper-initial-hotwords.txt`):

```
Transcrição literal de consulta médica em português brasileiro. Vocabulário clínico: anticoncepcional, churrasco, colesterol, ...
```

**`.env`** — shorter inline list (34 terms); overrides `config.py` default that would load the hotwords file.

---

## Recommendation

For **consulta-real-1** scoring against the current reference:

1. **Try `WHISPER_FASTER_INITIAL_PROMPT` empty / unset** — best WER in this test.
2. If you keep a prompt, prefer **`whisper-initial-hotwords.txt`** over the inline `.env` list (+3.45 pp better than `.env`).
3. Treat hotwords as a **recall / clinical spelling** tool, not a guaranteed WER win — reference wording matters.

### Re-run

```bash
python3 -c "
# Or inspect: benchmarks/results/initial-prompt-compare-consulta-real-1/20260706T182916Z/
"
```

Re-run script used: inline benchmark in session `20260706T182916Z` (same knobs as sweep winner `batched_large-v3_int8_b4_beam1`).

---

## Generic prompts (sem lista de hotwords)

Sweep adicional em `20260706T183526Z` — mesmos áudio, referência e knobs Whisper.

| Rank | Prompt (`initial_prompt`) | WER | CER | Palavras |
| ---: | --- | ---: | ---: | ---: |
| 1 | **(nenhum)** | **29.93%** | **21.98%** | 1,846 |
| 2 | `pt-BR consulta médica.` | 30.51% | 22.27% | 1,853 |
| 3 | Hotwords file (43 termos) | 30.61% | 22.53% | 1,870 |
| 4 | `Consulta médica, português do Brasil.` | 31.73% | 23.34% | 1,807 |
| 5 | `Português brasileiro.` | 32.26% | 24.53% | 1,775 |
| 6 | `Transcrição literal em português brasileiro.` | 32.57% | 24.86% | 1,798 |
| 7 | `Transcrição coloquial… Manter tá, né, tô…` | 33.16% | 24.94% | 1,813 |
| 8 | `Transcrição literal de diálogo entre médico e paciente…` | 35.01% | 27.47% | 1,722 |
| 9 | `Transcrição literal de consulta médica em pt-BR.` | 36.23% | 28.80% | 1,680 |
| 10 | `Transcrição literal de anamnese… médica interna e paciente…` | 37.24% | 29.36% | 1,663 |
| 11 | `…Preservar a fala original, incluindo expressões informais.` | 37.71% | 30.66% | 1,659 |
| 12 | `…com leitura de laudos e exames…` | 38.14% | 30.51% | 1,608 |
| 13 | `Consulta ambulatorial em português brasileiro. Transcrição literal.` | **88.35%** | 80.82% | 349 |

Raw: `benchmarks/results/generic-prompt-sweep-consulta-real-1/20260706T183526Z/`

### O que aprendemos

1. **Nenhum prompt genérico melhora o WER** vs omitir `initial_prompt` neste áudio/referência.
2. **Prompts longos pioram muito** (+5 a +8 pp WER) — especialmente os que mencionam “anamnese”, “médica interna”, “preservar fala” ou “laudos”. Perdem 150–200 palavras na hipótese.
3. **Prompt mínimo `pt-BR consulta médica.`** é o único genérico competitivo: 30.51% WER (0.58 pp pior que sem prompt, **melhor que hotwords**).
4. **`Consulta ambulatorial…`** causou colapso (349 palavras, 88% WER) — provável alucinação / truncamento; evitar.
5. **Hotwords** continuam úteis para **recall** (+24 palavras vs sem prompt), mas não para WER contra esta referência coloquial.

### Recomendação atualizada

| Objetivo | `WHISPER_FASTER_INITIAL_PROMPT` |
|----------|----------------------------------|
| Melhor WER vs `consulta-real-1` | **Vazio / omitir** |
| Compromisso mínimo (domínio sem hotwords) | `pt-BR consulta médica.` |
| Recall / termos clínicos | `whisper-initial-hotwords.txt` |
| Evitar | Prompts longos, “anamnese”, “ambulatorial”, listas inline no `.env` |
