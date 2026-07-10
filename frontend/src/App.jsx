import { useState, useCallback, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { LangProvider } from './i18n';
import Sidebar from './components/Sidebar/Sidebar';
import ChannelView from './components/Channel/ChannelView';
import WelcomeView from './components/Channel/WelcomeView';
import CreateChannelView from './components/Channel/CreateChannelView';
import CreateTeammateView from './components/Teammate/CreateTeammateView';
import SettingsPanel from './components/Settings/SettingsPanel';
import TaskListView from './components/Task/TaskListView';

import LandingPage from './components/Landing/LandingPage';
import PitchDeck from './components/Landing/PitchDeck';
import './styles/landing.css';
import * as api from './services/api';

import { TaskProvider } from './services/taskContext';

export default function App() {
  // URL-based routing: #/landing, #/app, or #/pitch
  const [route, setRoute] = useState(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'pitch') return 'pitch';
    return hash.startsWith('/app') ? 'app' : 'landing';
  });

  const [activeChannelId, setActiveChannelId] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showCreateChannel, setShowCreateChannel] = useState(false);
  const [showCreateTeammate, setShowCreateTeammate] = useState(false);
  const [showTasks, setShowTasks] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lang, setLang] = useState(() => localStorage.getItem('aihub_lang') || 'zh');

  // Listen for hash changes
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '');
      if (h === 'pitch') setRoute('pitch');
      else setRoute(h.startsWith('/app') ? 'app' : 'landing');
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const changeLang = useCallback((newLang) => {
    setLang(newLang);
    localStorage.setItem('aihub_lang', newLang);
  }, []);

  const handleEnterApp = useCallback(async () => {
    // 首次进入 app 时，如果没有频道则自动创建默认频道和队友
    try {
      const [ch, tm] = await Promise.all([api.listChannels(), api.listTeammates()]);
      if (ch.length === 0) {
        // 先检查是否有 API Key
        const keys = await api.listAPIKeys();
        let keyId;
        if (keys.length === 0) {
          // Prompt user for API key — auto-provisioning requires a valid key
          alert('请先在设置中添加 API Key，然后才能创建队友。');
          // Continue to app — user can configure keys in Settings
        } else {
          keyId = keys[0].id;
        }
        // 创建默认队友（如果没有）— requires API key
        let engineerId, pmId;
        if (tm.length === 0 && keyId) {
          const [engineer, pm] = await Promise.all([
            api.createTeammate({
              name: 'Senior Engineer',
              role: 'engineer',
              avatar_emoji: '👨‍💻',
              system_prompt: 'You are a Senior Engineer. Write clean, efficient code. Review for bugs and suggest improvements. Be precise and technical.',
              model_provider: 'openrouter',
              model_name: 'openrouter/auto',
              api_key_ref: keyId,
            }),
            api.createTeammate({
              name: 'Product Manager',
              role: 'pm',
              avatar_emoji: '🧠',
              system_prompt: 'You are a Product Manager. Focus on user needs, prioritize features, and ensure the team delivers value. Think strategically about product decisions.',
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
        // 创建默认频道
        const newCh = await api.createChannel({ name: 'General', description: 'Default channel' });
        // 把队友加入频道
        if (engineerId) await api.addTeammateToChannel(newCh.id, engineerId);
        if (pmId) await api.addTeammateToChannel(newCh.id, pmId);
        setActiveChannelId(newCh.id);
      } else if (ch.length > 0 && !activeChannelId) {
        // 有频道但没有选中，默认选中第一个
        setActiveChannelId(ch[0].id);
      }
    } catch (e) {
      console.error('Init app failed:', e);
    }
    setRoute('app');
  }, [activeChannelId]);

  const handleGoToLanding = useCallback(() => {
    window.location.hash = '#/landing';
    setRoute('landing');
    setActiveChannelId(null);
    setShowSettings(false);
    setShowCreateTeammate(false);
    setShowCreateChannel(false);
  }, []);

  const triggerRefresh = useCallback(() => setRefreshKey(k => k + 1), []);
  const clearViews = useCallback(() => {
    setShowSettings(false);
    setShowCreateTeammate(false);
    setShowCreateChannel(false);
    setShowTasks(false);
  }, []);

  const goHome = useCallback(() => { clearViews(); setActiveChannelId(null); }, [clearViews]);

  const handleSelectChannel = useCallback((id) => {
    if (id === null) { goHome(); return; }
    clearViews();
    setActiveChannelId(id);
  }, [clearViews, goHome]);

  const handleOpenSettings = useCallback(() => {
    setShowSettings(s => !s);
    setShowCreateTeammate(false);
    setShowCreateChannel(false);
    setActiveChannelId(null);
  }, []);

  const handleCreateChannel = useCallback(() => { clearViews(); setShowCreateChannel(true); }, [clearViews]);
  const handleChannelDone = useCallback((channel) => {
    setShowCreateChannel(false);
    setActiveChannelId(channel.id);
    triggerRefresh();
  }, [triggerRefresh]);

  const handleCreateTeammate = useCallback(() => { clearViews(); setShowCreateTeammate(true); }, [clearViews]);
  const handleTeammateDone = useCallback(() => {
    setShowCreateTeammate(false);
    triggerRefresh();
  }, [triggerRefresh]);

  const handleOpenTasks = useCallback(() => {
    clearViews();
    setShowTasks(s => !s);
    setActiveChannelId(null);
  }, [clearViews]);

  const handleCloseTasks = useCallback(() => {
    setShowTasks(false);
  }, []);

  // ── Landing Page ──
  if (route === 'landing') {
    return (
      <LangProvider lang={lang}>
        <AnimatePresence mode="wait">
          <motion.div
            key="landing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
            style={{ background: 'var(--color-bg)', minHeight: '100vh' }}
          >
            <LandingPage onEnterApp={handleEnterApp} lang={lang} changeLang={changeLang} />
          </motion.div>
        </AnimatePresence>
      </LangProvider>
    );
  }

  // ── Pitch Deck ──
  if (route === 'pitch') {
    return (
      <LangProvider lang={lang}>
        <PitchDeck onBack={handleGoToLanding} />
      </LangProvider>
    );
  }

  // ── Product App ──
  let viewKey, ViewComponent, viewProps;
  if (showCreateTeammate) {
    viewKey = 'create-teammate';
    ViewComponent = CreateTeammateView;
    viewProps = { onDone: handleTeammateDone, onCancel: goHome };
  } else if (showCreateChannel) {
    viewKey = 'create-channel';
    ViewComponent = CreateChannelView;
    viewProps = { onDone: handleChannelDone, onCancel: goHome };
  } else if (showTasks) {
    viewKey = 'tasks';
    ViewComponent = TaskListView;
    viewProps = { onBack: handleCloseTasks };
  } else if (showSettings) {
    viewKey = 'settings';
    ViewComponent = SettingsPanel;
    viewProps = { onClose: goHome, triggerRefresh, lang, changeLang };
  } else if (activeChannelId) {
    viewKey = activeChannelId;
    ViewComponent = ChannelView;
    viewProps = { channelId: activeChannelId, triggerRefresh, refreshKey };
  } else {
    viewKey = 'welcome';
    ViewComponent = WelcomeView;
    viewProps = { onCreateChannel: handleCreateChannel };
  }

  return (
    <LangProvider lang={lang}>
      <TaskProvider>
      <div className="flex h-screen overflow-hidden product-body">
        <Sidebar
          activeChannelId={activeChannelId}
          onSelectChannel={handleSelectChannel}
          onOpenSettings={handleOpenSettings}
          onCreateChannel={handleCreateChannel}
          onCreateTeammate={handleCreateTeammate}
          onOpenTasks={handleOpenTasks}
          showTasks={showTasks}
          refreshKey={refreshKey}
          triggerRefresh={triggerRefresh}
          showSettings={showSettings}
        />
        <div className="flex-1 flex flex-col min-w-0 relative">
          <AnimatePresence mode="sync">
            <ViewComponent key={viewKey} {...viewProps} />
          </AnimatePresence>
        </div>
      </div>
      </TaskProvider>
    </LangProvider>
  );
}
