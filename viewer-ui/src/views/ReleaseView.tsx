import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Badge, Crumbs, Empty, EntityLinks, IssueFields, Timeline } from "../components/Common";
import { StageBar } from "../components/StageBar";
import { KIND_LABEL, STAGE_LABEL, short } from "../labels";
import { changeHref, evidenceHref, releaseHref, requirementHref } from "../links";
import { STAGES, type Gate, type ReleaseDetail, type ReleaseRow, type Stage } from "../types";
import { useContext } from "react";
import { AppContext } from "../context";

const versionCompare = (a: string, b: string) => {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map(Number);
  const [x, y] = [parse(a), parse(b)];
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0);
  return 0;
};

/** Landing board: choose a component and version, then read the release. */
export function ReleaseBoard() {
  const { component, version } = useParams();
  const list = useQuery<{ releases: ReleaseRow[] }>(url("/releases"));
  const app = useContext(AppContext);
  const navigate = useNavigate();
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Releases</p>
          <h1>Qué falta para publicar</h1>
          <p className="lead">Avance por etapa de cada cambio, resultado del gate final y estado de la publicación.</p>
        </div>
      </header>
      <Async query={list}>{({ releases }) => {
        if (!releases.length) {
          return <div className="card"><Empty title="Este proyecto aún no tiene releases">Planifica una con <code>roclec release plan &lt;componente&gt; &lt;versión&gt; --change CHG-…</code> y vuelve a pulsar Actualizar.</Empty></div>;
        }
        const components = [...new Set(releases.map((r) => r.component))];
        const chosen = component && components.includes(component) ? component : (app.project?.components.find((c) => components.includes(c.name))?.name ?? components[0]);
        const versions = releases.filter((r) => r.component === chosen).sort((a, b) => versionCompare(b.version, a.version));
        if (!component || !version) {
          const pick = versions.find((r) => r.status === "planning") ?? versions[0];
          return <Navigate replace to={releaseHref(pick.component, pick.version)} />;
        }
        const exists = versions.some((r) => r.version === version);
        return (
          <>
            <div className="selectors" style={{ marginBottom: 20 }}>
              <label className="field">Componente
                <select value={chosen} onChange={(e) => {
                  const next = releases.filter((r) => r.component === e.target.value).sort((a, b) => versionCompare(b.version, a.version));
                  navigate(releaseHref(e.target.value, (next.find((r) => r.status === "planning") ?? next[0]).version));
                }}>{components.map((c) => <option key={c}>{c}</option>)}</select>
              </label>
              <label className="field">Versión
                <select value={version} onChange={(e) => navigate(releaseHref(chosen, e.target.value))}>
                  {versions.map((r) => <option key={r.version} value={r.version}>{r.version} · {r.status === "published" ? "publicada" : "en planificación"}</option>)}
                  {!exists ? <option value={version}>{version}</option> : null}
                </select>
              </label>
            </div>
            <ReleaseDetailView component={chosen} version={version} />
          </>
        );
      }}</Async>
    </>
  );
}

function summary(release: ReleaseDetail) {
  const { counts, total } = release;
  const base = `${counts.integrated} de ${total} cambios integrados`;
  if (release.status === "published") return `${base} · publicada`;
  if (total === 0) return "Sin cambios asignados";
  const gate = release.gate;
  if (!gate) return base;
  if (gate.ok) return `${base} · verificación final aprobada · publicación pendiente`;
  if (counts.integrated === total && gate.code === "COVERAGE_MISSING") return `${base} · verificación final pendiente`;
  if (counts.integrated === total) return `${base} · verificación final bloqueada`;
  return `${base} · faltan integraciones`;
}

