from app.services.soap_validation import (
    EMPTY_OBJETIVO_TEXT,
    EMPTY_SUBJETIVO_TEXT,
    EXPECTED_SOAP_STATUS,
    count_temporal_markers,
    merge_soap_sections,
    normalize_soap_section_partial,
    temporal_markers_preserved_in_text,
    transcript_review_hints,
    validate_soap_document,
    validate_soap_section,
)


def _valid_document() -> dict:
    return {
        "status": EXPECTED_SOAP_STATUS,
        "soap": {
            "subjetivo": (
                "Refere episódios de dor há duas semanas, com novo episódio iniciado há duas horas."
            ),
            "objetivo": "Sem dados objetivos suficientes na transcrição.",
            "avaliacao": "Avaliação não explicitada de forma suficiente na consulta.",
            "plano": "Conduta não explicitada de forma suficiente na consulta.",
        },
        "alertas_revisao": [
            {
                "timestamp": "",
                "trecho_original": "Yasmin",
                "motivo": "conflito com Patrícia",
            }
        ],
    }


def test_rejects_legacy_soap_shape() -> None:
    ok, errors = validate_soap_document({"SOAP": {"S": "x", "O": "y", "A": "z", "P": "w"}})
    assert not ok
    assert any("legado" in err for err in errors)


def test_requires_temporal_markers_in_narrative_subjetivo() -> None:
    transcript = "Dor há duas semanas. Episódio há duas horas com náusea."
    doc = _valid_document()
    doc["soap"]["subjetivo"] = "Refere dor iniciada há duas horas."
    ok, errors = validate_soap_document(doc, transcript=transcript)
    assert not ok
    assert any("marcadores temporais" in err for err in errors)


def test_requires_alerts_for_uncertain_terms() -> None:
    transcript = "Paciente Patrícia. Médico chama dona Yasmin. Não sentiu tortura."
    doc = _valid_document()
    doc["alertas_revisao"] = []
    ok, errors = validate_soap_document(doc, transcript=transcript)
    assert not ok
    assert any("alertas_revisao" in err for err in errors)


def test_accepts_valid_document() -> None:
    transcript = "Dor há duas semanas. Episódio há duas horas. Patrícia e Yasmin."
    ok, errors = validate_soap_document(_valid_document(), transcript=transcript)
    assert ok
    assert errors == []


def test_temporal_marker_count() -> None:
    assert count_temporal_markers("há duas semanas e há duas horas") >= 2


def test_temporal_markers_preserved_in_text() -> None:
    text = "Episódios há duas semanas, com novo episódio há duas horas."
    transcript = "Dor há duas semanas. Episódio há duas horas."
    assert temporal_markers_preserved_in_text(text, transcript) >= 2


def test_temporal_markers_preserved_with_approximate_wording() -> None:
    text = "Refere episódios há cerca de duas semanas, com novo episódio há duas horas."
    transcript = "Dor há duas semanas. Episódio há duas horas."
    assert temporal_markers_preserved_in_text(text, transcript) >= 2


def test_rejects_hallucinated_subjetivo() -> None:
    transcript = (
        "Patrícia refere dor no peito com pressão e náusea há duas horas. "
        "Episódios há duas semanas."
    )
    partial = {
        "subjetivo": "Paciente relata dor lombar com irradiação para perna esquerda.",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("subjetivo", partial, transcript=transcript)
    assert not ok
    assert any("alucinação" in err for err in errors)


def test_supplements_alertas_from_hints() -> None:
    transcript = "Patrícia disse. O médico falou com dona Yasmin. Não sentiu tortura."
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "subjetivo": "Refere dor no peito há duas semanas, com episódio atual há duas horas.",
            "alertas_revisao": [],
        },
        transcript=transcript,
    )
    ok, errors = validate_soap_section("subjetivo", partial, transcript=transcript)
    assert ok
    assert len(partial["alertas_revisao"]) >= 1


