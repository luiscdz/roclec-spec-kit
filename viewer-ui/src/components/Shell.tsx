import { useContext, useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { AppContext } from "../context";
import brand from "../assets/brand/roclec-horizontal-color-fondo-oscuro.svg";

export function Shell() {
  const app = useContext(AppContext);
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const project = app.project;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (term.trim()) navigate(`/search?q=${encodeURIComponent(term.trim())}`);
  };
  return (
    <div className="shell">
      <a className="skip-link" href="#contenido">Saltar al contenido</a>
      <aside className="sidebar">
        <Link className="brand" to="/releases" aria-label="Roclec Technologies, ir a Releases"><img src={brand} alt="" width={188} /></Link>
        <form role="search" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="global-search">Buscar documentación, REQ o AC</label>
          <input id="global-search" type="search" placeholder="Buscar texto, REQ, AC…" value={term} onChange={(e) => setTerm(e.target.value)} />
          <button className="button" type="submit" style={{ padding: "6px 10px" }}>Buscar</button>
        </form>
        <div>
          <p className="sidebar-label">Proyecto</p>
          <nav aria-label="Secciones">
            <NavLink to="/releases"><span className="dot" aria-hidden="true" />Releases</NavLink>
            <NavLink to="/docs">Documentación</NavLink>
          </nav>
        </div>
        <div className="project-card">
          <strong>{project?.name ?? "Cargando proyecto…"}</strong>
          {project ? (
            <div className="meta">
              <div>{project.detached ? <>HEAD desacoplado <span className="mono">{project.head}</span></> : <>Rama <span className="mono">{project.branch}</span></>}</div>
              {project.worktree ? <div>Worktree <span className="mono">{project.worktree}</span></div> : null}
              <div className="mono root">{project.root}</div>
            </div>
          ) : null}
          <button className="button" style={{ marginTop: 12, width: "100%", justifyContent: "center" }} onClick={() => void app.refresh()} disabled={app.refreshing}>
            {app.refreshing ? "Actualizando…" : "Actualizar"}
          </button>
        </div>
      </aside>
      <main className="main" id="contenido" tabIndex={-1}>
        {app.changed ? (
          <div className="banner warn" role="status">
            <div className="grow"><strong>El repositorio cambió.</strong> Lo que ves puede mezclar estados distintos (rama, commits o archivos locales).</div>
            <button className="button primary" onClick={() => void app.refresh()} disabled={app.refreshing}>Recargar</button>
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
