import { useCallback } from 'react';
import { AnimatePresence } from 'motion/react';
import { ui } from './content/load';
import type { Lang } from './content/types';
import { LangProvider, useT } from './i18n/lang';
import { RouterProvider, useNavigate, useRoute } from './router/Router';
import { MapView } from './views/MapView';
import { ComponentsView } from './views/ComponentsView';
import { DetailView } from './views/DetailView';
import { MachineView } from './views/MachineView';
import { DebtView } from './views/DebtView';
import { PhasesView } from './views/PhasesView';

const VIEWS = ['map', 'phases', 'components', 'machine', 'debt'] as const;
type ViewName = (typeof VIEWS)[number];

function CurrentView({ view, id }: { view: string; id?: string }) {
  if (view === 'phases') return <PhasesView />;
  if (view === 'components') return <ComponentsView />;
  if (view === 'component' && id) return <DetailView id={id} />;
  if (view === 'machine') return <MachineView />;
  if (view === 'debt') return <DebtView />;
  return <MapView />;
}

function Shell() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const view = route.segments[0] ?? 'map';
  const lang: Lang = route.query.lang === 'vi' ? 'vi' : 'en';

  const switchLang = (next: Lang) => {
    navigate({ segments: route.segments, query: { ...route.query, lang: next } }, { replace: true });
  };

  return (
    <>
      <a className="skip" href="#main">
        {t(ui.site.skipToContent)}
      </a>
      <header className="masthead">
        <div className="masthead__title">
          <h1>{t(ui.site.title)}</h1>
          <p>{t(ui.site.tagline)}</p>
        </div>
        <div className="masthead__controls">
          <nav aria-label={t(ui.nav.label)}>
            <ul className="nav">
              {VIEWS.map((name: ViewName) => (
                <li key={name}>
                  <button
                    type="button"
                    className="nav__button"
                    aria-current={view === name ? 'page' : undefined}
                    onClick={() => navigate({ segments: [name], query: route.query })}
                  >
                    {t(ui.nav[name])}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="langswitch" role="group" aria-label={t(ui.nav.languageLabel)}>
            <button
              type="button"
              className="langswitch__button"
              aria-pressed={lang === 'en'}
              onClick={() => switchLang('en')}
            >
              {t(ui.nav.english)}
            </button>
            <button
              type="button"
              className="langswitch__button"
              aria-pressed={lang === 'vi'}
              onClick={() => switchLang('vi')}
            >
              {t(ui.nav.vietnamese)}
            </button>
          </div>
        </div>
      </header>

      <main id="main" data-view={view}>
        <AnimatePresence mode="wait">
          <CurrentView key={view} view={view} id={route.segments[1]} />
        </AnimatePresence>
      </main>
    </>
  );
}

/** Language lives in the hash query so a shared link keeps its language. */
function LangBridge() {
  const route = useRoute();
  const navigate = useNavigate();
  const lang: Lang = route.query.lang === 'vi' ? 'vi' : 'en';
  const setLang = useCallback(
    (next: Lang) =>
      navigate(
        { segments: route.segments, query: { ...route.query, lang: next } },
        { replace: true },
      ),
    [navigate, route.segments, route.query],
  );
  return (
    <LangProvider lang={lang} setLang={setLang}>
      <Shell />
    </LangProvider>
  );
}

export function App() {
  return (
    <RouterProvider>
      <LangBridge />
    </RouterProvider>
  );
}
