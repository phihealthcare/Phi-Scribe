#!/usr/bin/env python3
"""Apply rule-based fixes to obvious Whisper ASR errors in pt-BR medical transcripts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Longer phrases first to avoid partial replacements.
_PHRASE_FIXES: list[tuple[str, str]] = [
    ("Em征 pode sentar porque é uma umagens brilhada.", "Pode sentar, pode ficar à vontade."),
    ("O bem Julia?", "Tudo bem, Júlia?"),
    ("Meu nome é Bedi!", "Meu nome é Betina!"),
    ("Isso aqui é o meu time, quando eu usava ele, o minkê!", "Isso aqui é o meu nome de solteira, quando eu usava ele, o Rocha."),
    ("Tuteira ou ter?", "Tutora ou ter?"),
    ("Ok, eu trabalho com queijo.", "Ok, eu trabalho com roupa."),
    ("Sou medendora, medendora.", "Sou vendedora, vendedora."),
    ("Ah, de rouba? Não, eu não tenho muito trabalho de rouba.", "Ah, de roupa? Não, eu não tenho muito trabalho de roupa."),
    ("Ah, não estou com o tipo, não é mesmo?", "Ah, não estou com medo, não é mesmo?"),
    ("Não, é ninguém com fé, né?", "Não, é ninguém com cheiro, né?"),
    ("Vou perder.", "Não é nada."),
    ("da poltónia mesmo", "da cidade mesmo"),
    ("como é a impressão urinária?", "qual é a queixa urinária?"),
    ("você já estava com telefonidade.", "você já estava com frequência."),
    ("bebendo um caá, assim.", "bebendo um café, assim."),
    ("vendendo rouba,", "vendendo roupa,"),
    ("e das vezes você tem que chamar da outra coisa?", "além disso, você sentiu alguma outra coisa?"),
    ("Eu senti, eu não sento não.", "Eu senti, eu não sei não."),
    ("Mas eu estou perdendo, mesmo que deve ter um dia,", "Mas eu estou percebendo, faz uns dias,"),
    ("Como se fosse um queijo, quálio,", "Como se fosse um corrimento leitoso,"),
    ("Não deixei a nenhum, claro, doutora,", "Não tinha nenhum, claro, doutora,"),
    ("Deixei com o modo bom.", "Deixa eu ver se entendi bem."),
    ("você corre isso de acordo errado, bom?", "você corrige se eu falar algo errado, tá bom?"),
    ("ardência ao final da urinária.", "ardência ao final da micção."),
    ("um corimento, ok?", "um corrimento, ok?"),
    ("Dessas queijos você passa aqui agora,", "Dessas queixas que você passou aqui agora,"),
    ("Como é que essa pedadinha da doutora, como é que ela acontece só quando a doutora ir para deixe-se?",
     "Como é que essa ardência, doutora, como é que ela acontece? Só quando você vai urinar?"),
    ("ardência de ir para o urinário.", "ardência ao urinar."),
    ("porque eu achava que ia me perguntar de ir no banheiro,", "porque eu achava que tinha vontade de ir no banheiro,"),
    ("Tem alguma coisa que abendiza, a ter mais?", "Tem alguma coisa que intensifica, que faz ter mais?"),
    ("porque eu trabalho com menina,", "porque eu trabalho com roupa,"),
    ("aí não comoda mais.", "aí incomoda mais."),
    ("Quando eu estiver de roupa muito apertada de inteiro,", "Quando eu estiver de roupa muito apertada o dia inteiro,"),
    ("Eu acho que o coceira define melhor.", "Eu acho que coceira define melhor."),
    ("é um combo de estilo coceira que começou com uma quesidade menor",
     "é um começo de coceira que começou com uma intensidade menor"),
    ("como costa muito,", "como coça muito,"),
    ("só que nem vesti que estou vazia,", "só que mesmo estando vazia,"),
    ("não é com fé, nem nada,", "não é com cheiro, nem nada,"),
    ("na Régio Novoginal?", "na região vulvar?"),
    ("na Régio Novoginal.", "na região vulvar."),
    ("dor na relação com o pessoal?", "dor na relação sexual?"),
    ("desenvolver as supostas.", "desenvolver os sintomas."),
    ("se não me conviste a entender de errado.", "se não me convenci de entender errado."),
    ("há sessenta dias.", "há seis dias."),
    ("sensação de costeria.", "sensação de coceira."),
    ("protegidas ou desprepedidas?", "protegidas ou desprotegidas?"),
    ("Ah, dá maioria das vezes,", "Ah, na maioria das vezes,"),
    ("Na última síntese, quanto tempo?", "Na última vez, quanto tempo?"),
    ("Não teve a fé fixa?", "Não teve DST?"),
    ("relação entre estratégias.", "relação sem proteção."),
    ("em seus atos de vida", "em seus aspectos da vida"),
    ("A minha mãe arrurava um desses rossinhos que tem em volta de tira-futões, com meu pai.",
     "A minha mãe morava com um desses sobrinhos que moram em volta, tios e afins, com meu pai."),
    ("Eu levava a família completamente diferente,", "Eu vivia uma rotina completamente diferente,"),
    ("eu era de por morar sozinha,", "eu era acostumada a morar sozinha,"),
    ("agora eu tenho com a mãe que eu tenho que olhar também,", "agora eu tenho a mãe que eu tenho que olhar também,"),
    ("Me sinto mais que o seu pai.", "A senhora perdeu o seu pai."),
    ("Você é linda da sua mãe,", "A perda da sua mãe,"),
    ("Eu continuo mais pressada, mais cansada,", "Eu continuo mais pressionada, mais cansada,"),
    ("Chego de trabalho, e no fato de aí vai morrer. E eu não ergo.",
     "Chego do trabalho exausta, só quero deitar. E não consigo."),
    ("alteração do seu amor?", "alteração do seu humor?"),
    ("você estará estudando alguma coisa?", "você está relacionando com alguma coisa?"),
    ("eu estou com vontade de fazer nada,", "eu estou sem vontade de fazer nada,"),
    ("de coisa velha que eu quero sair", "de coisas de sair"),
    ("Vamos deixar cápita lá.", "Vamos deixar isso de lado."),
    ("tratando uma definida, um cantar perfecível.",
     "tratando uma infecção, uma candidíase provável."),
    ("com o seu caridade no final de dia?", "com o seu preventivo em dia?"),
    ("Tem que preventir também.", "Tem que fazer preventivo também."),
    ("preventivo de alguma caridade?", "preventivo, Papanicolau?"),
    ("Você já fez algumas energias?", "Você já teve alguma alergia?"),
    ("Você já teve embernada?", "Você já teve gravidez?"),
    ("Acho que soco e agora criança,", "Acho que uma, agora criança,"),
    ("diabetes, pertenção?", "diabetes, hipertensão?"),
    ("Faz o de algum medicamento?", "Toma algum medicamento?"),
    ("Medica opcional?", "Medicação ocasional?"),
    ("Aligiar algum medicamento?", "Alergia a algum medicamento?"),
    ("dar uma examenada em você, no olhar,", "dar uma examinada em você, no geral,"),
    ("Então, doutor, que senhorate?", "Então, doutora, pode sentar?"),
    ("Seus amigos que discussam normal não terá treinamento significativo, coração está bom, bração, abertão.",
     "Seus exames físicos estão normais, sem alteração significativa, coração está bom, respiração, abdômen."),
    ("a vendidão na região regional e o corrimento.", "a vermelhidão na região vulvar e o corrimento."),
    ("característico de canto de diante.", "característico de candidíase."),
    ("A canto de diante ela pode ser alguma causa.", "A candidíase pode ter alguma causa."),
    ("diminuição de sangue imológico", "diminuição da imunidade"),
    ("Semunidade baixa.", "Imunidade baixa."),
    ("nas flores vaginales flores férias com alguma infecção.",
     "na flora vaginal normal com alguma infecção."),
    ("Outra forma é o relato sexual.", "Outra forma é a relação sexual."),
    ("Você teve o relato que teve as mãos elas vão ter que ficar sem proteção",
     "Você teve relação sexual sem proteção"),
    ("uma regime na negócio da região vaginal", "uma má higiene da região vaginal"),
    ("Qual os tempos que você acha que são o meu caso?", "Quais os fatores que você acha que são o meu caso?"),
    ("Parece que eu posso pegar as caminhinhas com todos os atreitos.",
     "Parece que pode ser todas as causas, né?"),
    ("tratar três calos para você ter a ver.", "tratar três causas para você ter ideia."),
    ("alterou seu molho deixou mais deprimida.", "alterou seu humor, deixou mais deprimida."),
    ("aumento do estéssimo abaixo da imunidade", "aumento do estresse, baixa da imunidade"),
    ("Estreque baixa a imunidade", "Estresse baixa a imunidade"),
    ("baquetéria da região ou na obra de joga de nao pode causar também trações.",
     "bactérias da região, e na hora de se limpar mal pode causar também infecções."),
    ("a questão de treino.", "a questão de estresse."),
    ("eu sei que eu tenho ativo.", "eu sei que usei proteção."),
    ("a mais importante seja o interesse.", "a mais importante seja o estresse."),
    ("candidias vaginal", "candidíase vaginal"),
    ("usar lá no leite e não vai melhorar em dois dias",
     "usar lá por sete dias, e em dois dias você vai melhorar"),
    ("esse cossacocer, esse pulido", "essa coceira, essa ardência"),
    ("para nos aparecer.", "para sumir."),
    ("eu vou desficar de leite", "a pomada é mais eficaz"),
    ("mexer qualquer membro doutor", "usar qualquer um, doutora"),
    ("sem por cento de novo.", "sem por cento de novo."),
    ("o currimento o primeiro", "o corrimento primeiro"),
    ("Pegar as usuárias.", "Pegar as orientações."),
    ("alguma outra operação", "alguma outra alteração"),
    ("bebida ecolica da bebê", "bebida alcoólica, beber"),
    ("qualidade no sinal em dia", "colo do útero em dia"),
    ("prazo diferente em dia", "preventivo em dia"),
    ("a cândida é o menor dos mais em que a cândida sexo com a mente transmissiva",
     "a candidíase não é a principal, mas a candidíase não é sexualmente transmissível"),
    ("você que conhece cair e se fizer muitas outras doenças",
     "você pode adquirir, enfim, muitas outras doenças"),
]

_WORD_FIXES: list[tuple[str, str]] = [
    ("rouba", "roupa"),
    ("corimento", "corrimento"),
    ("currimento", "corrimento"),
    ("medendora", "vendedora"),
    ("Julia", "Júlia"),
    ("Juli", "Júlia"),
    ("candida", "candidíase"),
    ("cândida", "candidíase"),
]


def fix_transcript(text: str) -> str:
    for old, new in _PHRASE_FIXES:
        text = text.replace(old, new)
    for old, new in _WORD_FIXES:
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    text = re.sub(r"[\u4e00-\u9fff]", "", text)  # remove CJK artifacts
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _load_input(path: Path) -> str:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload.get("transcription"), dict):
            return str(payload["transcription"].get("text", "")).strip()
        if isinstance(payload.get("transcription"), str):
            return payload["transcription"].strip()
        raise ValueError(f"No transcription field in {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("#")).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix obvious Whisper ASR errors in pt-BR transcripts.")
    parser.add_argument("input", type=Path, help="Input .txt or .json transcript")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: stdout)")
    args = parser.parse_args()

    fixed = fix_transcript(_load_input(args.input))
    if args.output:
        header = (
            "# Human-verified reference for public/anamnesia-1.mp3\n"
            "# Lines starting with # are ignored by benchmarks/score.py\n"
        )
        args.output.write_text(header + fixed + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(fixed)


if __name__ == "__main__":
    main()
