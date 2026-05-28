import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { OpenRouterModelItem } from "../api";
import { getOpenRouterModels, setChatModel } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

const STORAGE_KEY = "datasyn-chat-model";

type Props = {
  locale: UiLocale;
  modelProvider?: string;
  hasOpenRouterKey?: boolean;
  chatModel: string;
  onModelChange: (modelId: string) => void;
  disabled?: boolean;
};

export function readStoredChatModel(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v && v.trim() ? v.trim() : null;
  } catch {
    return null;
  }
}

export function persistChatModel(modelId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, modelId);
  } catch {
    /* ignore */
  }
}

export function ModelSwitch({
  locale,
  modelProvider,
  hasOpenRouterKey,
  chatModel,
  onModelChange,
  disabled = false,
}: Props) {
  const m = uiStrings(locale).modelSwitch;
  const canSwitch = modelProvider === "openrouter" && hasOpenRouterKey && !disabled;
  const [open, setOpen] = useState(false);
  const [freeOnly, setFreeOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [models, setModels] = useState<OpenRouterModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const loadModels = useCallback(async () => {
    if (!canSwitch) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getOpenRouterModels({ freeOnly });
      if (res.status !== "ok") {
        setModels([]);
        setError(res.error ?? m.loadFailed);
        return;
      }
      setModels(res.models ?? []);
    } catch (e) {
      setModels([]);
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [canSwitch, freeOnly, m.loadFailed]);

  useEffect(() => {
    if (!open || !canSwitch) return;
    void loadModels();
  }, [open, canSwitch, loadModels]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return models;
    return models.filter(
      (item) =>
        item.id.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        (item.description || "").toLowerCase().includes(q),
    );
  }, [models, search]);

  const pickModel = async (modelId: string) => {
    if (!modelId || modelId === chatModel) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      const res = await setChatModel(modelId);
      persistChatModel(modelId);
      onModelChange(res.chat_model);
      setOpen(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSwitching(false);
    }
  };

  if (!canSwitch) {
    return <p className="agent-model">{chatModel || "—"}</p>;
  }

  return (
    <div className="model-switch" ref={rootRef}>
      <button
        type="button"
        className="model-switch-trigger"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={switching}
        onClick={() => setOpen((v) => !v)}
        title={m.switchTitle}
      >
        <span className="agent-model">{chatModel || "—"}</span>
        <span className="model-switch-chevron" aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <div className="model-switch-popover" role="dialog" aria-label={m.switchTitle}>
          <div className="model-switch-toolbar">
            <input
              type="search"
              className="model-switch-search"
              placeholder={m.searchPlaceholder}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
            <label className="model-switch-free">
              <input
                type="checkbox"
                checked={freeOnly}
                onChange={(e) => setFreeOnly(e.target.checked)}
              />
              {m.freeOnly}
            </label>
          </div>
          {loading && <p className="small muted model-switch-status">{m.loading}</p>}
          {error && <p className="error small model-switch-status">{error}</p>}
          {!loading && !error && filtered.length === 0 && (
            <p className="small muted model-switch-status">{m.empty}</p>
          )}
          <ul className="model-switch-list" role="listbox">
            {filtered.map((item) => {
              const selected = item.id === chatModel;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`model-switch-item ${selected ? "is-selected" : ""}`}
                    disabled={switching}
                    onClick={() => void pickModel(item.id)}
                  >
                    <span className="model-switch-item-head">
                      <span className="model-switch-item-name">{item.name}</span>
                      {item.is_free && <span className="pill sm ok">{m.freeBadge}</span>}
                      {selected && <span className="pill sm">{m.currentBadge}</span>}
                    </span>
                    <span className="model-switch-item-id mono">{item.id}</span>
                    {item.description ? (
                      <span className="model-switch-item-desc">{item.description}</span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
