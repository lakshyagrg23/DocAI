import { Fragment, createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { setLangValue, type Lang } from '@/lib/i18n'

/** Interface language, persisted per browser. Changing it remounts the tree so every `t()` call re-evaluates. */
interface I18nContext {
  lang: Lang
  setLang: (l: Lang) => void
}

const Ctx = createContext<I18nContext | null>(null)
const KEY = 'docai.lang'

function initial(): Lang {
  let l: Lang = 'en'
  try {
    const v = localStorage.getItem(KEY)
    l = v === 'hi' || v === 'en' ? v : navigator.language?.toLowerCase().startsWith('hi') ? 'hi' : 'en'
  } catch { /* private mode */ }
  setLangValue(l) // before the first render, so the first paint is already in the right language
  return l
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial)
  const setLang = useCallback((l: Lang) => {
    setLangValue(l)
    try { localStorage.setItem(KEY, l) } catch { /* private mode */ }
    document.documentElement.lang = l
    setLangState(l)
  }, [])
  const value = useMemo(() => ({ lang, setLang }), [lang, setLang])
  return <Ctx.Provider value={value}><Fragment key={lang}>{children}</Fragment></Ctx.Provider>
}

export function useLang(): I18nContext {
  const c = useContext(Ctx)
  if (!c) return { lang: 'en', setLang: () => undefined } // components rendered in tests without the provider stay English
  return c
}
