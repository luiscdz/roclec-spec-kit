import type { CriterionState, Stage } from "./types";

export const STAGE_LABEL: Record<Stage, string> = {
  approved: "Aprobado", "in-progress": "En curso", verified: "Verificado", integrated: "Integrado",
  "not-evaluated": "Sin evaluar", canceled: "Cancelado",
};
export const STEP_LABEL: Record<string, string> = { approved: "Aprobado", started: "Iniciado", verified: "Verificado", integrated: "Integrado" };
export const STEP_STATE: Record<string, string> = { done: "hecho", pending: "pendiente", blocked: "bloqueado", "not-evaluated": "sin evaluar", canceled: "cancelado" };
export const CRITERION_LABEL: Record<CriterionState, string> = {
  covered: "Cubierto", pending: "Pendiente", unfavorable: "Desfavorable", stale: "Desactualizado",
  interrupted: "Interrumpido", "not-evaluated": "Sin evaluar", ambiguous: "Ambiguo",
};
export const CRITERION_TONE: Record<CriterionState, string> = {
  covered: "ok", pending: "warn", unfavorable: "bad", stale: "warn", interrupted: "bad", "not-evaluated": "neutral", ambiguous: "bad",
};
export const REPORT_STATE_LABEL: Record<string, string> = {
  applicable: "Aplicable", unfavorable: "Desfavorable", superseded: "Sustituida", stale: "Desactualizada", current: "Vigente",
};
export const KIND_LABEL: Record<string, string> = { evolution: "Evolución", fix: "Corrección", refactor: "Refactor", chore: "Tarea técnica", release: "Release", hotfix: "Hotfix", bugfix: "Bugfix" };
export const OP_LABEL: Record<string, string> = { add: "Añade", retire: "Retira", revise: "Revisa", replace: "Reemplaza" };
export const REPORT_KIND_LABEL: Record<string, string> = { manual: "Observación manual", "automated-import": "Importación automática", "independent-review": "Revisión independiente" };
export const CANDIDATE_LABEL: Record<string, string> = {
  current: "Candidato vigente", stale: "Candidato desactualizado", recorded: "Candidato registrado", unknown: "Candidato sin determinar",
};
export const short = (value: string | null | undefined, n = 8) => (value ? value.slice(0, n) : "—");
