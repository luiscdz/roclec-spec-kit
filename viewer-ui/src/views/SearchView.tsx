import { Link, useSearchParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Badge, Crumbs, Empty } from "../components/Common";
import { changeHref, docHref, requirementHref } from "../links";
import { short } from "../labels";
import type { SearchResult } from "../types";

function entityLink(r: SearchResult) {
  const l = r.link ?? {};
  if (r.kind === "CHG") return changeHref(r.id!, r.revision!, { component: l.component });
  const req = r.kind === "AC" ? l.req! : r.id!;
  return requirementHref(req, r.cap!, r.revision!, { component: l.component ?? r.components?.[0], release: l.release, rc: l.release ? l.component : null, change: l.change, intent: l.intent });
}

export function SearchView() {
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const query = useQuery<{ query: string; results: SearchResult[]; truncated: boolean }>(q ? url("/search", { q }) : null);
  return (
    <>
      <Crumbs items={[{ label: "Búsqueda" }]} />
      <header className="page-header"><div><p className="eyebrow">Búsqueda</p><h1>{q ? `«${q}»` : "Buscar en el proyecto"}</h1>
        <p className="lead">Por texto, título, ruta o identificador exacto (<span className="mono">REQ-001</span>, <span className="mono">AC-001</span>, <span className="mono">CHG-001</span>).</p></div></header>
      {!q ? <div className="card"><Empty title="Escribe una consulta">Usa el cuadro de búsqueda del menú lateral.</Empty></div> : (
        <Async query={query}>{(data) => data.results.length === 0 ? <div className="card"><Empty title="Sin coincidencias">Prueba con otro término o un identificador exacto.</Empty></div> : (
          <>
            <p className="muted" aria-live="polite">{data.results.length} resultado{data.results.length === 1 ? "" : "s"}{data.truncated ? " (se muestran los primeros)" : ""}</p>
            <ul className="results">{data.results.map((r, i) => (
              <li key={i}>
                {r.type === "doc" ? (
                  <><Badge tone="neutral">Documento</Badge> <Link to={docHref(r.path!)}><strong>{r.title}</strong></Link><div className="path">{r.path}</div></>
                ) : (
                  <><Badge>{r.kind}</Badge> <Link to={entityLink(r)}><strong className="mono">{r.id}</strong> · {r.title}</Link>
                    <div className="path">{r.cap ? `${r.cap} · ` : ""}rev {short(r.revision, 12)} · {(r.components ?? []).join(", ")}</div>
                    <div className="path">{(r.contexts ?? []).join(" · ")}</div></>
                )}
                {r.snippet ? <p className="snippet">{r.snippet}</p> : null}
              </li>))}</ul>
          </>
        )}</Async>
      )}
    </>
  );
}
