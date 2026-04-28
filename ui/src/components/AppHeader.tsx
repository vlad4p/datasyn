import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = {
  locale: UiLocale;
  onLocaleChange: (locale: UiLocale) => void;
};

export function AppHeader({ locale, onLocaleChange }: Props) {
  const s = uiStrings(locale);
  return (
    <header className="app-header">
      <div className="brand">
        <span className="logo" aria-hidden />
        <div>
          <h1>Datacyber</h1>
          <p className="tagline">{s.tagline}</p>
        </div>
      </div>
      <div
        className="locale-switch"
        role="group"
        aria-label={locale === "es" ? "Idioma de respuestas" : "Response language"}
      >
        <button
          type="button"
          className={`locale-btn${locale === "en" ? " active" : ""}`}
          onClick={() => onLocaleChange("en")}
          aria-pressed={locale === "en"}
        >
          EN
        </button>
        <button
          type="button"
          className={`locale-btn${locale === "es" ? " active" : ""}`}
          onClick={() => onLocaleChange("es")}
          aria-pressed={locale === "es"}
        >
          ES
        </button>
      </div>
    </header>
  );
}