def test_supplements_alertas_when_key_missing() -> None:
    transcript = "Patrícia disse. O médico falou com dona Yasmin."
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "subjetivo": "Refere dor no peito há duas semanas, com episódio atual há duas horas.",
        },
        transcript=transcript,
    )
    assert "alertas_revisao" in partial
    assert len(partial["alertas_revisao"]) >= 1


def test_coerces_summary_key_to_subjetivo() -> None:
    transcript = (
        "Patrícia refere dor no peito com pressão há duas horas. "
        "Episódios há duas semanas, umas duas vezes na semana."
    )
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "summary": (
                "Paciente refere dor no peito em aperto há duas semanas, "
                "com episódio atual há duas horas e intensidade 8/10."
            ),
        },
        transcript=transcript,
    )
    ok, errors = validate_soap_section("subjetivo", partial, transcript=transcript)
    assert ok, errors
    assert partial["subjetivo"].startswith("Paciente refere dor no peito")


def test_coerces_wrong_schema_with_multiple_keys_to_subjetivo() -> None:
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "summary": "Resumo clínico com dor no peito há duas semanas.",
            "key_concerns": ["dor"],
            "recommendations": ["ECG"],
        },
    )
    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok, errors
    assert partial["subjetivo"] == "Resumo clínico com dor no peito há duas semanas."


def test_normalizes_string_alertas_to_objects() -> None:
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "subjetivo": "Refere dor no peito há duas semanas, com episódio atual há duas horas.",
            "alertas_revisao": ["termo_clinico_inseguro: possível erro de ASR para vesícula"],
        },
    )
    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok, errors
    assert partial["alertas_revisao"][0]["motivo"].startswith("termo_clinico_inseguro")


