import { useState, useCallback, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { LangProvider } from './i18n';
import Sidebar from './components/Sidebar/Sidebar';
import ChannelView from './components/Channel/ChannelView';
import WelcomeView from './components/Channel/WelcomeView';
import CreateChannelView from './components/Channel/CreateChannelView';
import SettingsPanel from './components/Settings/SettingsPanel';
import CreateTeammateView from './components/Teammate/CreateTeammateView';
import LandingPage from './components/Landing/LandingPage';
import PitchDeck from './components/Landing/PitchDeck';
import './styles/landing.css';

export default function App() {
  // URL-based routing: #/landing, #/app, or #/pitch
  const [route, setRoute] = useState(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'pitch') return 'pitch';
    return hash.startsWith('app') ? 'app' : 'landing';
  });

  const [activeChannelId, setActiveChannelId] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showCreateTeammate, setShowCreateTeammate] = useState(false);
  const [showCreateChannel, setShowCreateChannel] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lang, setLang] = useState(() => localStorage.getItem('aihub_lang') || 'en');

  // Listen for hash changes
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '');
      if (h === 'pitch') setRoute('pitch');
      else setRoute(h.startsWith('app') ? 'app' : 'landing');
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
          // 自动创建默认 API Key
          const newKey = await api.createAPIKey({
            provider: 'openrouter',
            label: 'Default',
            api_key: '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',
          });
          keyId = newKey.id;
        } else {
          keyId = keys[0].id;
        }
        // 创建默认队友（如果没有）
        let tmId;
        if (tm.length === 0) {
          const newTm = await api.createTeammate({
            name: 'AI Assistant',
            role: 'assistant',
            avatar_emoji: '🤖',
            system_prompt: 'You are a helpful AI assistant. Be concise and helpful.',
            model_provider: 'openrouter',
            model_name: 'openrouter/auto',
            api_key_ref: keyId,
          });
          tmId = newTm.id;
        } else {
          tmId = tm[0].id;
        }
        // 创建默认频道
        const newCh = await api.createChannel({ name: 'General', description: 'Default channel' });
        // 把队友加入频道
        await api.addTeammateToChannel(newCh.id, tmId);
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

  const handleCreateTeammate = useCallback(() => { clearViews(); setShowCreateTeammate(true); }, [clearViews]);
  const handleTeammateDone = useCallback(() => { setShowCreateTeammate(false); triggerRefresh(); }, [triggerRefresh]);
  const handleCreateChannel = useCallback(() => { clearViews(); setShowCreateChannel(true); }, [clearViews]);
  const handleChannelDone = useCallback((channel) => {
    setShowCreateChannel(false);
    setActiveChannelId(channel.id);
    triggerRefresh();
  }, [triggerRefresh]);

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
            <LandingPage onEnterApp={handleEnterApp} />
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
      <div className="flex h-screen overflow-hidden product-body">
        <Sidebar
          activeChannelId={activeChannelId}
          onSelectChannel={handleSelectChannel}
          onOpenSettings={handleOpenSettings}
          onCreateTeammate={handleCreateTeammate}
          onCreateChannel={handleCreateChannel}
          showSettings={showSettings}
          refreshKey={refreshKey}
          triggerRefresh={triggerRefresh}
        />
        <div className="flex-1 flex flex-col min-w-0 relative">
          <AnimatePresence mode="sync">
            <ViewComponent key={viewKey} {...viewProps} />
          </AnimatePresence>
        </div>
      </div>
    </LangProvider>
  );
}
