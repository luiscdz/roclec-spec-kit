import { Link, useParams, useSearchParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Badge, Crumbs, type Crumb } from "../components/Common";
import { Markdown } from "../components/Markdown";
import { CANDIDATE_LABEL, CRITERION_LABEL, CRITERION_TONE, REPORT_STATE_LABEL, short } from "../labels";
import { changeHref, checkHref, evidenceHref, readCtx, releaseHref } from "../links";
import type { Coverage, RequirementDetail } from "../types";

const SOURCE: Record<string, string> = { integrated: "contrato integrado", proposal: "propuesta de un cambio" };

function CoverageCard({ component, coverage, detail, ctx }: { component: string; coverage: Coverage; detail: RequirementDetail; ctx: ReturnType<typeof readCtx> }) {
  const scope = { ...ctx, component };
  if (coverage.state !== "evaluated") {
    return <div className="card"><h3>{component}</h3><p className="muted" style={{ marginBottom: 0 }}>
      {coverage.state === "no-scope" ? "Abre este requisito desde una release o un cambio para ver su cobertura." : `Sin cobertura disponible: ${coverage.message ?? "no se pudo resolver el contexto"}.`}</p></div>;
  }
  return (
    <div className="card">
      <h3 style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span>{component}</span>
        <span className="row-actions">
          {coverage.run && coverage.candidate ? <Badge tone={coverage.candidate === "stale" ? "warn" : "neutral"}>{CANDIDATE_LABEL[coverage.candidate]}</Badge> : null}
          {coverage.published ? <Badge tone="neutral">Registro histórico</Badge> : null}
        </span>
      </h3>
      {coverage.run ? <p className="muted">Run: <Link to={evidenceHref(coverage.run.id, scope)}>{coverage.run.id}</Link> · {coverage.run.status}</p> : <p className="muted">Sin run finalizado para este alcance.</p>}
      {coverage.stop ? <p className="note">{coverage.stop.code === "COVERAGE_MISSING"
        ? <><strong>Aún no hay un run de verificación para este alcance.</strong> Los criterios están pendientes.</>
        : <><strong>El gate se detuvo antes de evaluar la cobertura:</strong> <span className="mono">{coverage.stop.code}</span> — {coverage.stop.message}. Los criterios sin conclusión aparecen como «Sin evaluar».</>}</p> : null}
      <div className="table-scroll" style={{ marginTop: 10 }}><table>
        <thead><tr><th className="id">Criterio</th><th>Estado</th><th>Checks</th><th>Informes</th></tr></thead>
        <tbody>{detail.acceptance.filter((a) => a.id in coverage.criteria).map((a) => { const c = coverage.criteria[a.id]; return (
          <tr key={a.id}>
            <td className="id">{a.id}</td>
            <td><Badge tone={CRITERION_TONE[c.state] as "ok"}>{CRITERION_LABEL[c.state]}</Badge></td>
            <td>{c.checks.length ? c.checks.map((k) => <div key={k.id}><Link to={checkHref(k.run_id, k.id, scope)}>{k.id}</Link> <span className="muted">· {k.status}</span></div>) : <span className="muted">Ningún check lo cubre</span>}</td>
            <td>{c.reports.length ? c.reports.map((r) => <div key={r.id}><Link to={evidenceHref(r.id, scope)}>{short(r.id, 14)}</Link> <span className="muted">· {REPORT_STATE_LABEL[r.state] ?? r.state}</span></div>) : <span className="muted">—</span>}</td>
          </tr>); })}</tbody>
      </table></div>
      {coverage.review?.required ? (
        <p style={{ marginTop: 12 }}><strong>Revisión independiente</strong> (condición separada): <Badge tone={coverage.review.state === "ready" ? "ok" : coverage.review.state === "changes-needed" ? "bad" : "warn"}>
          {{ ready: "Favorable", pending: "Pendiente", "changes-needed": "Requiere cambios", stale: "Desactualizada" }[coverage.review.state ?? "pending"]}</Badge></p>
      ) : null}
      {coverage.superseded_runs?.length ? <p className="muted">Intentos sustituidos: {coverage.superseded_runs.map((r) => <Link key={r.id} to={evidenceHref(r.id, scope)}>{short(r.id, 14)} </Link>)}</p> : null}
      {coverage.reports?.some((r) => r.state === "superseded") ? <p className="muted">Informes sustituidos: {coverage.reports.filter((r) => r.state === "superseded").map((r) => <Link key={r.id} to={evidenceHref(r.id, scope)}>{short(r.id, 14)} </Link>)}</p> : null}
    </div>
  );
}

export function RequirementView() {
  const { req = "" } = useParams();
  const [params] = useSearchParams();
  const ctx = readCtx(params);
  const query = useQuery<RequirementDetail>(url(`/requirements/${req}`, {
    cap: params.get("cap"), revision: params.get("revision"), component: ctx.component, release: ctx.release, release_component: ctx.rc, change: ctx.change, intent: ctx.intent }));
  return (
    <Async query={query}>{(detail) => {
      const crumbs: Crumb[] = [{ label: "Releases", to: "/releases" }];
      if (ctx.release && ctx.rc) crumbs.push({ label: `${ctx.rc} ${ctx.release}`, to: releaseHref(ctx.rc, ctx.release) });
      if (ctx.change) crumbs.push({ label: ctx.change, to: changeHref(ctx.change, ctx.intent ?? null, { release: ctx.release, rc: ctx.rc, component: ctx.component }) });
      crumbs.push({ label: detail.id });
      const scopeLabel = ctx.release ? `release ${ctx.rc ?? ""} ${ctx.release}` : ctx.change ? `cambio ${ctx.change}` : "sin release ni cambio";
      return (
        <>
          <Crumbs items={crumbs} />
          <div className="page-header">
            <div>
              <p className="eyebrow">{detail.cap} · revisión de contrato <span className="mono" title={detail.revision}>{short(detail.revision, 12)}</span></p>
              <h1>{detail.id}</h1>
            </div>
            <div className="row-actions">
              <Badge tone="neutral">{SOURCE[detail.source] ?? detail.source}</Badge>
              <Badge>{scopeLabel}</Badge>
            </div>
          </div>
          <section className="section" aria-labelledby="enunciado"><h2 id="enunciado">Enunciado</h2><Markdown source={detail.statement} />
            <p className="muted" style={{ marginTop: 8 }}>Componentes: {detail.components.join(", ")}{detail.identity ? ` · introducido por ${detail.identity.introduced_by}` : ""}</p></section>
          <section className="section" aria-labelledby="criterios"><h2 id="criterios">Criterios de aceptación aplicables <span className="count">{detail.acceptance.length}</span></h2>
            <div className="table-scroll"><table>
              <thead><tr><th className="id">Criterio</th><th>Escenario</th><th>Componentes</th></tr></thead>
              <tbody>{detail.acceptance.map((a) => <tr key={a.id}><td className="id">{a.id}</td><td className="cell-title"><Markdown source={a.scenario} plain /></td><td>{a.components.join(", ")}</td></tr>)}</tbody>
            </table></div></section>
          <section className="section" aria-labelledby="cobertura"><h2 id="cobertura">Cobertura por componente</h2>
            <div className="grid-coverage">{Object.entries(detail.coverage).map(([component, coverage]) => <CoverageCard key={component} component={component} coverage={coverage} detail={detail} ctx={ctx} />)}</div></section>
        </>
      );
    }}</Async>
  );
}
