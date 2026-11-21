import { Link, useLocation, useParams } from "react-router-dom";
import { url, useQuery } from "../api";
import { Async, Crumbs, Empty } from "../components/Common";
import { Markdown } from "../components/Markdown";
import { docHref } from "../links";
import type { DocNode } from "../types";

function Tree({ node, current }: { node: DocNode; current: string }) {
  if (node.type === "file") {
    return <li><Link to={docHref(node.path)} aria-current={node.path === current ? "page" : undefined} title={node.path}>{node.title ?? node.name}<span className="muted mono" style={{ display: "block", fontSize: 11 }}>{node.name}</span></Link></li>;
  }
  const open = !node.path || current.startsWith(node.path + "/");
  const body = <ul>{(node.children ?? []).map((c) => <Tree key={c.path} node={c} current={current} />)}</ul>;
  return node.path ? <li><details open={open}><summary>{node.name}</summary>{body}</details></li> : body;
}

export function DocsView() {
  const params = useParams();
  const path = decodeURIComponent(params["*"] ?? "");
  const location = useLocation();
  const tree = useQuery<DocNode>(url("/docs/tree"));
  const doc = useQuery<{ path: string; title: string; size: number; source: string; content: string }>(path ? url("/docs/file", { path }) : null);
  return (
    <>
      <Crumbs items={[{ label: "Documentación", to: "/docs" }, ...(path ? [{ label: path }] : [])]} />
      <header className="page-header"><div><p className="eyebrow">Documentación</p><h1>{path ? doc.data?.title ?? path : "Explorador de Markdown"}</h1>
        <p className="lead">Archivos de <code>docs/</code>, <code>specs/</code> y las referencias declaradas del proyecto.</p></div></header>
      <div className="docs-layout">
        <nav className="tree" aria-label="Árbol de documentos">
          <Async query={tree}>{(root) => (root.children?.length ? <Tree node={root} current={path} /> : <Empty title="Sin documentos">No hay Markdown en el alcance de lectura.</Empty>)}</Async>
        </nav>
        <div>
          {!path ? <div className="card"><Empty title="Elige un documento">Selecciona un archivo del árbol o usa la búsqueda del menú lateral.</Empty></div> : (
            <Async query={doc}>{(d) => (
              <>
                <p className="muted mono" style={{ marginTop: 0 }}>{d.path} · {(d.size / 1024).toFixed(1)} KiB · {d.source === "reference" ? "referencia declarada" : d.source}</p>
                <Markdown key={location.pathname} source={d.content} path={d.path} />
              </>
            )}</Async>
          )}
        </div>
      </div>
    </>
  );
}