function GateIndicator({ release }: { release: ReleaseDetail }) {
  const gate: Gate | null = release.gate;
  if (release.status === "published") {
    return (
      <div className="indicator ok">
        <h3>Gate final <Badge tone="neutral">Histórico</Badge></h3>
        <p className="muted">La release está publicada: se consulta el registro, no se vuelve a evaluar el gate sobre el árbol actual.</p>
        {release.publication?.run_id ? <p><Link to={evidenceHref(release.publication.run_id, { release: release.version, rc: release.component, component: release.component })}>Run final {release.publication.run_id}</Link></p> : <p className="muted">Este registro no conserva el run final.</p>}
      </div>
    );
  }
  if (!gate) return <div className="indicator"><h3>Gate final <Badge tone="neutral">Sin evaluar</Badge></h3></div>;
  const ctx = { release: release.version, rc: release.component };
  return (
    <div className={`indicator ${gate.ok ? "ok" : "bad"}`}>
      <h3>Gate final <Badge tone={gate.ok ? "ok" : "bad"}>{gate.ok ? "Aprobado" : "Bloqueado"}</Badge></h3>
      <p className="muted" style={{ margin: 0 }}>{gate.scope}. Se evalúa al abrir o actualizar; no ejecuta checks.</p>
      {gate.ok ? (
        <dl className="kv"><dt>Run</dt><dd>{gate.run_id ? <Link to={evidenceHref(gate.run_id, { ...ctx, component: release.component })}>{gate.run_id}</Link> : "—"}</dd>
          <dt>Evidencia</dt><dd>{gate.evidence?.length ? gate.evidence.map((e) => <Link key={e} to={evidenceHref(e, { ...ctx, component: release.component })}>{short(e, 12)} </Link>) : "Sin informes adicionales"}</dd>
          <dt>Commit</dt><dd className="mono">{short(gate.head, 12)}</dd></dl>
      ) : (
        <>
          <IssueFields issue={{ code: gate.code ?? "", message: gate.message ?? "", entity: gate.entity, path: gate.path, expected: gate.expected, actual: gate.actual, remediation: gate.remediation }} />
          <EntityLinks entities={gate.entities ?? []} ctx={ctx} />
        </>
      )}
    </div>
  );
}

function PublicationIndicator({ release }: { release: ReleaseDetail }) {
  const p = release.publication;
  if (!p) return <div className="indicator warn"><h3>Publicación <Badge tone="warn">Pendiente</Badge></h3><p className="muted" style={{ margin: 0 }}>Aún no hay un registro de publicación verificado para esta versión.</p></div>;
  return (
    <div className="indicator ok">
      <h3>Publicación <Badge tone="ok">Publicada</Badge></h3>
      <dl className="kv">
        <dt>Etiqueta</dt><dd className="mono">{p.tag}</dd><dt>Commit</dt><dd className="mono">{short(p.commit, 12)}</dd><dt>Remoto</dt><dd>{p.remote}</dd>
        {p.actor ? <><dt>Registrada por</dt><dd>{p.actor}</dd></> : null}{p.reason ? <><dt>Motivo</dt><dd>{p.reason}</dd></> : null}
        <dt>Procedencia</dt><dd>{Object.entries(p.provenance).map(([k, v]) => `${k}: ${v ? "sí" : "no"}`).join(" · ")}</dd>
      </dl>
      {p.partial ? <p className="note" style={{ marginTop: 10 }}>Procedencia parcial: este registro es válido, pero no conserva todos los detalles históricos{p.note ? ` (${p.note})` : ""}. Disponible: {Object.entries(p.provenance).filter(([, v]) => v).map(([k]) => k).join(", ") || "solo commit y etiqueta"}.</p> : null}
    </div>
  );
}

