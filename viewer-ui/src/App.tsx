import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { request } from "./api";
import { AppContext, type AppState } from "./context";
import { Shell } from "./components/Shell";
import { ErrorState } from "./components/Common";
import { ChangeView } from "./views/ChangeView";
import { DocsView } from "./views/DocsView";
import { EvidenceView } from "./views/EvidenceView";
import { ReleaseBoard } from "./views/ReleaseView";
import { RequirementView } from "./views/RequirementView";
import { SearchView } from "./views/SearchView";
import type { ApiError } from "./api";
import type { Project } from "./types";

export function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [generation, setGeneration] = useState(0);
  const [changed, setChanged] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [fatal, setFatal] = useState<ApiError | null>(null);
  const baseline = useRef<string | null>(null);

  const observe = useCallback((stateId: string) => {
    if (baseline.current === null) baseline.current = stateId;
    else if (baseline.current !== stateId) setChanged(true);
  }, []);
  const markChanged = useCallback(() => setChanged(true), []);

  const load = useCallback(async (reset: boolean) => {
    try {
      const env = await request<Project>(reset ? "/api/v1/refresh" : "/api/v1/project", reset ? { method: "POST" } : undefined);
      baseline.current = env.state_id;
      setProject(env.data); setChanged(false); setFatal(null);
    } catch (error) { setFatal(error as ApiError); }
  }, []);
  useEffect(() => { void load(false); }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load(true);
    setGeneration((g) => g + 1);
    setRefreshing(false);
  }, [load]);

  const value: AppState = useMemo(() => ({ project, generation, changed, refreshing, observe, markChanged, refresh }),
    [project, generation, changed, refreshing, observe, markChanged, refresh]);

  if (fatal && !project) return <main className="main" style={{ margin: "40px auto" }}><ErrorState error={fatal} retry={() => void load(false)} /></main>;
  return (
    <AppContext.Provider value={value}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate replace to="/releases" />} />
          <Route path="releases/:component?/:version?" element={<ReleaseBoard />} />
          <Route path="changes/:id" element={<ChangeView />} />
          <Route path="requirements/:req" element={<RequirementView />} />
          <Route path="evidence/:id" element={<EvidenceView />} />
          <Route path="evidence/:id/checks/:check" element={<EvidenceView />} />
          <Route path="docs/*" element={<DocsView />} />
          <Route path="search" element={<SearchView />} />
          <Route path="*" element={<div className="card"><h2>Página no encontrada</h2><p><a href="/releases">Volver a Releases</a></p></div>} />
        </Route>
      </Routes>
    </AppContext.Provider>
  );
}
