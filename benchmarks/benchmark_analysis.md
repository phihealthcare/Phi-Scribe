# Relatório de Benchmark — Stacks de Pré-processamento (phi-scribe)

**Data da análise:** 22 Jun 2026  
**Fonte:** último timestamp em cada pasta `benchmarks/results/anamnesia-`*  
**Modelo ASR:** Whisper `large-v3` · CUDA · `int8_float16`  
**Stacks testados:** 69 (`stacks_all_generated.yaml`)

---

## 1. Resumo  


| Áudio                    | Último run         | Postprocess  | Melhor stack                    | WER        | CER    |
| ------------------------ | ------------------ | ------------ | ------------------------------- | ---------- | ------ |
| anamnesia-1 (OVERFITADO) | `20260622T211917Z` | Não          | `spectral_hpf_agc_loudness_vad` | **1.12%**  | 0.97%  |
| anamnesia-2(OVERFITADO) | `20260622T170812Z` | Sim (gpt-4o) | `spectral_hpf_agc_loudness_vad` | **3.13%**  | 2.33%  |
| anamnesia-3              | `20260622T135952Z` | Sim (gpt-4o) | `spectral_lpf_agc`              | **16.61%** | 11.78% |
| anamnesia-4              | `20260622T164300Z` | Sim (gpt-4o) | `spectral_hpf_agc_loudness_vad` | **12.89%** | 7.89%  |


Provavel que os resultados da anamnseia-1 e anamnseia-2 estejam overfitados, pois usei a mesma stack para transcrever o texto usado como referencia, o 3 e 4 esta com a referencia correta, irei realizar a revisao das anamnesias 3 e 4 para corrigir a reference e testar novamente.

### Recomendação geral para produção

**Stack padrão:** `spectral_hpf_agc_loudness_vad`

Pipeline: `normalize → remove_hum (HPF 80 Hz) → denoise (0.6) → agc → loudness (LUFS -23) → vad (trim)`

- Melhor ou empate em **3 de 4** áudios
- **Média WER global:** 8.92% (melhor entre os 69 stacks)
- Já alinhado com o `.env` de produção
- Em anamnesia-3 fica em 2.º lugar (18.55% vs 16.61% do vencedor local)

**Baseline (sem pré-processamento):** WER entre 15.67% e 26.49% — o stack recomendado reduz **~10–20 pp** de WER.

---

## 2. Ranking global (média WER nos 4 áudios)


| Rank | Stack                           | Média WER | an-1 | an-2 | an-3 | an-4 |
| ---- | ------------------------------- | --------- | ---- | ---- | ---- | ---- |
| 1    | `spectral_hpf_agc_loudness_vad` | **8.92%** | 1.1  | 3.1  | 18.6 | 12.9 |
| 2    | `spectral_agc_loudness_vad`     | 17.67%    | 16.2 | 21.0 | 19.6 | 13.8 |
| 3    | `spectral_lpf_agc_loudness_vad` | 17.87%    | 13.9 | 21.0 | 21.3 | 15.3 |
| 4    | `spectral_hpf_loudness_vad`     | 18.07%    | 14.9 | 21.4 | 22.4 | 13.6 |
| 5    | `none_hpf_vad`                  | 18.07%    | 16.7 | 21.6 | 20.2 | 13.8 |
| 6    | `none_lpf_loudness_vad`         | 18.07%    | 19.4 | 20.4 | 18.4 | 14.1 |
| 7    | `vad_only`                      | 18.22%    | 14.9 | 21.9 | 22.7 | 13.4 |
| 8    | `none_hpf_loudness_vad`         | 18.25%    | 16.2 | 20.7 | 22.1 | 14.1 |
| 9    | `none_vad`                      | 18.38%    | 14.9 | 21.9 | 23.2 | 13.6 |
| 10   | `none_lpf_vad`                  | 18.53%    | 14.9 | 22.4 | 22.3 | 14.6 |


**Conclusão:** HPF + denoise espectral + AGC + loudness + VAD conservador é o sweet spot. LPF + AGC ganha apenas em anamnesia-3 (áudio mais difícil).

---

## 3. Análise por áudio

### anamnesia-1 — Ginecologia (~2495 palavras)


| Métrica      | Valor                           |
| ------------ | ------------------------------- |
| Melhor stack | `spectral_hpf_agc_loudness_vad` |
| WER / CER    | 1.12% / 0.97%                   |
| Baseline     | 15.67%                          |
| Postprocess  | Desligado neste run             |


