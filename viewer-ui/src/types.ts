export type Stage = "approved" | "in-progress" | "verified" | "integrated" | "not-evaluated" | "canceled";
export const STAGES: Stage[] = ["approved", "in-progress", "verified", "integrated", "not-evaluated", "canceled"];

export interface Issue {
  code: string; message: string; entity?: string | null; path?: string | null;
  expected?: unknown; actual?: unknown; remediation?: string | null; severity?: string;
}
export interface Project {
  name: string; root: string; branch: string | null; detached: boolean; head: string | null; worktree: string | null;
  trunk_ref: string; viewer_version: string;
  components: { name: string; user_facing: boolean; target_ref: string; repo: string }[];
}
export interface Step { key: "approved" | "started" | "verified" | "integrated"; state: "done" | "pending" | "blocked" | "not-evaluated" | "canceled";
  ref: { kind: string; id: string } | null; detail: string | null; issue: Issue | null }
export interface Member {
  change_id: string; intent_revision: string; kind: string; title: string; stage: Stage; timeline: Step[]; diagnostic: Issue | null; current: boolean;
}
export interface EntityRef { kind: string; id: string; req?: string; cap?: string; revision?: string | null }
export interface Gate {
  scope: string; evaluated: boolean; ok: boolean; code: string | null; message?: string; entity?: string | null; expected?: unknown; actual?: unknown;
  remediation?: string | null; path?: string | null; entities?: EntityRef[]; run_id?: string; evidence?: string[]; head?: string;
}
export interface ContractSummary {
  cap: string; revision: string; issue: unknown; requirements: { id: string; title: string; acceptance_ids: string[] }[];
}
export interface Publication {
  commit: string; tag: string; remote: string; actor: string | null; reason: string | null; preparation: string | null; run_id: string | null;
  evidence_ids: string[]; provenance: Record<string, boolean>; partial: boolean; note: string | null;
}
export interface ReleaseDetail {
  component: string; version: string; kind: string; base_tag: string | null; status: "planning" | "published";
  members: Member[]; counts: Record<Stage, number>; total: number; contracts: ContractSummary[]; contracts_source: string | null;
  contracts_issue: Issue | null; policy: { enabled: boolean | null } | null; gate: Gate | null; publication: Publication | null;
  preparations: { id: string; run_id: string | null; head: string | null; evidence_ids: string[]; valid: boolean; issue: Issue | null }[];
}
export interface ReleaseRow { component: string; version: string; kind: string; status: string; members: number }
export interface ChangeDetail {
  id: string; revision: string; kind: string; title: string; intention: string; components: string[]; current: boolean; current_revision: string | null;
  revisions: { revision: string; current: boolean }[]; approval: { id: string; actor: string; reason: string } | null;
  stages: Record<string, { stage: Stage; steps: Step[]; diagnostic: Issue | null }>;
  requirements: { op: string; req: string; cap: string; components: string[]; proposed_revision: string | null; base_revisions: string[];
    retire_acceptance_ids: string[]; add_acceptance_ids: string[] }[];
  preserved: { cap: string; component: string; revision: string; issue: unknown; requirements: { id: string; title: string; acceptance_ids: string[] }[] }[];
  fixes: { component: string; commit: string; requirement_ids: string[]; acceptance_ids: string[]; backport: { commit: string } | null }[];
  baseline_release: { component: string; version: string } | null;
  releases: { component: string; version: string; status: string }[];
}
export type CriterionState = "covered" | "pending" | "unfavorable" | "stale" | "interrupted" | "not-evaluated" | "ambiguous";
export interface CheckResult { id: string; status: string; returncode: number | null; run_id: string }
export interface CoverageReport { id: string; kind: string; outcome: string; actor: string; acceptance_ids: string[]; state: string; run_id: string }
export interface Coverage {
  state: "evaluated" | "unavailable" | "no-scope"; message?: string;
  criteria: Record<string, { state: CriterionState; checks: CheckResult[]; reports: { id: string; state: string; outcome: string }[] }>;
  run?: { id: string; status: string; limitations: unknown[] } | null; stop?: { code: string; message: string } | null; candidate?: string;
  review?: { required: boolean | null; state?: string; reviews?: CoverageReport[] };
  reports?: CoverageReport[]; superseded_runs?: { id: string }[]; published?: boolean;
}
export interface RequirementDetail {
  id: string; cap: string; revision: string; source: string; components: string[]; statement: string;
  acceptance: { id: string; components: string[]; scenario: string }[]; identity: { introduced_by: string } | null;
  coverage: Record<string, Coverage>; context: { release: string | null; release_component: string | null; change: string | null; intent: string | null };
}
export interface EvidenceScope { component: string; release: string | null; change: string | null; intent: string | null }
export interface CriterionLink { ac: string; req: string; cap: string; revision: string }
export interface RunDetail {
  type: "run" | "check"; id: string; status: string; component: string; change_id: string | null; release: { version: string } | null;
  candidate: { head: string; base: string; dirty: boolean; inputs_digest: string; files: number; paths: number };
  checks: { id: string; argv: string[]; cwd: string; status: string; returncode: number | null; duration_seconds: number; acceptance_ids: string[];
    executed_by_roclec: boolean; limitation: string | null; environment: string[];
    logs: Record<"stdout" | "stderr", { size: number; complete: boolean; sha256: string }> }[];
  limitations: unknown[]; supersedes: string[]; superseded_by: string[]; executed_by_roclec: boolean; tools?: Record<string, { path: string; sha256: string } | null>;
  digest?: string; reports: { id: string; kind: string; outcome: string }[]; scope: EvidenceScope; criteria: CriterionLink[]; check?: RunDetail["checks"][number];
}
export interface ReportDetail {
  type: "report"; id: string; kind: string; outcome: string; actor: string; context: string; component: string; change_id: string | null;
  release: { version: string } | null; run_id: string; candidate_digest: string; acceptance_ids: string[]; checks: string[]; limitations: string[];
  findings: { id: string; description: string }[]; supersedes: string[]; superseded_by: string[]; state: string; executed_by_roclec: false;
  digest: string; scope: EvidenceScope; criteria: CriterionLink[];
}
export interface DocNode { name: string; path: string; type: "dir" | "file"; title?: string; children?: DocNode[] }
export interface SearchResult {
  type: "doc" | "entity"; path?: string; title: string; snippet: string | null; score: number; source?: string;
  kind?: string; id?: string; cap?: string | null; revision?: string | null; components?: string[]; contexts?: string[];
  link?: { component?: string; release?: string; change?: string; intent?: string; req?: string };
}
