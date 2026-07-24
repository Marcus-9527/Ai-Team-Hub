import { useState, useCallback, useEffect, lazy, Suspense } from 'react';
import {
  HashRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
} from 'react-router-dom';
import { LangProvider } from './i18n';
import ErrorBoundary from './components/ErrorBoundary';
import ToastHost from './components/ToastHost';
import { isLoggedIn, setSession } from './services/auth';

import LandingPage from './components/Landing/LandingPage';
import PitchDeck from './components/Landing/PitchDeck';
import AuthPage from './components/Auth/AuthPage';
import './styles/landing.css';

// /app 主壳整体懒加载:framer-motion 等依赖全部移出首屏
const AppShell = lazy(() => import('./AppShell'));

// ponytail: first-run data seeding moved to backend startup.py
// (ensure_default_data in startup.py runs during lifespan)

function AuthGate({ onNavigateToLanding }) {
  const navigate = useNavigate();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!isLoggedIn()) {
      navigate('/auth', { replace: true });
      return;
    }
    setChecked(true);
  }, [navigate]);

  if (!isLoggedIn()) return null;
  if (!checked) return <div className="flex h-screen items-center justify-center text-gray-400">加载中…</div>;

  return (
    <ErrorBoundary>
      <Suspense fallback={<div className="flex h-screen items-center justify-center text-gray-400">加载中…</div>}>
        <AppShell onNavigateToLanding={onNavigateToLanding} />
      </Suspense>
    </ErrorBoundary>
  );
}

function Root() {
  const navigate = useNavigate();
  const [lang, setLang] = useState(() => localStorage.getItem('aihub_lang') || 'zh');

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === 'aihub_lang') setLang(e.newValue || 'zh');
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  useEffect(() => {
    localStorage.setItem('aihub_lang', lang);
  }, [lang]);

  const handleAuth = useCallback(() => {
    navigate('/app');
  }, [navigate]);

  return (
    <ErrorBoundary>
      <LangProvider lang={lang}>
        <ToastHost />
        <Routes>
          <Route
            path="/"
            element={<LandingPage onEnterApp={() => navigate('/auth')} />}
          />
          <Route path="/pitch" element={<PitchDeck onBack={() => navigate('/')} />} />
          <Route path="/auth" element={<AuthPage onAuth={handleAuth} />} />
          <Route path="/app" element={<AuthGate onNavigateToLanding={() => navigate('/')} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </LangProvider>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <HashRouter>
      <Root />
    </HashRouter>
  );
}
