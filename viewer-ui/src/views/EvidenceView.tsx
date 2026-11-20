import { Link, useParams, useSearchParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Badge, Crumbs, type Crumb } from "../components/Common";
import { REPORT_KIND_LABEL, REPORT_STATE_LABEL, short } from "../labels";
import { changeHref, evidenceHref, readCtx, releaseHref, requirementHref } from "../links";
import type { CriterionLink, EvidenceScope, ReportDetail, RunDetail } from "../types";

const tone = (status: string) => (status === "pass" || status === "ready" ? "ok" : status === "fail" || status === "changes-needed" || status === "interrupted" ? "bad" : "warn");

function Criteria({ links, scope }: { links: CriterionLink[]; scope: EvidenceScope }) {
  if (!links.length) return <p className="muted">No se pudieron resolver los criterios en su contexto.</p>;
  const ctx = { release: scope.release, rc: scope.release ? scope.component : null, component: scope.component, change: scope.change, intent: scope.intent };
  return <div className="entity-links">{links.map((l) => <Link key={l.ac} to={requirementHref(l.req, l.cap, l.revision, ctx)} title={`Volver al criterio ${l.ac} en ${l.req}`}>{l.ac} · {l.req}</Link>)}</div>;
}

export function EvidenceView() {
  const { id = "", check } = useParams();
  const [params] = useSearchParams();
  const ctx = readCtx(params);
  const query = useQuery<RunDetail | ReportDetail>(check ? url(`/evidence/${id}/checks/${encodeURIComponent(check)}`) : url(`/evidence/${id}`));
  return (
    <Async query={query}>{(data) => {
      const crumbs: Crumb[] = [{ label: "Releases", to: "/releases" }];
      if (ctx.release && ctx.rc) crumbs.push({ label: `${ctx.rc} ${ctx.release}`, to: releaseHref(ctx.rc, ctx.release) });
      if (ctx.change) crumbs.push({ label: ctx.change, to: changeHref(ctx.change, ctx.intent ?? null, { release: ctx.release, rc: ctx.rc, component: ctx.component }) });
      crumbs.push({ label: check ? `${id} · ${check}` : id });
      const scope = data.scope;
      return (
        <>
          <Crumbs items={crumbs} />
          {data.type === "report" ? <Report data={data} scope={scope} ctx={ctx} /> : <Run data={data} scope={scope} focus={check} ctx={ctx} />}
        </>
      );
    }}</Async>
  );
}

function Scope({ scope }: { scope: EvidenceScope }) {
  return <>{scope.component}{scope.release ? ` · release ${scope.release}` : scope.change ? ` · cambio ${scope.change}` : ""}</>;
}

function Report({ data, scope, ctx }: { data: ReportDetail; scope: EvidenceScope; ctx: ReturnType<typeof readCtx> }) {
  const review = data.kind === "independent-review";
  return (
    <>
      <div className="page-header">
        <div><p className="eyebrow">{REPORT_KIND_LABEL[data.kind] ?? data.kind} · <Scope scope={scope} /></p><h1 className="mono" style={{ fontSize: 22 }}>{data.id}</h1></div>
        <div className="row-actions"><Badge tone={tone(data.outcome)}>{data.outcome}</Badge><Badge tone={data.state === "current" ? "ok" : "warn"}>{REPORT_STATE_LABEL[data.state] ?? data.state}</Badge></div>
      </div>
      <p className="note"><strong>Declarado, no ejecutado por Roclec.</strong> {data.actor} afirma esta observación{review ? " como revisión independiente (condición separada de los checks)" : ""}. Contexto: {data.context}</p>
      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card"><h3>Procedencia</h3><dl className="kv">
          <dt>Observador</dt><dd>{data.actor}</dd><dt>Run</dt><dd><Link to={evidenceHref(data.run_id, ctx)}>{data.run_id}</Link></dd>
          <dt>Candidato</dt><dd className="mono" title={data.candidate_digest}>{short(data.candidate_digest, 16)}</dd><dt>Registro</dt><dd className="mono" title={data.digest}>{short(data.digest, 16)}</dd>
          {data.supersedes.length ? <><dt>Sustituye a</dt><dd>{data.supersedes.map((s) => <Link key={s} to={evidenceHref(s, ctx)}>{short(s, 14)} </Link>)}</dd></> : null}
          {data.superseded_by.length ? <><dt>Sustituida por</dt><dd>{data.superseded_by.map((s) => <Link key={s} to={evidenceHref(s, ctx)}>{short(s, 14)} </Link>)}</dd></> : null}</dl></div>
        <div className="card"><h3>Criterios</h3><Criteria links={data.criteria} scope={scope} />{!data.criteria.length && data.acceptance_ids.length ? <p className="mono">{data.acceptance_ids.join(", ")}</p> : null}</div>
      </div>
      <section className="section"><h2>Observaciones</h2>{data.checks.length ? <ul>{data.checks.map((c, i) => <li key={i}>{c}</li>)}</ul> : <p className="muted">Sin observaciones declaradas.</p>}</section>
      <section className="section"><h2>Limitaciones</h2>{data.limitations.length ? <ul>{data.limitations.map((c, i) => <li key={i}>{c}</li>)}</ul> : <p className="muted">Sin limitaciones declaradas.</p>}</section>
      {data.findings.length ? <section className="section"><h2>Hallazgos</h2><div className="table-scroll"><table><thead><tr><th className="id">ID</th><th>Descripción</th></tr></thead><tbody>{data.findings.map((f) => <tr key={f.id}><td className="id">{f.id}</td><td>{f.description}</td></tr>)}</tbody></table></div></section> : null}
    </>
  );
}