function ReleaseDetailView({ component, version }: { component: string; version: string }) {
  const query = useQuery<ReleaseDetail>(url(`/releases/${encodeURIComponent(component)}/${encodeURIComponent(version)}`));
  const [params, setParams] = useSearchParams();
  const selected = (STAGES as string[]).includes(params.get("stage") ?? "") ? (params.get("stage") as Stage) : null;
  const select = (stage: Stage | null) => setParams((p) => { const next = new URLSearchParams(p); if (stage) next.set("stage", stage); else next.delete("stage"); return next; });
  return (
    <Async query={query}>{(release) => {
      const rows = selected ? release.members.filter((m) => m.stage === selected) : release.members;
      const ctx = { release: release.version, rc: release.component };
      return (
        <>
          <Crumbs items={[{ label: "Releases", to: "/releases" }, { label: `${release.component} ${release.version}` }]} />
          <div className="page-header">
            <div>
              <h2 style={{ fontSize: 24, margin: 0 }}>{release.component} · {release.version}</h2>
              <p className="lead" style={{ marginTop: 6 }} aria-live="polite"><strong>{summary(release)}</strong></p>
            </div>
            <div className="row-actions">
              <Badge tone={release.status === "published" ? "ok" : ""}>{release.status === "published" ? "Publicada" : "En planificación"}</Badge>
              <Badge tone="neutral">{KIND_LABEL[release.kind] ?? release.kind}</Badge>
              {release.policy?.enabled ? <Badge tone="warn">Revisión independiente requerida</Badge> : null}
            </div>
          </div>
          <div className="grid-2"><GateIndicator release={release} /><PublicationIndicator release={release} /></div>
          <section className="section" aria-labelledby="etapas">
            <h2 id="etapas">Miembros por etapa <span className="count">{release.total} en total</span></h2>
            <StageBar counts={release.counts} total={release.total} selected={selected} onSelect={select} />
          </section>
          <section className="section" aria-labelledby="miembros">
            <h2 id="miembros">Cambios de la release <span className="count">{selected ? `Mostrando ${rows.length} de ${release.total} · ${STAGE_LABEL[selected]}` : `${rows.length} de ${release.total}`}</span></h2>
            {selected ? <p><button className="button ghost" onClick={() => select(null)}>Quitar filtro «{STAGE_LABEL[selected]}»</button></p> : null}
            {rows.length === 0 ? <div className="card"><Empty title={release.total === 0 ? "La release no tiene miembros" : "Ningún cambio en esta etapa"} /></div> : (
              <div className="table-scroll"><table>
                <thead><tr><th className="id">Cambio</th><th>Título</th><th>Tipo</th><th>Etapa</th><th>Línea de etapas</th></tr></thead>
                <tbody>{rows.map((m) => (
                  <tr key={m.change_id}>
                    <td className="id"><Link to={changeHref(m.change_id, m.intent_revision, { ...ctx, component: release.component })}>{m.change_id}</Link><div className="muted mono" title={m.intent_revision}>rev {short(m.intent_revision)}</div></td>
                    <td className="cell-title">{m.title}{!m.current ? <div><Badge tone="warn">Revisión sustituida</Badge></div> : null}</td>
                    <td>{KIND_LABEL[m.kind] ?? m.kind}</td>
                    <td><Badge tone={m.stage === "integrated" ? "ok" : m.stage === "not-evaluated" || m.stage === "canceled" ? "neutral" : ""}>{STAGE_LABEL[m.stage]}</Badge></td>
                    <td><Timeline steps={m.timeline} />{m.diagnostic ? <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{m.diagnostic.code}: {m.diagnostic.message}</div> : null}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </section>
          <section className="section" aria-labelledby="contrato">
            <h2 id="contrato">Contrato final {release.contracts_source === "proposals" ? <span className="count">provisional: propuestas aprobadas</span> : null}</h2>
            {release.contracts.length === 0 ? <div className="card muted">No hay un contrato final resoluble todavía{release.contracts_issue ? `: ${release.contracts_issue.message}` : ""}.</div> : release.contracts.map((c) => (
              <div className="table-scroll" key={c.cap} style={{ marginBottom: 12 }}><table>
                <caption>{c.cap} <span className="muted mono">rev {short(c.revision, 12)}</span></caption>
                <thead><tr><th className="id">Requisito</th><th>Enunciado</th><th>Criterios</th></tr></thead>
                <tbody>{c.requirements.map((r) => (
                  <tr key={r.id}><td className="id"><Link to={requirementHref(r.id, c.cap, c.revision, { ...ctx, component: release.component })}>{r.id}</Link></td><td className="cell-title">{r.title}</td><td className="mono">{r.acceptance_ids.join(", ")}</td></tr>))}</tbody>
              </table></div>))}
          </section>
          {release.preparations.length ? (
            <section className="section" aria-labelledby="preparaciones">
              <h2 id="preparaciones">Preparaciones <span className="count">registro histórico</span></h2>
              <div className="table-scroll"><table>
                <thead><tr><th>Preparación</th><th>Run</th><th>Commit</th><th>Validez</th></tr></thead>
                <tbody>{release.preparations.map((p) => (
                  <tr key={p.id}><td className="mono" title={p.id}>{short(p.id, 12)}</td><td>{p.run_id ? <Link to={evidenceHref(p.run_id, { ...ctx, component: release.component })}>{p.run_id}</Link> : "—"}</td><td className="mono">{short(p.head, 12)}</td>
                    <td>{p.valid ? <Badge tone="ok">Válida</Badge> : <Badge tone="bad">{p.issue?.code ?? "Inválida"}</Badge>}</td></tr>))}</tbody>
              </table></div>
            </section>
          ) : null}
        </>
      );
    }}</Async>
  );
}
