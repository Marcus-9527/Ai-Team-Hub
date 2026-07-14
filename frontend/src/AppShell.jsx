import { useState, useCallback, lazy, Suspense } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Sidebar from './components/Sidebar/Sidebar';
import ChatLayout from './components/ChatLayout';
import SettingsPanel from './components/Settings/SettingsPanel';
import ErrorBoundary from './components/ErrorBoundary';
import { listChannels } from './services/api';

// 非首屏视图懒加载,拆分到各自的 chunk
const NewTopicPage = lazy(() => import('./components/NewTopic/NewTopicPage'));
const TaskModeView = lazy(() => import('./components/TaskModeView'));
const HomePage = lazy(() => import('./components/Home/HomePage'));
const ProjectsPage = lazy(() => import('./components/Projects/ProjectsPage'));
const TeamPage = lazy(() => import('./components/Team/TeamPage'));
const DashboardPage = lazy(() => import('./components/Dashboard/DashboardPage'));
const InboxPage = lazy(() => import('./components/Inbox/InboxPage'));
const DeveloperCenter = lazy(() => import('./components/Developer/DeveloperCenter'));
const BrainPage = lazy(() => import('./components/Brain/BrainPage'));
const ProposalApprovalPage = lazy(() => import('./components/Brain/ProposalApprovalPage'));
const ApprovalQueuePage = lazy(() => import('./components/Approval/ApprovalQueuePage'));
const AutonomousCenter = lazy(() => import('./components/Autonomous/AutonomousCenter'));
const ExecutionRoom = lazy(() => import('./components/Execution/ExecutionRoom'));
const WorkspaceExplorer = lazy(() => import('./components/Workspace/WorkspaceExplorer'));
const SystemHealthView = lazy(() => import('./components/SystemHealth/SystemHealth'));

function ViewFallback() {
  return <div className="flex-1 flex items-center justify-center text-gray-400">加载中…</div>;
}

export default function AppShell({ onNavigateToLanding }) {
  const [view, setView] = useState('home');
  const [userMode, setUserMode] = useState(
    () => localStorage.getItem('aihub_user_mode') || 'user'
  );
  const setUserModePersist = useCallback((m) => {
    setUserMode(m);
    localStorage.setItem('aihub_user_mode', m);
  }, []);
  const [channelId, setChannelId] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lang, setLang] = useState(() => localStorage.getItem('aihub_lang') || 'zh');

  const changeLang = useCallback((newLang) => {
    setLang(newLang);
    localStorage.setItem('aihub_lang', newLang);
  }, []);

  const triggerRefresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const handleNavigate = useCallback(
    (newView) => {
      setShowSettings(false);
      if (newView === 'chat') {
        if (!channelId) {
          listChannels()
            .then((chs) => {
              if (chs.length > 0) setChannelId(chs[0].id);
            })
            .catch(() => {});
        }
      }
      if (newView === 'new-topic') {
        setChannelId(null);
      }
      setView(newView);
    },
    [channelId]
  );

  const handleOpenSettings = useCallback(() => setShowSettings((s) => !s), []);

  const handleChannelSelect = useCallback((id) => {
    setChannelId(id);
    setView('chat');
  }, []);

  let ViewComponent, viewKey, viewProps;
  if (showSettings) {
    viewKey = 'settings';
    ViewComponent = SettingsPanel;
    viewProps = {
      onClose: () => setShowSettings(false),
      triggerRefresh,
      lang,
      changeLang,
      userMode,
      setUserMode: setUserModePersist,
    };
  } else if (view === 'chat') {
    viewKey = 'chat-' + (channelId || 'empty') + '-' + refreshKey;
    ViewComponent = ChatLayout;
    viewProps = {
      channelId,
      setChannelId,
      triggerRefresh,
      refreshKey,
      onNavigate: handleNavigate,
      onOpenSettings: handleOpenSettings,
    };
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
  } else if (view === 'system-health') {
    viewKey = 'system-health-' + refreshKey;
    ViewComponent = SystemHealthView;
    viewProps = {};
  } else {
    viewKey = 'home-' + refreshKey;
    ViewComponent = HomePage;
    viewProps = {
      onNavigate: handleNavigate,
      triggerRefresh,
      refreshKey,
      lang,
      userMode,
    };
  }

  return (
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
          <Suspense fallback={<ViewFallback />}>
            <ViewComponent key={viewKey} {...viewProps} />
          </Suspense>
        </AnimatePresence>
      </div>
    </div>
  );
}
