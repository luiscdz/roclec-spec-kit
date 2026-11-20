import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import type { ApiError, Query } from "../api";
import { STEP_LABEL, STEP_STATE } from "../labels";
import type { EntityRef, Issue, Step } from "../types";
import { requirementHref } from "../links";

export function Badge({ tone = "", children }: { tone?: "ok" | "bad" | "warn" | "neutral" | ""; children: ReactNode }) {
  return <span className={`badge ${tone}`}><span className="pip" aria-hidden="true" />{children}</span>;
}

export function Loading() {
  return <div role="status" aria-live="polite" aria-label="Cargando"><div className="skeleton" style={{ width: "40%" }} /><div className="skeleton" /><div className="skeleton" style={{ width: "80%" }} /></div>;
}

const ERROR_TITLE: Record<string, string> = {
  not_found: "No se encontró el recurso", invalid_record: "Registro inválido", query_failed: "La consulta falló",
  repository_changed: "El repositorio cambió durante la lectura", invalid_query: "Consulta inválida",
};

export function ErrorState({ error, retry }: { error: ApiError; retry?: () => void }) {
  const issue = error.payload.issue as Issue | undefined;
  return (
    <div className="banner error" role="alert">
      <div className="grow">
        <strong>{ERROR_TITLE[error.kind] ?? "Error"}</strong>
        <div>{error.message}</div>
        <div className="muted mono">{error.code}{error.payload.entity ? ` · ${String(error.payload.entity)}` : ""}</div>
        {issue?.remediation ? <div>{issue.remediation}</div> : null}
        {error.payload.remediation ? <div>{String(error.payload.remediation)}</div> : null}
      </div>
      {retry ? <button className="button" onClick={retry}>Reintentar</button> : null}
    </div>
  );
}

/** Render a query's loading and error states, then its data. */
export function Async<T>({ query, children }: { query: Query<T>; children: (data: T) => ReactNode }) {
  if (query.error) return <ErrorState error={query.error} retry={query.reload} />;
  if (query.loading || query.data === null) return <Loading />;
  return <>{children(query.data)}</>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><h2>{title}</h2>{children}</div>;
}

export interface Crumb { label: string; to?: string }
export function Crumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Ruta de navegación">
      <ol>{items.map((c, i) => (
        <li key={i}>{c.to && i < items.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === items.length - 1 ? "page" : undefined}>{c.label}</span>}</li>
      ))}</ol>
    </nav>
  );
}

export function Timeline({ steps, large = false }: { steps: Step[]; large?: boolean }) {
  return (
    <ol className={`timeline${large ? " large" : ""}`} aria-label="Línea de etapas">
      {steps.map((s) => (
        <li key={s.key}>
          <span className={`step ${s.state}`} title={s.detail ?? undefined}>
            <span className="mark" aria-hidden="true" />
            <span>{STEP_LABEL[s.key]}<span className="visually-hidden">: {STEP_STATE[s.state]}</span></span>
            {large && s.state !== "done" && s.state !== "pending" ? <span className="step-detail">{STEP_STATE[s.state]}</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

const fmt = (value: unknown) => (typeof value === "string" ? value.replaceAll("\u0000", " ") : JSON.stringify(value));

export function IssueFields({ issue }: { issue: Issue }) {
  return (
    <dl className="kv">
      <dt>Código</dt><dd className="mono">{issue.code}</dd>
      <dt>Mensaje</dt><dd>{issue.message}</dd>
      {issue.entity ? <><dt>Entidad</dt><dd className="mono">{issue.entity}</dd></> : null}
      {issue.path ? <><dt>Ruta</dt><dd className="mono">{issue.path}</dd></> : null}
      {issue.expected != null ? <><dt>Esperado</dt><dd className="mono">{fmt(issue.expected)}</dd></> : null}
      {issue.actual != null ? <><dt>Actual</dt><dd className="mono">{fmt(issue.actual)}</dd></> : null}
      {issue.remediation ? <><dt>Remediación</dt><dd>{issue.remediation}</dd></> : null}
    </dl>
  );
}

export function EntityLinks({ entities, ctx }: { entities: EntityRef[]; ctx: { release?: string | null; rc?: string | null } }) {
  if (!entities.length) return null;
  return (
    <div className="entity-links" aria-label="Entidades identificadas">
      {entities.map((e) => {
        if (e.kind === "CHG") return <Link key={e.id} to={`/changes/${e.id}?release=${ctx.release ?? ""}&rc=${ctx.rc ?? ""}`}>{e.id}</Link>;
        if ((e.kind === "REQ" || e.kind === "AC") && e.req && e.cap && e.revision)
          return <Link key={e.id} to={requirementHref(e.req, e.cap, e.revision, { release: ctx.release, rc: ctx.rc, component: ctx.rc })}>{e.id}</Link>;
        if (e.kind === "RUN" || e.kind === "EVD") return <Link key={e.id} to={`/evidence/${e.id}`}>{e.id}</Link>;
        return <span key={e.id} className="mono">{e.id}</span>;
      })}
    </div>
  );
}
