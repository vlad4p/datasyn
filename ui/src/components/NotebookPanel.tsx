import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = {
  id: string;
  className?: string;
  locale: UiLocale;
};

function notebookSrc(): string {
  const base = (import.meta.env.VITE_JUPYTER_URL || "http://127.0.0.1:8888").replace(/\/$/, "");
  const token = import.meta.env.VITE_JUPYTER_TOKEN?.trim();
  if (token) {
    const u = new URL(`${base}/lab`);
    u.searchParams.set("token", token);
    return u.toString();
  }
  return `${base}/lab`;
}

export function NotebookPanel({ id, className, locale }: Props) {
  const s = uiStrings(locale);
  const src = notebookSrc();

  return (
    <section
      id={id}
      className={`notebook-panel ${className ?? ""}`.trim()}
      aria-label={s.notebookIframeTitle}
    >
      <div className="notebook-panel__toolbar">
        <a className="notebook-panel__open" href={src} target="_blank" rel="noreferrer">
          {s.notebookOpenExternal}
        </a>
      </div>
      <iframe className="notebook-panel__frame" title={s.notebookIframeTitle} src={src} />
    </section>
  );
}
