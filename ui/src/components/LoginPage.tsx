import logoUrl from "../../images/image.png";
import { brainApiUrl } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = {
  locale: UiLocale;
  onLocaleChange: (locale: UiLocale) => void;
  providers: string[];
  error?: string | null;
};

function providerLabel(provider: string): string {
  if (provider === "google") return "Google";
  if (provider === "github") return "GitHub";
  return provider;
}

export function LoginPage({ locale, onLocaleChange, providers, error }: Props) {
  const s = uiStrings(locale);

  return (
    <div className="login-shell">
      <header className="app-header login-header">
        <div className="brand">
          <img className="logo" src={logoUrl} alt="" width={36} height={36} />
          <div>
            <h1>Datasyn</h1>
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

      <main className="login-main">
        <section className="login-card" aria-labelledby="login-title">
          <h2 id="login-title">{s.auth.signInTitle}</h2>
          <p className="login-subtitle">{s.auth.signInSubtitle}</p>

          {error ? <p className="login-error" role="alert">{error}</p> : null}

          <div className="login-actions">
            {providers.includes("google") ? (
              <a className="login-btn login-btn--google" href={brainApiUrl("/auth/login/google")}>
                <span className="login-btn__icon" aria-hidden>
                  G
                </span>
                {s.auth.continueWith.replace("{provider}", providerLabel("google"))}
              </a>
            ) : null}
            {providers.includes("github") ? (
              <a className="login-btn login-btn--github" href={brainApiUrl("/auth/login/github")}>
                <span className="login-btn__icon" aria-hidden>
                  GH
                </span>
                {s.auth.continueWith.replace("{provider}", providerLabel("github"))}
              </a>
            ) : null}
            {providers.length === 0 ? (
              <p className="login-error" role="alert">
                {s.auth.noProviders}
              </p>
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}
