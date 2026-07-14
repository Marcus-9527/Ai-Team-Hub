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
import {
  listChannels,
  listAPIKeys,
  listTeammates,
  createTeammate,
  createChannel,
  addTeammateToChannel,
} from './services/api';

import LandingPage from './components/Landing/LandingPage';
import PitchDeck from './components/Landing/PitchDeck';
import './styles/landing.css';

// /app 主壳整体懒加载:framer-motion 等依赖全部移出首屏
const AppShell = lazy(() => import('./AppShell'));

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

  const handleEnterApp = useCallback(async () => {
    try {
      const ch = await listChannels();
      if (ch.length === 0) {
        const keys = await listAPIKeys();
        let keyId = keys.length > 0 ? keys[0].id : null;
        const tm = await listTeammates();
        let engineerId, pmId;
        if (tm.length === 0 && keyId) {
          const [engineer, pm] = await Promise.all([
            createTeammate({
              name: '高级工程师',
              role: 'engineer',
              avatar_emoji: '👨‍💻',
              system_prompt: 'You are a Senior Engineer. Write clean, efficient code.',
              model_provider: 'openrouter',
              model_name: 'openrouter/auto',
              api_key_ref: keyId,
            }),
            createTeammate({
              name: '产品经理',
              role: 'pm',
              avatar_emoji: '🧠',
              system_prompt:
                'You are a Product Manager. Focus on user needs and strategic decisions.',
              model_provider: 'openrouter',
              model_name: 'openrouter/auto',
              api_key_ref: keyId,
            }),
          ]);
          engineerId = engineer.id;
          pmId = pm.id;
        } else if (tm.length > 0) {
          engineerId = tm[0].id;
          pmId = tm.length > 1 ? tm[1].id : null;
        }
        const newCh = await createChannel({
          name: 'General',
          description: 'Main chat channel',
        });
        if (engineerId) await addTeammateToChannel(newCh.id, engineerId);
        if (pmId) await addTeammateToChannel(newCh.id, pmId);
      }
    } catch (e) {
      console.error('Init failed:', e);
    }
    navigate('/app');
  }, [navigate]);

  return (
    <ErrorBoundary>
      <LangProvider lang={lang}>
        <ToastHost />
        <Routes>
          <Route
            path="/"
            element={
              <LandingPage onEnterApp={handleEnterApp} lang={lang} changeLang={setLang} />
            }
          />
          <Route
            path="/pitch"
            element={<PitchDeck onBack={() => navigate('/')} />}
          />
          <Route
            path="/app"
            element={
              <ErrorBoundary>
                <Suspense fallback={<div className="flex h-screen items-center justify-center text-gray-400">加载中…</div>}>
                  <AppShell onNavigateToLanding={() => navigate('/')} />
                </Suspense>
              </ErrorBoundary>
            }
          />
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
