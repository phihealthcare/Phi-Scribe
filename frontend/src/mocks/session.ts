import type { ConsultationSession } from "../api/types";

/**
 * Mock consultation session matching public/ui-template.jpeg, used when
 * VITE_USE_MOCK=true. Replace with a real API-backed session in a later phase.
 */
export const mockSession: ConsultationSession = {
  consultationId: "CN-40871",
  patientName: "Helena Marques",
  patientAge: 54,
  professionalName: "Dra. Camila Nunes",
  startedAt: "2026-07-08T14:22:00-03:00",
  status: "done",
  entities: ["Losartana 50 mg", "Cefaleia vespertina", "HAS"],
  transcript: [
    {
      start_ms: 3000,
      end_ms: 10000,
      speaker: "0",
      speaker_label: "MÉDICO",
      text: "Bom dia, Helena. Como a senhora está se sentindo desde a última consulta?",
    },
    {
      start_ms: 11000,
      end_ms: 23000,
      speaker: "1",
      speaker_label: "PACIENTE",
      text: "Bom dia, doutora. A dor de cabeça melhorou um pouco, mas ainda aparece no fim da tarde.",
    },
    {
      start_ms: 24000,
      end_ms: 30000,
      speaker: "0",
      speaker_label: "MÉDICO",
      text: "Certo. A senhora continuou tomando a losartana de 50 mg todos os dias?",
    },
    {
      start_ms: 31000,
      end_ms: 40000,
      speaker: "1",
      speaker_label: "PACIENTE",
      text: "Sim, toda manhã. Só esqueci uma vez no fim de semana.",
    },
    {
      start_ms: 42000,
      end_ms: 50000,
      speaker: "0",
      speaker_label: "MÉDICO",
      text: "Tudo bem. Vamos aferir sua pressão agora e ver como estão os valores hoje.",
    },
  ],
  soap: {
    subjetivo:
      "Cefaleia vespertina, em melhora. Refere boa adesão ao anti-hipertensivo.",
    objetivo: "Aferição de PA em andamento...",
    avaliacao: "HAS em acompanhamento; cefaleia provavelmente tensional.",
    plano: "Manter losartana 50 mg/dia; reavaliar em 30 dias.",
  },
};
