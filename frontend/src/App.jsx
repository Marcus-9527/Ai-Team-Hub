import { useState, useCallback, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { LangProvider } from './i18n';
import Sidebar from './components/Sidebar/Sidebar';
import ChatLayout from './components/ChatLayout';
import NewTopicPage from './components/NewTopic/NewTopicPage';
import TaskModeView from './components/TaskModeView';
import SettingsPanel from './components/Settings/SettingsPanel';
import HomePage from './components/Home/HomePage';
import ProjectsPage from './components/Projects/ProjectsPage';
import TeamPage from './components/Team/TeamPage';
import DashboardPage from './components/Dashboard/DashboardPage';
import InboxPage from './components/Inbox/InboxPage';
import DeveloperCenter from './components/Developer/DeveloperCenter';
import BrainPage from './components/Brain/BrainPage';
import ProposalApprovalPage from './components/Brain/ProposalApprovalPage';
import ApprovalQueuePage from './components/Approval/ApprovalQueuePage';
import AutonomousCenter from './components/Autonomous/AutonomousCenter';
import ExecutionRoom from './components/Execution/ExecutionRoom';
import WorkspaceExplorer from './components/Workspace/WorkspaceExplorer';

import LandingPage from './components/Landing/LandingPage';
import PitchDeck from './components/Landing/PitchDeck';
import './styles/landing.css';
import * as api from './services/api';

export default function App() {
  const [route, setRoute] = useState(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'pitch') return 'pitch';
    return hash.startsWith('/app') ? 'app' : 'landing';
  });

  const [view, setView] = useState('home');
  const [userMode, setUserMode] = useState(() => localStorage.getItem('aihub_user_mode') || 'user');
  const setUserModePersist = useCallback((m) => {
    setUserMode(m);
    localStorage.setItem('aihub_user_mode', m);
  }, []);
  const [channelId, setChannelId] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lang, setLang] = useState(() => localStorage.getItem('aihub_lang') || 'zh');

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

  const triggerRefresh = useCallback(() => setRefreshKey(k => k + 1), []);

  const handleEnterApp = useCallback(async (targetView) => {
    window.location.hash = '#/app';
    try {
      const ch = await api.listChannels();
      if (ch.length === 0) {
        const keys = await api.listAPIKeys();
        let keyId = keys.length > 0 ? keys[0].id : null;
        const tm = await api.listTeammates();
        let engineerId, pmId;
        if (tm.length === 0 && keyId) {
          const [engineer, pm] = await Promise.all([
            api.createTeammate({
              name: '高级工程师', role: 'engineer', avatar_emoji: '👨‍💻',
              system_prompt: 'You are a Senior Engineer. Write clean, efficient code.',
              model_provider: 'openrouter', model_name: 'openrouter/auto', api_key_ref: keyId,
            }),
            api.createTeammate({
              name: '产品经理', role: 'pm', avatar_emoji: '🧠',
              system_prompt: 'You are a Product Manager. Focus on user needs and strategic decisions.',
              model_provider: 'openrouter', model_name: 'openrouter/auto', api_key_ref: keyId,
            }),
          ]);
          engineerId = engineer.id;
          pmId = pm.id;
        } else if (tm.length > 0) {
          engineerId = tm[0].id;
          pmId = tm.length > 1 ? tm[1].id : null;
        }
        const newCh = await api.createChannel({ name: 'General', description: 'Main chat channel' });
        if (engineerId) await api.addTeammateToChannel(newCh.id, engineerId);
        if (pmId) await api.addTeammateToChannel(newCh.id, pmId);
        setChannelId(newCh.id);
      } else {
        setChannelId(ch[0].id);
      }
    } catch (e) {
      console.error('Init failed:', e);
    }
    setRoute('app');
    window.location.hash = '#/app';
  }, []);

  const handleGoToLanding = useCallback(() => {
    window.location.hash = '#/landing';
    setRoute('landing');
    setShowSettings(false);
    setChannelId(null);
  }, []);

  const handleNavigate = useCallback((newView) => {
    if (route !== 'app') { handleEnterApp(); return; }
    setShowSettings(false);
    if (newView === 'chat') {
      if (!channelId) {
        api.listChannels().then(chs => {
          if (chs.length > 0) setChannelId(chs[0].id);
        }).catch(() => {});
      }
    }
    if (newView === 'new-topic') {
      setChannelId(null);
    }
    setView(newView);
  }, [route, handleEnterApp, channelId]);

  const handleOpenSettings = useCallback(() => {
    setShowSettings(s => !s);
  }, []);

  const handleChannelSelect = useCallback((id) => {
    setChannelId(id);
    setView('chat');
  }, []);

  // ── Landing ──
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

  if (route === 'pitch') {
    return (
      <LangProvider lang={lang}>
        <PitchDeck onBack={handleGoToLanding} />
      </LangProvider>
    );
  }

  // ── App: multi-view ──
  let ViewComponent, viewKey, viewProps;
  if (showSettings) {
    viewKey = 'settings';
    ViewComponent = SettingsPanel;
    viewProps = { onClose: () => setShowSettings(false), triggerRefresh, lang, changeLang, userMode, setUserMode: setUserModePersist };
  } else if (view === 'chat') {
    viewKey = 'chat-' + (channelId || 'empty') + '-' + refreshKey;
    ViewComponent = ChatLayout;
    viewProps = { channelId, setChannelId, triggerRefresh, refreshKey, onNavigate: handleNavigate, onOpenSettings: handleOpenSettings };
  } else if (view === 'new-topic') {
    viewKey = 'new-topic-' + refreshKey;
    ViewComponent = NewTopicPage;
    viewProps = { setChannelId, triggerRefresh, refreshKey };
  } else if (view === 'tasks') {
    viewKey = 'tasks-' + refreshKey;
    ViewComponent = TaskModeView;
    viewProps = { userMode };
  } else if (view === 'projects') {
    viewKey = 'projects-' + refreshKey;
    ViewComponent = ProjectsPage;
    viewProps = { lang };
  } else if (view === 'inbox') {
    viewKey = 'inbox-' + refreshKey;
    ViewComponent = InboxPage;
    viewProps = { onNavigate: handleNavigate, setChannelId };
  } else if (view === 'team') {
    viewKey = 'team-' + refreshKey;
    ViewComponent = TeamPage;
    viewProps = { lang };
  } else if (view === 'dashboard') {
    viewKey = 'dashboard-' + refreshKey;
    ViewComponent = userMode === 'developer' ? DeveloperCenter : DashboardPage;
    viewProps = { onBack: () => setView('home') };
  } else if (view === 'brain') {
    viewKey = 'brain-' + refreshKey;
    ViewComponent = BrainPage;
    viewProps = { lang };
  } else if (view === 'proposals') {
    viewKey = 'proposals-' + refreshKey;
    ViewComponent = ProposalApprovalPage;
    viewProps = { lang };
  } else if (view === 'approvals') {
    viewKey = 'approvals-' + refreshKey;
    ViewComponent = ApprovalQueuePage;
    viewProps = { onBack: () => setView('home') };
  } else if (view === 'autonomous') {
    viewKey = 'autonomous-' + refreshKey;
    ViewComponent = AutonomousCenter;
    viewProps = {};
  } else if (view === 'execution') {
    viewKey = 'execution-' + refreshKey;
    ViewComponent = ExecutionRoom;
    viewProps = {};
  } else if (view === 'workspace') {
    viewKey = 'workspace-' + refreshKey;
    ViewComponent = WorkspaceExplorer;
    viewProps = {};
  } else {
    viewKey = 'home-' + refreshKey;
    ViewComponent = HomePage;
    viewProps = { onNavigate: handleNavigate, triggerRefresh, refreshKey, lang, userMode };
  }

  return (
    <LangProvider lang={lang}>
      <div className="flex h-screen overflow-hidden bg-[#faf8f5]">
        <Sidebar
          activeView={showSettings ? null : view}
          onNavigate={handleNavigate}
          onOpenSettings={handleOpenSettings}
          showSettings={showSettings}
          channelId={channelId}
          onChannelSelect={handleChannelSelect}
          showDashboard={userMode === 'developer'}
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