**Comparação com referência:** Transcrição quase literal; delta de +8 palavras. Erros raros e localizados.

**Palavras problemáticas (Whisper):**


| Tipo                  | Exemplos                                                                        |
| --------------------- | ------------------------------------------------------------------------------- |
| Substituições médicas | `micção` → `dimensão`, `anticoncepcional` → `dente`, `corrimento` → `colimento` |
| Omissões              | `uso`, `protegi`                                                                |
| Inserções (artefacto) | `concessional`, metadados de `initial_prompt` (`diálogo`, `médica interna`)     |


**Nota:** WER ~1% **sem** LLM — postprocess opcional neste áudio.

---

### anamnesia-2 — Consulta médica (~1725 palavras)


| Métrica       | Valor                           |
| ------------- | ------------------------------- |
| Melhor stack  | `spectral_hpf_agc_loudness_vad` |
| WER / CER     | 3.13% / 2.33%                   |
| Raw → pós-LLM | 3.19% → 3.13%                   |
| Baseline      | 21.68%                          |


**Comparação com referência:** Muito fiel; erros esporádicos em pronomes e números.

**Padrões de erro:**


| Tipo               | Exemplos                                |
| ------------------ | --------------------------------------- |
| Números            | `2` → `dois`, `1` → `uma`, `8` → `oito` |
| Pronomes           | `você` → `o`, `é` omitido               |
| Nomes/termos raros | `podalviada` → `rodalviara`             |
| LLM                | Ganho pequeno (−0.06 pp WER)            |


---

### anamnesia-3 — Cardiologia / anamnese longa (~1914 palavras)


| Métrica        | Valor                                        |
| -------------- | -------------------------------------------- |
| Melhor stack   | `spectral_lpf_agc` (não o stack de produção) |
| WER / CER      | 16.61% / 11.78%                              |
| Stack produção | 18.55% WER                                   |
| Baseline       | 21.84%                                       |
| Postprocess    | Quase sem efeito (18.70% → 18.55%)           |


**Comparação com referência:** Áudio mais difícil — diálogo longo, sobreposições, termos coloquiais e médicos. Hipótese com **~49 palavras a menos** que a referência (omissões).

**Padrões de erro:**


| Tipo                 | Exemplos                                                    |
| -------------------- | ----------------------------------------------------------- |
| Omissões frequentes  | `eu`, `é`, `o`, `né`, `doutor`, `anos`                      |
| Substituições graves | `churrasco` → `xamã`, `mudasse` → `mudou`, `dor` → `azuado` |
| Termos médicos       | `vesícula`, `eletrocardiograma`, `infarto`, `hipertensão`   |
| Coloquial            | `tá` ↔ `está`, `pra` ↔ `para`                               |


**Conteúdo clínico na referência:** dor torácica em apertão, história familiar (pai infarto aos 55 anos, hipertenso), vesícula/pedra, mioma, pneumonia infantil, Tylenol/Advil — vários pontos com distorção fonética.

---

### anamnesia-4 — Cardiologia curta (~419 palavras)


| Métrica       | Valor                                                                          |
| ------------- | ------------------------------------------------------------------------------ |
| Melhor stack  | `spectral_hpf_agc_loudness_vad` (= `spectral_hpf_agc_vad_conservative` em WER) |
| WER / CER     | 12.89% / 7.89%                                                                 |
| Raw → pós-LLM | **14.32% → 12.89%** (−1.43 pp)                                                 |
| Baseline      | 26.49%                                                                         |


**Comparação com referência:** Consulta cardiovascular estruturada (Carlos, 52 anos, ex-fumante, maço/dia, hipertensão familiar).

**Padrões de erro:**


| Tipo          | Exemplos                                        |
| ------------- | ----------------------------------------------- |
| Tratamento    | `seu` → `sr` (3×)                               |
| Omissões      | `né`, `preto`, `momento`, `num`                 |
| Substituições | `escritório` → `escritor`, `no` → `minimamente` |
| LLM           | Maior ganho relativo entre os 4 áudios          |


---

## 4. Padrões agregados — o que o Whisper não capta bem

### Omissões recorrentes (deletions vs referência)

`é`, `eu`, `o`, `né`, `não`, `que`, `você`, `doutor`, `anos`, `meu`, `a`

→ Pronomes, fillers e palavras funcionais curtas em fala rápida ou com overlap.

### Substituições comuns


