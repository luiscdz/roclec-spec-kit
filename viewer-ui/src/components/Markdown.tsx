import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import { docHref } from "../links";

const SAFE = /^(https?:|mailto:)/i;

/** Resolve a relative path against the document's folder, refusing to leave the project. */
export function resolveRelative(base: string, target: string): string | null {
  const parts = base.split("/").slice(0, -1);
  for (const piece of target.split("/")) {
    if (piece === "" || piece === ".") continue;
    if (piece === "..") { if (!parts.length) return null; parts.pop(); } else parts.push(piece);
  }
  return parts.join("/");
}

interface Props { source: string; path?: string; plain?: boolean }

/** Markdown without raw HTML; only http(s), mailto, anchors and project-relative links survive. */
export function Markdown({ source, path, plain = false }: Props) {
  return (
    <div className={`markdown${plain ? " plain" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(value, key) => {
          if (SAFE.test(value) || value.startsWith("#")) return defaultUrlTransform(value);
          if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//") || value.startsWith("/")) return "";
          return key === "src" || key === "href" ? value : "";
        }}
        components={{
          a({ href, children }) {
            if (!href) return <span>{children}</span>;
            if (SAFE.test(href)) return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
            if (href.startsWith("#")) return <a href={href}>{children}</a>;
            const [file, anchor] = href.split("#");
            const resolved = path ? resolveRelative(path, decodeURIComponent(file)) : null;
            if (resolved && /\.(md|markdown)$/i.test(resolved)) return <Link to={docHref(resolved) + (anchor ? `#${anchor}` : "")}>{children}</Link>;
            return <span title="Enlace fuera del alcance de lectura">{children}</span>;
          },
          img({ src, alt }) {
            const resolved = src && path ? resolveRelative(path, decodeURIComponent(src)) : null;
            if (!resolved) return <span className="muted">[imagen fuera del alcance: {alt}]</span>;
            return <img src={`/api/v1/docs/asset?path=${encodeURIComponent(resolved)}`} alt={alt ?? ""} loading="lazy" />;
          },
          table({ children }) { return <div className="md-table-wrap"><table>{children}</table></div>; },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
