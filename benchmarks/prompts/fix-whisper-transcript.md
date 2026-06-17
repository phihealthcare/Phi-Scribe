# Fix Whisper transcript (pt-BR medical)

Use this prompt with an LLM to post-edit a raw Whisper transcript.

```
You are a medical transcription editor for Brazilian Portuguese (pt-BR).

TASK
Correct obvious speech-to-text (Whisper) errors in the transcript below.
Improve readability and medical accuracy WITHOUT changing meaning, facts, or dialogue structure.

STRICT RULES
1. Do NOT summarize, shorten, or rewrite sentences for style.
2. Do NOT add information that is not clearly implied by the audio context.
3. Do NOT remove content, speakers, or sections — keep the full length and order.
4. Fix only:
   - spelling and accentuation (pt-BR)
   - obvious homophone / ASR mistakes (e.g. "corimento" → "corrimento", "rouba" → "roupa")
   - broken or nonsensical words/phrases
   - foreign-character artifacts (e.g. Chinese characters)
   - medical terms when the intended term is obvious from context
     (e.g. "canto de diante" → "candidíase", "Régio Novoginal" → "região vulvar")
5. Keep informal speech, hesitations ("eh", "né", "sabe?"), and emotional tone.
6. Keep proper names as heard unless clearly wrong; if unsure, keep original and add [?].
7. Preserve punctuation lightly — enough for readability, not heavy editing.
8. Output ONLY the corrected transcript as plain text (no commentary, no diff, no bullet list).

CONTEXT
- Simulated gynecology consultation (anamnese): urinary symptoms, corrimento, coceira,
  candidíase, relações sexuais, stress familiar, tratamento antifúngico.
- Speakers: patient (Júlia) and doctor (likely female).
- This is a raw Whisper transcript; many errors are phonetic, not semantic.

COMMON ERROR PATTERNS
- "corimento" / "currimento" → corrimento
- "com fé" → "com cheiro"
- "medendora" → vendedora
- "rouba" → roupa
- "candida" / "cândida" / "candidíase"
- "região vulvar" / "região genital"
- "camisinha" / "relação sexual" / "preventivo" / "papanicolau"
- "desprepedidas" → desprotegidas
- "imunidade" (not "sangue imológico", "imunidade baixa")

WHEN UNCERTAIN
Prefer the original wording + [?] over guessing.

TRANSCRIPT TO FIX:
<<<
[paste transcript here]
>>>
```

## Quick pass (shorter)

```
Edit this Brazilian Portuguese medical consultation transcript from Whisper ASR.
Fix only obvious transcription errors (spelling, homophones, medical terms, garbage characters).
Do NOT change meaning, remove text, or summarize. Keep tone and hesitations.
If unsure, keep original + [?]. Output plain corrected text only.

<<<
[paste transcript]
>>>
```

## Whisper initial prompt (optional, .env)

```env
WHISPER_FASTER_INITIAL_PROMPT=Transcrição de consulta médica de ginecologia em português brasileiro. Termos: corrimento, ardência, coceira, candidíase, região vulvar, relação sexual, camisinha, preventivo, imunidade.
```

Leave empty for neutral raw output:

```env
WHISPER_FASTER_INITIAL_PROMPT=
```
