PRIORIDADE MÁXIMA — COMPLETUDE

- A saída deve ter aproximadamente o mesmo número de palavras e linhas que a entrada (tolerância ±5%).
- É proibido omitir turnos, resumir, condensar ou pular trechos do meio.
- Se não puder devolver o texto completo corrigido, devolva a entrada inalterada.

CORREÇÕES PERMITIDAS

- Ortografia, acentuação e homófonos óbvios em pt-BR.
- Termos médicos truncados ou claramente errados pelo contexto imediato.
- Frases de resposta Q&A agramaticais quando a pergunta anterior restringe o tipo de resposta (ex.: medicamento, quantidade, história familiar).

PROIBIDO

- Resumir, reescrever por estilo, inventar fatos ou respostas novas.
- Editar pontuação ou capitalização entre palavras (copie do ASR).
- Remover conteúdo clínico: exames, doses, laudos lidos em voz alta, condutas, medicamentos.
- Renomear Falante 1:/Falante 2:/SPEAKER_ (etapa posterior faz isso).

LAUDOS EM VOZ ALTA

Quando Falante 1/2 alternam durante leitura de laudo ou exame, preserve todas as frases na ordem. Corrija só ortografia médica óbvia. Não aplique reparo Q&A nesses blocos.

VERIFICAÇÃO

- Saída com pelo menos 95% das palavras da entrada.
- Mesmo número de linhas Falante/SPEAKER (±2 só para legenda removível).
- Se falhar, devolva a entrada inalterada.

Saída: somente o texto corrigido em texto simples, sem prefácio, markdown ou JSON.
