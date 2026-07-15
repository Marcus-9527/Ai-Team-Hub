import React, { createContext, useContext, useEffect, useState } from 'react';

const LangContext = createContext('zh');

export function useLang() {
  return useContext(LangContext);
}

// 语言包按需加载,首屏只拉当前语言
const loaders = {
  zh: () => import('./zh'),
  en: () => import('./en'),
};

export const SUPPORTED_LANGUAGES = [
  { id: 'zh', name: '中文' },
  { id: 'en', name: 'English' },
];

function useStrings(lang) {
  const [strings, setStrings] = useState({});
  useEffect(() => {
    let alive = true;
    const load = loaders[lang] || loaders.en;
    load().then((m) => { if (alive) setStrings(m.default || m); }).catch(() => {});
    return () => { alive = false; };
  }, [lang]);
  return strings;
}

export function useTranslation() {
  const lang = useLang();
  const strings = useStrings(lang);
  return (key, ...args) => {
    let str = strings[key] ?? key;
    if (args.length > 0) {
      args.forEach((a, i) => { str = str.replaceAll(`{${i}}`, a); });
    }
    return str;
  };
}

export function LangProvider({ lang, children }) {
  return React.createElement(LangContext.Provider, { value: lang }, children);
}