def test_rejects_yasmin_as_patient_name() -> None:
    transcript = "Meu nome é Patrícia. O médico falou com dona Yasmin."
    partial = {
        "subjetivo": (
            "A paciente, Dona Yasmin, relata dor no peito há duas semanas, "
            "com episódio atual há duas horas."
        ),
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("subjetivo", partial, transcript=transcript)
    assert not ok
    assert any("Yasmin" in err for err in errors)


def test_review_hints_detect_name_conflict() -> None:
    hints = transcript_review_hints("Patrícia disse. O médico falou com dona Yasmin.")
    assert any("Patrícia" in hint for hint in hints)


def test_rejects_english_subjetivo() -> None:
    partial = {
        "subjetivo": (
            "The patient is a 50-year-old teacher experiencing chest pain "
            "that worsens with exertion."
        ),
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("subjetivo", partial)
    assert not ok
    assert any("português" in err for err in errors)


def test_validate_subjetivo_section_narrative() -> None:
    partial = {
        "subjetivo": "Paciente refere dor abdominal há três dias.",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok
    assert errors == []


def test_merge_soap_sections_builds_full_document() -> None:
    document = merge_soap_sections(
        subjetivo={"subjetivo": "Refere dor abdominal.", "alertas_revisao": []},
        objetivo={
            "objetivo": "PA 120x80 mmHg.",
            "alertas_revisao": [{"timestamp": "", "trecho_original": "x", "motivo": "y"}],
        },
        avaliacao={"avaliacao": "Dor articular", "alertas_revisao": []},
        plano={"plano_conduta": "Oriento repouso.", "alertas_revisao": []},
    )
    ok, errors = validate_soap_document(document)
    assert ok
    assert document["status"] == EXPECTED_SOAP_STATUS
    assert document["soap"]["subjetivo"] == "Refere dor abdominal."
    assert document["soap"]["objetivo"] == "PA 120x80 mmHg."
    assert document["soap"]["avaliacao"] == "Dor articular"
    assert document["soap"]["plano"] == "Oriento repouso."
    assert len(document["alertas_revisao"]) == 1


def test_validate_plano_section_narrative() -> None:
    partial = {
        "plano_conduta": "Prescrevo dipirona 500 mg 6/6h por 3 dias.",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("plano", partial)
    assert ok
    assert errors == []


def test_validate_avaliacao_section_narrative() -> None:
    partial = {
        "avaliacao": "Dor articular",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("avaliacao", partial)
    assert ok
    assert errors == []


def test_validate_objetivo_section_narrative() -> None:
    partial = {
        "objetivo": "Sem dados objetivos suficientes na transcrição.",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("objetivo", partial)
    assert ok
    assert errors == []


def test_rejects_objetivo_meta_echo() -> None:
    partial = {
        "objetivo": "Gerar um JSON de Objetivo.",
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("objetivo", partial)
    assert not ok
    assert any("instrução" in err for err in errors)


def test_rejects_objetivo_asr_fix_echo() -> None:
    partial = {
        "objetivo": (
            "Identificar e corrigir erros na transcrição, "
            "focando em timestamps, trechos originais e motivos."
        ),
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("objetivo", partial)
    assert not ok
    assert any("instrução" in err for err in errors)


def test_coerces_wrong_schema_objetivo_to_empty() -> None:
    partial = normalize_soap_section_partial(
        "objetivo",
        {"summary": "Resumo.", "key_concerns": ["dor"], "recommendations": ["ECG"]},
    )
    ok, errors = validate_soap_section("objetivo", partial)
    assert ok, errors
    assert partial["objetivo"] == EMPTY_OBJETIVO_TEXT


def test_rejects_avaliacao_rubric_dict() -> None:
    partial = {
        "avaliacao": {
            "pontuacao": 0,
            "justificativa": "",
            "aspectos_positivos": [],
            "aspectos_negativos": [],
            "recomendações": [],
        },
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("avaliacao", partial)
    assert not ok
    assert any("pontuação" in err for err in errors)


def test_normalizes_plano_de_conduta_key() -> None:
    partial = normalize_soap_section_partial(
        "plano",
        {
            "plano_de_conduta": "Solicito eletrocardiograma.\nSolicito enzimas laboratoriais.",
            "alertas_revisao": [],
        },
    )
    ok, errors = validate_soap_section("plano", partial)
    assert ok
    assert errors == []
    assert partial["plano_conduta"].startswith("Solicito eletrocardiograma")


def test_normalizes_plano_conduta_dict_to_text() -> None:
    partial = normalize_soap_section_partial(
        "plano",
        {
            "plano_conduta": {
                "etapa_1": "Investigar quadro cardiovascular.",
                "etapa_2": "Solicito eletrocardiograma.",
            },
            "alertas_revisao": [],
        },
    )
    ok, errors = validate_soap_section("plano", partial)
    assert ok
    assert "eletrocardiograma" in partial["plano_conduta"]


def test_rejects_plano_conduta_object_after_normalization() -> None:
    partial = normalize_soap_section_partial(
        "plano",
        {
            "plano_conduta": {"objetivo_principal": "Investigar"},
            "alertas_revisao": [],
        },
    )
    ok, errors = validate_soap_section("plano", partial)
    assert not ok
    assert any("plano_conduta" in err for err in errors)


def test_rejects_english_avaliacao() -> None:
    partial = {
        "avaliacao": (
            "Chest pain, especially with exertion\n"
            "Family history of heart disease (father had heart attack)"
        ),
        "alertas_revisao": [],
    }
    ok, errors = validate_soap_section("avaliacao", partial)
    assert not ok
    assert any("português" in err for err in errors)


def test_coerces_avaliacao_wrong_schema_key_concerns() -> None:
    partial = normalize_soap_section_partial(
        "avaliacao",
        {
            "summary": "Resumo.",
            "key_concerns": ["Dor torácica"],
            "recommendations": ["ECG"],
        },
    )
    ok, errors = validate_soap_section("avaliacao", partial)
    assert ok, errors
    assert partial["avaliacao"] == "Resumo."


def test_normalize_monolithic_flat_schema() -> None:
    from app.services.soap_validation import normalize_monolithic_soap_document

    flat = {
        "status": "RASCUNHO_PENDENTE_DE_REVISAO_MEDICA",
        "subjetivo": "Paciente refere dor torácica há duas horas.",
        "objetivo": "Sem dados objetivos suficientes na transcrição.",
        "avaliacao": "Investigar origem cardiovascular.",
        "plano": "Solicito eletrocardiograma.",
        "alertas_revisao": [],
        "evidencias_chave": ["Dor torácica"],
    }
    doc = normalize_monolithic_soap_document(flat)
    ok, errors = validate_soap_document(doc, transcript="dor torácica há duas horas")
    assert ok, errors
    assert doc["soap"]["subjetivo"].startswith("Paciente refere")
    assert doc.get("subjetivo") is None


def test_normalize_monolithic_emr_english_to_pt_br_placeholders() -> None:
    from app.services.soap_validation import (
        EMPTY_AVALIACAO_TEXT,
        EMPTY_OBJETIVO_TEXT,
        EMPTY_PLANO_TEXT,
        EMPTY_SUBJETIVO_TEXT,
        monolithic_document_degraded,
        normalize_monolithic_soap_document,
    )

    emr = {
        "response": (
            '{'
            '"patient_id": "Luiz Amizinho", '
            '"chief_complaint": "Follow-up for kidney function and urinary bleeding.", '
            '"history_of_present_illness": "Patient is following up for concerns about kidney function.", '
            '"physical_exam": "Not explicitly mentioned in the provided text.", '
            '"investigations": ["Kidney ultrasound (cysts corticales in both kidneys)"], '
            '"assessment": ["Possible acute kidney injury vs. chronic kidney disease"], '
            '"plan": ["Order blood tests to assess kidney function (creatinine, etc.)."], '
            '"medications": ["Losartan (20mg daily) for hypertension"]'
            "}"
        ),
    }
    doc = normalize_monolithic_soap_document(emr, transcript="creatinina ecografia losartana")
    ok, errors = validate_soap_document(doc, transcript="creatinina ecografia losartana")
    assert ok, errors
    assert doc["status"] == EXPECTED_SOAP_STATUS
    assert doc["soap"]["subjetivo"] == EMPTY_SUBJETIVO_TEXT
    assert doc["soap"]["objetivo"] == EMPTY_OBJETIVO_TEXT
    assert doc["soap"]["avaliacao"] == EMPTY_AVALIACAO_TEXT
    assert doc["soap"]["plano"] == EMPTY_PLANO_TEXT
    assert monolithic_document_degraded(doc) is True
    assert "patient_id" not in doc
    assert "chief_complaint" not in doc


def test_parse_soap_section_json_keeps_flat_subjetivo() -> None:
    from app.services.soap_draft import _parse_soap_json

    raw = (
        '{"response":"{\\"subjetivo\\": \\"Paciente refere dor.\\", '
        '\\"alertas_revisao\\": [\\"trecho incerto\\"]}"}'
    )
    partial = _parse_soap_json(raw, monolithic=False)
    assert partial is not None
    assert partial.get("subjetivo") == "Paciente refere dor."
    assert "soap" not in partial

    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok, errors


def test_coerces_medgemma_response_text_wrapper_to_subjetivo() -> None:
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "response": {
                "text": (
                    "Paciente refere urina concentrada e aumento da creatinina. "
                    "Relata ingestão de 1,5 litros de água por dia."
                )
            }
        },
    )
    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok, errors
    assert "urina concentrada" in partial["subjetivo"]


def test_coerces_english_physical_exam_to_placeholder() -> None:
    partial = normalize_soap_section_partial(
        "objetivo",
        {
            "physical_exam": [
                "Patient is stable",
                "No acute concerns identified during physical exam",
            ],
        },
    )
    ok, errors = validate_soap_section("objetivo", partial)
    assert ok, errors
    assert partial["objetivo"] == EMPTY_OBJETIVO_TEXT


def test_coerces_english_emr_subjetivo_to_placeholder() -> None:
    partial = normalize_soap_section_partial(
        "subjetivo",
        {
            "response": (
                '{'
                '"patient_id": "Luiz", '
                '"chief_complaint": "Follow-up for kidney function.", '
                '"history_of_present_illness": "Patient is following up for concerns about kidney function.", '
                '"investigations": ["Kidney function tests"], '
                '"plan": ["Repeat kidney function tests"]'
                "}"
            ),
        },
    )
    ok, errors = validate_soap_section("subjetivo", partial)
    assert ok, errors
    assert partial["subjetivo"] == EMPTY_SUBJETIVO_TEXT
    assert partial.get("_schema_coerced") is True


def test_coerces_english_emr_objetivo_to_placeholder() -> None:
    partial = normalize_soap_section_partial(
        "objetivo",
        {
            "patient_name": "Luiz",
            "imaging_results": [
                "Kidneys are normal in size (right: 11.6 cm, left: 11.5 cm).",
                "Cortical cysts are present in both kidneys.",
            ],
            "lab_results": ["Creatinine levels are elevated."],
        },
    )
    ok, errors = validate_soap_section("objetivo", partial)
    assert ok, errors
    assert partial["objetivo"] == EMPTY_OBJETIVO_TEXT


def test_coerces_emr_objetivo_lists_to_narrative() -> None:
    partial = normalize_soap_section_partial(
        "objetivo",
        {
            "patient_name": "Luiz",
            "imaging_results": [
                "Rins com dimensões normais (11,6 cm à direita).",
                "Cistos corticais bilaterais.",
            ],
            "lab_results": ["Creatinina elevada."],
        },
    )
    ok, errors = validate_soap_section("objetivo", partial)
    assert ok, errors
    assert "Creatinina elevada." in partial["objetivo"]


def test_coerces_avaliacao_topic_dict_to_text() -> None:
    partial = normalize_soap_section_partial(
        "avaliacao",
        {
            "cistos corticais nos rins": "achado incidental",
            "aumento da creatinina": "investigar IRA versus DRC",
        },
    )
    ok, errors = validate_soap_section("avaliacao", partial)
    assert ok, errors
    assert "cistos corticais nos rins" in partial["avaliacao"]


def test_coerces_medgemma_response_text_wrapper_to_avaliacao() -> None:
    partial = normalize_soap_section_partial(
        "avaliacao",
        {
            "response": {
                "text": (
                    "Aqui estão os principais pontos identificados no texto:\n\n"
                    "* **Investigação de insuficiência renal aguda vs. doença renal crônica:** "
                    "O médico está investigando se o aumento da creatinina é agudo ou crônico.\n"
                    "* **Exames de sangue seriados:** Necessários para comparar temporalidade."
                )
            }
        },
    )
    ok, errors = validate_soap_section("avaliacao", partial)
    assert ok, errors
    assert "insuficiência renal aguda" in partial["avaliacao"]


def test_coerces_empty_avaliacao_schema_to_placeholder() -> None:
    partial = normalize_soap_section_partial("avaliacao", {})
    ok, errors = validate_soap_section("avaliacao", partial)
    assert ok, errors
    assert partial["avaliacao"] == (
        "Avaliação não explicitada de forma suficiente na consulta."
    )


def test_coerces_plan_conduta_typo_to_plano_conduta() -> None:
    partial = normalize_soap_section_partial(
        "plano",
        {
            "plan_conduta": "Solicitar exames.\nReforçar ingesta hídrica.",
            "alertas_revisao": [],
        },
    )
    ok, errors = validate_soap_section("plano", partial)
    assert ok, errors
    assert partial["plano_conduta"].startswith("Solicitar exames")
