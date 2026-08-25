import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { Lang, Loc } from '../content/types';

type LangValue = { lang: Lang; setLang: (l: Lang) => void };
const LangContext = createContext<LangValue>({ lang: 'en', setLang: () => {} });

export function LangProvider(props: {
  lang: Lang;
  setLang: (l: Lang) => void;
  children: ReactNode;
}) {
  const value = useMemo(
    () => ({ lang: props.lang, setLang: props.setLang }),
    [props.lang, props.setLang],
  );
  return <LangContext.Provider value={value}>{props.children}</LangContext.Provider>;
}

export function useLang(): LangValue {
  return useContext(LangContext);
}

/** Resolve a bilingual record against the active language. */
export function useT(): (loc: Loc) => string {
  const { lang } = useLang();
  return (loc: Loc) => loc[lang];
}