function Run({ data, scope, focus, ctx }: { data: RunDetail; scope: EvidenceScope; focus?: string; ctx: ReturnType<typeof readCtx> }) {
  const checks = data.checks;
  return (
    <>
      <div className="page-header">
        <div><p className="eyebrow">Run ejecutado por Roclec · <Scope scope={scope} /></p><h1 className="mono" style={{ fontSize: 22 }}>{data.id}</h1></div>
        <div className="row-actions"><Badge tone={tone(data.status)}>{data.status === "unfinished" ? "Interrumpido sin finalizar" : data.status}</Badge></div>
      </div>
      {data.limitations.length ? <div className="banner warn" role="status"><div className="grow"><strong>Limitaciones registradas:</strong> {data.limitations.map((l) => (typeof l === "string" ? l : JSON.stringify(l))).join(" · ")}</div></div> : null}
      <div className="grid-2">
        <div className="card"><h3>Candidato</h3><dl className="kv">
          <dt>Commit</dt><dd className="mono">{short(data.candidate.head, 12)}</dd><dt>Base</dt><dd className="mono">{short(data.candidate.base, 12)}</dd>
          <dt>Árbol sucio</dt><dd>{data.candidate.dirty ? "Sí al capturarlo" : "No"}</dd><dt>Entradas</dt><dd>{data.candidate.files} archivos de entrada · {data.candidate.paths} rutas clasificadas</dd>
          <dt>Resumen</dt><dd className="mono" title={data.candidate.inputs_digest}>{short(data.candidate.inputs_digest, 16)}</dd></dl></div>
        <div className="card"><h3>Criterios y procedencia</h3><Criteria links={data.criteria} scope={scope} />
          <dl className="kv"><dt>Ejecución</dt><dd>{data.executed_by_roclec ? "Roclec ejecutó los checks" : "No ejecutado por Roclec"}</dd>
            {data.supersedes.length ? <><dt>Sustituye a</dt><dd>{data.supersedes.map((s) => <Link key={s} to={evidenceHref(s, ctx)}>{short(s, 14)} </Link>)}</dd></> : null}
            {data.superseded_by.length ? <><dt>Sustituido por</dt><dd>{data.superseded_by.map((s) => <Link key={s} to={evidenceHref(s, ctx)}>{short(s, 14)} </Link>)}</dd></> : null}</dl></div>
      </div>
      <section className="section"><h2>Checks <span className="count">{checks.length}</span></h2>
        {checks.length === 0 ? <div className="card muted">Este run no terminó de registrar resultados.</div> : (
          <div className="table-scroll"><table>
            <thead><tr><th className="id">Check</th><th>Resultado</th><th>Comando</th><th>Criterios</th><th>Logs (metadatos)</th></tr></thead>
            <tbody>{checks.map((c) => (
              <tr key={c.id} style={c.id === focus ? { background: "var(--violet-wash)" } : undefined}>
                <td className="id">{c.id === focus ? c.id : <Link to={`/evidence/${data.id}/checks/${encodeURIComponent(c.id)}${window.location.search}`}>{c.id}</Link>}</td>
                <td><Badge tone={tone(c.status)}>{c.status}</Badge><div className="muted">código {c.returncode ?? "—"} · {c.duration_seconds.toFixed(2)} s</div>{c.limitation ? <div className="muted">{c.limitation}</div> : null}</td>
                <td className="mono cell-title">{c.argv.join(" ")}<div className="muted">cwd {c.cwd}</div></td>
                <td className="mono">{c.acceptance_ids.join(", ") || "—"}</td>
                <td className="muted">{(["stdout", "stderr"] as const).map((l) => <div key={l}>{l}: {c.logs[l].size} B · {c.logs[l].complete ? "completo" : "incompleto"} · <span className="mono">{short(c.logs[l].sha256)}</span></div>)}</td>
              </tr>))}</tbody>
          </table></div>)}
        <p className="muted" style={{ marginTop: 8 }}>El visor no muestra el contenido de los logs crudos; solo los metadatos que deja el manifiesto.</p>
      </section>
      {data.reports.length ? <section className="section"><h2>Informes sobre este run</h2><ul>{data.reports.map((r) => <li key={r.id}><Link to={evidenceHref(r.id, ctx)}>{short(r.id, 14)}</Link> · {REPORT_KIND_LABEL[r.kind] ?? r.kind} · {r.outcome}</li>)}</ul></section> : null}
    </>
  );
}
