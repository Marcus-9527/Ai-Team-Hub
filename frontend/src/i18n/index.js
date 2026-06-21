import React, { createContext, useContext } from 'react';

const LangContext = createContext('zh');

export function useLang() {
  return useContext(LangContext);
}

import zh from './zh';
import en from './en';
import ja from './ja';
import ko from './ko';
import es from './es';
import fr from './fr';
import de from './de';
import pt from './pt';
import ru from './ru';
import ar from './ar';
import hi from './hi';
import it from './it';
import nl from './nl';

const strings = { zh, en, ja, ko, es, fr, de, pt, ru, ar, hi, it, nl };

export const SUPPORTED_LANGUAGES = [
  { id: 'zh',    name: '中文',        flag: '🇨🇳' },
  { id: 'en',    name: 'English',     flag: '🇺🇸' },
  { id: 'ja',    name: '日本語',       flag: '🇯🇵' },
  { id: 'ko',    name: '한국어',       flag: '🇰🇷' },
  { id: 'es',    name: 'Español',     flag: '🇪🇸' },
  { id: 'fr',    name: 'Français',    flag: '🇫🇷' },
  { id: 'de',    name: 'Deutsch',     flag: '🇩🇪' },
  { id: 'pt',    name: 'Português',   flag: '🇧🇷' },
  { id: 'ru',    name: 'Русский',     flag: '🇷🇺' },
  { id: 'ar',    name: 'العربية',     flag: '🇸🇦' },
  { id: 'hi',    name: 'हिन्दी',       flag: '🇮🇳' },
  { id: 'it',    name: 'Italiano',    flag: '🇮🇹' },
  { id: 'nl',    name: 'Nederlands',  flag: '🇳🇱' },
];

export function useTranslation() {
  const lang = useLang();
  return (key, ...args) => {
    let str = strings[lang]?.[key] ?? strings.en?.[key] ?? key;
    if (args.length > 0) {
      args.forEach((a, i) => { str = str.replaceAll(`{${i}}`, a); });
    }
    return str;
  };
}

export function LangProvider({ lang, children }) {
  return React.createElement(LangContext.Provider, { value: lang }, children);
}
