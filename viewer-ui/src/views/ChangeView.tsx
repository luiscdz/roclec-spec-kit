import { Link, useParams, useSearchParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Badge, Crumbs, Timeline, type Crumb } from "../components/Common";
import { Markdown } from "../components/Markdown";
import { KIND_LABEL, OP_LABEL, STAGE_LABEL, short } from "../labels";
import { changeHref, readCtx, releaseHref, requirementHref } from "../links";
import type { ChangeDetail } from "../types";

export function ChangeView() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const ctx = readCtx(params);
  const query = useQuery<ChangeDetail>(url(`/changes/${id}`, { revision: params.get("revision"), component: ctx.component }));
  return (
    <Async query={query}>{(change) => {
      const crumbs: Crumb[] = [{ label: "Releases", to: "/releases" }];
      if (ctx.release && ctx.rc) crumbs.push({ label: `${ctx.rc} ${ctx.release}`, to: releaseHref(ctx.rc, ctx.release) });
      crumbs.push({ label: change.id });
      const pass = { ...ctx, change: change.id, intent: change.revision };
      return (
        <>
          <Crumbs items={crumbs} />
          <div className="page-header">
            <div>
              <p className="eyebrow">{KIND_LABEL[change.kind] ?? change.kind} · revisión <span className="mono" title={change.revision}>{short(change.revision, 12)}</span></p>
              <h1>{change.id}</h1>
              <p className="lead">{change.title}</p>
            </div>
            <div className="row-actions">
              {change.approval ? <Badge tone="ok">Aprobado por {change.approval.actor}</Badge> : <Badge tone="warn">Sin aprobación</Badge>}
              {!change.current ? <Badge tone="warn">Revisión sustituida</Badge> : null}
            </div>
          </div>
          {change.revisions.length > 1 ? (
            <nav aria-label="Revisiones aprobadas" className="note" style={{ marginBottom: 18 }}>
              Revisiones: {change.revisions.map((r) => (
                <span key={r.revision} style={{ marginRight: 10 }}>{r.revision === change.revision ? <strong className="mono">{short(r.revision)}</strong> : <Link className="mono" to={changeHref(change.id, r.revision, ctx)}>{short(r.revision)}</Link>}{r.current ? " (vigente)" : ""}</span>))}
            </nav>
          ) : null}
          <section className="section" aria-labelledby="etapas"><h2 id="etapas">Etapas por componente</h2>
            <div className="table-scroll"><table>
              <thead><tr><th>Componente</th><th>Etapa</th><th>Línea de etapas</th></tr></thead>
              <tbody>{change.components.map((c) => { const s = change.stages[c]; return (
                <tr key={c} style={c === ctx.component ? { background: "var(--violet-wash)" } : undefined}>
                  <td className="id">{c}{c === ctx.component ? <span className="visually-hidden"> (contexto actual)</span> : null}</td>
                  <td><Badge tone={s.stage === "integrated" ? "ok" : s.stage === "not-evaluated" ? "neutral" : ""}>{STAGE_LABEL[s.stage]}</Badge></td>
                  <td><Timeline steps={s.steps} large />{s.diagnostic ? <p className="muted" style={{ marginBottom: 0 }}>{s.diagnostic.code}: {s.diagnostic.message}</p> : null}</td>
                </tr>); })}</tbody>
            </table></div>
          </section>
          <section className="section" aria-labelledby="requisitos">
            <h2 id="requisitos">Requisitos afectados</h2>
            {change.requirements.length === 0 && change.preserved.length === 0 ? <div className="card muted">Este cambio no declara deltas normativos ni contratos de base.</div> : null}
            {change.requirements.length ? (
              <div className="table-scroll"><table>
                <thead><tr><th>Operación</th><th className="id">Requisito</th><th>Capacidad</th><th>Componentes</th><th>Revisiones</th></tr></thead>
                <tbody>{change.requirements.map((r, i) => (
                  <tr key={i}>
                    <td>{OP_LABEL[r.op] ?? r.op}</td>
                    <td className="id">{r.proposed_revision ? <Link to={requirementHref(r.req, r.cap, r.proposed_revision, { ...pass, component: r.components[0] })}>{r.req}</Link> : r.base_revisions[0] ? <Link to={requirementHref(r.req, r.cap, r.base_revisions[0], { ...pass, component: r.components[0] })}>{r.req}</Link> : r.req}</td>
                    <td className="mono">{r.cap}</td><td>{r.components.join(", ")}</td>
                    <td><div className="row-actions">
                      {r.base_revisions.map((b) => <Link key={b} to={requirementHref(r.req, r.cap, b, { ...pass, component: r.components[0] })}>Base {short(b)}</Link>)}
                      {r.proposed_revision ? <Link to={requirementHref(r.req, r.cap, r.proposed_revision, { ...pass, component: r.components[0] })}>Propuesta {short(r.proposed_revision)}</Link> : null}
                    </div>
                      {r.add_acceptance_ids.length || r.retire_acceptance_ids.length ? <div className="muted" style={{ fontSize: 12 }}>{r.add_acceptance_ids.length ? `+ ${r.add_acceptance_ids.join(", ")} ` : ""}{r.retire_acceptance_ids.length ? `− ${r.retire_acceptance_ids.join(", ")}` : ""}</div> : null}</td>
                  </tr>))}</tbody>
              </table></div>
            ) : null}
            {change.preserved.map((p) => (
              <div className="table-scroll" key={`${p.cap}-${p.component}`} style={{ marginTop: 12 }}><table>
                <caption>Contrato de base preservado · {p.cap} · {p.component} <span className="muted mono">rev {short(p.revision, 12)}</span></caption>
                <thead><tr><th className="id">Requisito</th><th>Enunciado</th><th>Criterios</th></tr></thead>
                <tbody>{p.requirements.map((r) => (
                  <tr key={r.id}><td className="id"><Link to={requirementHref(r.id, p.cap, p.revision, { ...pass, component: p.component })}>{r.id}</Link></td><td className="cell-title">{r.title}</td><td className="mono">{r.acceptance_ids.join(", ")}</td></tr>))}</tbody>
              </table></div>))}
            {change.fixes.length ? (
              <div className="card" style={{ marginTop: 12 }}><h3>Alcance declarado de la corrección</h3>
                <ul>{change.fixes.map((f, i) => <li key={i}><strong>{f.component}</strong> · commit <span className="mono">{short(f.commit, 12)}</span> · {f.requirement_ids.join(", ")} / {f.acceptance_ids.join(", ")}{f.backport ? ` · backport ${short(f.backport.commit, 12)}` : ""}</li>)}</ul>
                {change.baseline_release ? <p className="muted">Línea base: {change.baseline_release.component} {change.baseline_release.version}</p> : null}</div>
            ) : null}
          </section>
          <section className="section" aria-labelledby="propuesta"><h2 id="propuesta">Propuesta aprobada</h2><Markdown source={change.intention} /></section>
          {change.releases.length ? (
            <section className="section"><h2>Releases que lo incluyen</h2>
              <ul>{change.releases.map((r) => <li key={`${r.component}${r.version}`}><Link to={releaseHref(r.component, r.version)}>{r.component} {r.version}</Link> · {r.status === "published" ? "publicada" : "en planificación"}</li>)}</ul></section>
          ) : null}
        </>
      );
    }}</Async>
  );
}