| Referência         | Hipótese   | Causa provável                            |
| ------------------ | ---------- | ----------------------------------------- |
| `micção`           | `dimensão` | Homófono médico                           |
| `anticoncepcional` | `dente`    | Fonética + contexto                       |
| `churrasco`        | `xamã`     | Ruído / chunk                             |
| `você`             | `o`        | Elisão / fala informal                    |
| `seu`              | `sr`       | Normalização indesejada                   |
| `está` ↔ `tá`      | variante   | Diferença coloquial vs referência escrita |


### Termos médicos de risco

`micção`, `anticoncepcional`, `vesícula`, `eletrocardiograma`, `hipertensão`, `infarto`, `mioma`, `colesterol`, `tontura`, `enjoo`

---

## 5. Impacto do postprocess (LLM)


| Áudio       | Stack prod | WER raw | WER final | Δ                   |
| ----------- | ---------- | ------- | --------- | ------------------- |
| anamnesia-1 | prod       | —       | 1.12%     | (sem LLM neste run) |
| anamnesia-2 | prod       | 3.19%   | 3.13%     | −0.06 pp            |
| anamnesia-3 | prod       | 18.70%  | 18.55%    | −0.15 pp            |
| anamnesia-4 | prod       | 14.32%  | 12.89%    | **−1.43 pp**        |


LLM ajuda mais em transcrições curtas com erros óbvios; em anamnesia-3 o ganho é mínimo.

---

## 6. Recomendação de implementação

### Configuração `.env` / produção (manter)

```env
DENOISE_ENABLED=true          # DENOISE_PROP_DECREASE=0.6
HPF_ENABLED=true              # HPF_CUTOFF_HZ=80
AGC_ENABLED=true              # AGC_TARGET_DBFS=-20
LOUDNESS_ENABLED=true         # LOUDNESS_TARGET_LUFS=-23
VAD_ENABLED=true              # VAD_THRESHOLD=0.35, min_speech=100ms, silence=2500ms, pad=600ms
WHISPER_FASTER_MODEL=large-v3
WHISPER_FASTER_DEVICE=cuda
TRANSCRIPT_POSTPROCESS_ENABLED=true   # quando API disponível
```

### Ajuste opcional por perfil de áudio


| Perfil                                | Sugestão                                                 |
| ------------------------------------- | -------------------------------------------------------- |
| Consultas curtas (tipo an-4)          | Stack prod + postprocess LLM                             |
| Consultas longas ruidosas (tipo an-3) | Testar `spectral_lpf_agc` ou `DENOISE_PROP_DECREASE=0.3` |
| Áudio limpo (tipo an-1)               | Stack prod; postprocess opcional                         |


---

## 7. Sugestão / Caminho para WER/CER → 0% (meta de acerto máximo)

WER/CER **0%** em anamnese realista é improvável; metas por fase:


| Fase                  | Ação                                                               | Impacto esperado           |
| --------------------- | ------------------------------------------------------------------ | -------------------------- |
| **1. Stack**          | Manter `spectral_hpf_agc_loudness_vad`                             | Já capturado               |
| **2. Whisper**        | `initial_prompt` médico pt-BR; evitar vazamento do prompt na saída | −1–3 pp                    |
| **3. Postprocess**    | LLM local (Ollama) ou API; prompt restringe pontuação              | −1–2 pp (an-4)             |
| **4. Domínio**        | Fine-tune / hotwords: `micção`, `vesícula`, `eletrocardiograma`    | Termos médicos             |
| **5. Diarização**     | Separar médico vs paciente                                         | Menos confusão pronominal  |
| **6. Chunking**       | Chunks 30s com overlap; VAD antes do ASR                           | anamnesia-3 (−49 palavras) |
| **7. Referência**     | Normalizar `tá`/`está`, fillers no scoring                         | Métrica mais justa         |
| **8. Ensemble**       | Crisper + Whisper + voto/LLM merge                                 | Casos difíceis             |
| **9. Pós-ASR regras** | Regex para `sr`→`seu`, números dígitos vs por extenso              | Erros sistemáticos         |


### Prioridade imediata (ROI)

1. Implementar stack prod (já validado)
2. Reativar postprocess quando houver quota API ou Ollama local
3. Investigar anamnesia-3: `spectral_lpf_agc` vs stack prod
4. Hotword list clínica pt-BR no `initial_prompt`
5. Filtrar eco do `initial_prompt` na saída (artefacto `concessional`, `diálogo entre médica`)

