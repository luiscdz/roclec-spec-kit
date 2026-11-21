import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { AppContext } from "./context";

export class ApiError extends Error {
  kind: string; code: string; status: number; payload: Record<string, unknown>;
  constructor(status: number, payload: Record<string, unknown>) {
    super(String(payload.message ?? "Falló la consulta"));
    this.status = status; this.kind = String(payload.kind ?? "query_failed"); this.code = String(payload.code ?? "ERROR"); this.payload = payload;
  }
}
export interface Envelope<T> { ok: true; state_id: string; data: T }

export async function request<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, { kind: "query_failed", code: "UNREACHABLE", message: "No se pudo contactar con el visor local. ¿Sigue ejecutándose `roclec view`?" });
  }
  let body: { ok: boolean; error?: Record<string, unknown> } & Partial<Envelope<T>>;
  try { body = await response.json(); } catch { throw new ApiError(response.status, { kind: "query_failed", code: "BAD_RESPONSE", message: "Respuesta inesperada del visor" }); }
  if (!response.ok || !body.ok) throw new ApiError(response.status, body.error ?? { message: response.statusText });
  return body as Envelope<T>;
}

export const url = (path: string, params: Record<string, string | null | undefined> = {}) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const text = q.toString();
  return `/api/v1${path}${text ? `?${text}` : ""}`;
};

export interface Query<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void }

/** Fetch one projection; re-runs when the path changes or the user refreshes the project. */
export function useQuery<T>(path: string | null): Query<T> {
  const app = useContext(AppContext);
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({ data: null, error: null, loading: path !== null });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);
  useEffect(() => {
    if (path === null) { setState({ data: null, error: null, loading: false }); return; }
    const id = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    request<T>(path).then(
      (env) => { if (id === latest.current) { app.observe(env.state_id); setState({ data: env.data, error: null, loading: false }); } },
      (error: ApiError) => { if (id === latest.current) { if (error.kind === "repository_changed") app.markChanged(); setState({ data: null, error, loading: false }); } },
    );
  }, [path, tick, app.generation]); // eslint-disable-line react-hooks/exhaustive-deps
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
