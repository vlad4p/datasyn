import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { SystemToolsPanel } from "./SystemToolsPanel";

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
};

export function SkillsToolsView({ className, id, locale }: Props) {
  const t = uiStrings(locale).skillsTools;

  return (
    <section id={id} className={`workspace-panel workspace-panel--scroll skills-tools-view ${className ?? ""}`}>
      <header className="skills-tools-view__header">
        <h2 className="section-title">{t.title}</h2>
        <p className="small muted">{t.hint}</p>
      </header>
      <SystemToolsPanel locale={locale} />
    </section>
  );
}
