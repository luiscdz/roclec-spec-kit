// Every deep link keeps its context in the query string so Back restores the filtered list.
export interface Ctx { release?: string | null; rc?: string | null; change?: string | null; intent?: string | null; component?: string | null }

export function qs(params: Record<string, string | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const text = q.toString();
  return text ? `?${text}` : "";
}
export const readCtx = (q: URLSearchParams): Ctx => ({
  release: q.get("release"), rc: q.get("rc"), change: q.get("change"), intent: q.get("intent"), component: q.get("component"),
});
export const ctxQuery = (c: Ctx) => ({ release: c.release, rc: c.rc, change: c.change, intent: c.intent, component: c.component });

export const releaseHref = (component: string, version: string, extra: Record<string, string | null | undefined> = {}) =>
  `/releases/${encodeURIComponent(component)}/${encodeURIComponent(version)}${qs(extra)}`;
export const changeHref = (id: string, revision: string | null, c: Ctx = {}) =>
  `/changes/${id}${qs({ revision, ...ctxQuery({ ...c, change: null, intent: null }) })}`;
export const requirementHref = (req: string, cap: string, revision: string, c: Ctx = {}) =>
  `/requirements/${req}${qs({ cap, revision, ...ctxQuery(c) })}`;
export const evidenceHref = (id: string, c: Ctx = {}) => `/evidence/${id}${qs(ctxQuery(c))}`;
export const checkHref = (run: string, check: string, c: Ctx = {}) => `/evidence/${run}/checks/${encodeURIComponent(check)}${qs(ctxQuery(c))}`;
export const docHref = (path: string) => `/docs/${path.split("/").map(encodeURIComponent).join("/")}`;
