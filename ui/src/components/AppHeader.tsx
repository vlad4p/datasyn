import logoUrl from "../../images/image.png";
import type { AuthUser } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = {
  locale: UiLocale;
  onLocaleChange: (locale: UiLocale) => void;
  user?: AuthUser | null;
  onLogout?: () => void;
};

export function AppHeader({ locale, onLocaleChange, user, onLogout }: Props) {
  const s = uiStrings(locale);
  return (
    <header className="app-header">
      <div className="brand">
        <img className="logo" src={logoUrl} alt="" width={36} height={36} />
        <div>
          <h1>Datasyn</h1>
          <p className="tagline">{s.tagline}</p>
        </div>
      </div>
      <div className="app-header__actions">
        {user ? (
          <div className="user-menu">
            {user.picture ? (
              <img className="user-menu__avatar" src={user.picture} alt="" width={28} height={28} />
            ) : (
              <span className="user-menu__avatar user-menu__avatar--fallback" aria-hidden>
                {(user.name || user.email || "?").slice(0, 1).toUpperCase()}
              </span>
            )}
            <span className="user-menu__name">{user.name || user.email || user.id}</span>
            {onLogout ? (
              <button type="button" className="user-menu__logout" onClick={onLogout}>
                {s.auth.signOut}
              </button>
            ) : null}
          </div>
        ) : null}
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
      </div>
    </header>
  );
}
