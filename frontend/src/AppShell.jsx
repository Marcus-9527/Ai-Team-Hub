import { useState, useCallback, lazy, Suspense } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Sidebar from './components/Sidebar/Sidebar';
import ChatLayout from './components/ChatLayout';
import SettingsPanel from './components/Settings/SettingsPanel';
import ErrorBoundary from './components/ErrorBoundary';
import { listChannels } from './services/api';
import { dismissAll } from './services/toast';

// 非首屏视图懒加载,拆分到各自的 chunk
const NewTopicPage = lazy(() => import('./components/NewTopic/NewTopicPage'));
const TaskModeView = lazy(() => import('./components/TaskModeView'));
const ProjectsPage = lazy(() => import('./components/Projects/ProjectsPage'));
const TeamPage = lazy(() => import('./components/Team/TeamPage'));
const DashboardPage = lazy(() => import('./components/Dashboard/DashboardPage'));
const BrainPage = lazy(() => import('./components/Brain/BrainPage'));
const ProposalApprovalPage = lazy(() => import('./components/Brain/ProposalApprovalPage'));
const ApprovalQueuePage = lazy(() => import('./components/Approval/ApprovalQueuePage'));
const AutonomousCenter = lazy(() => import('./components/Autonomous/AIOpsCenter'));
const ExecutionRoom = lazy(() => import('./components/Execution/ExecutionRoom'));
const WorkspaceExplorer = lazy(() => import('./components/Workspace/WorkspaceExplorer'));
const SystemHealthView = lazy(() => import('./components/SystemHealth/SystemHealth'));
const OrganizationRunView = lazy(() => import('./pages/OrganizationRunView'));
const OrganizationDashboard = lazy(() => import('./components/Dashboard/OrganizationDashboard'));


function ViewFallback() {
  return <div className="flex-1 flex items-center justify-center text-gray-400">加载中…</div>;
}

export default function AppShell({ onNavigateToLanding }) {
  const [view, setView] = useState('tasks');
  const [channelId, setChannelId] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [orgRunId, setOrgRunId] = useState('');

  const triggerRefresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const handleNavigate = useCallback(
    (newView) => {
      setShowSettings(false);
      dismissAll();
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
      onNavigate: handleNavigate,
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
    viewProps = { onNavigate: handleNavigate };
  } else if (view === 'projects') {
    viewKey = 'projects-' + refreshKey;
    ViewComponent = ProjectsPage;
    viewProps = {};
  } else if (view === 'brain') {
    viewKey = 'brain-' + refreshKey;
    ViewComponent = BrainPage;
    viewProps = { channelId, onBack: () => setView('tasks') };
  } else if (view === 'team') {
    viewKey = 'team-' + refreshKey;
    ViewComponent = TeamPage;
    viewProps = {};
  } else if (view === 'dashboard') {
    viewKey = 'dashboard-' + refreshKey;
    ViewComponent = DashboardPage;
    viewProps = { onBack: () => setView('tasks') };
  } else if (view === 'proposals') {
    viewKey = 'proposals-' + refreshKey;
    ViewComponent = ProposalApprovalPage;
    viewProps = {};
  } else if (view === 'approvals') {
    viewKey = 'approvals-' + refreshKey;
    ViewComponent = ApprovalQueuePage;
    viewProps = { onBack: () => setView('tasks') };
  } else if (view === 'ai-ops') {
    viewKey = 'ai-ops-' + refreshKey;
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
  } else if (view === 'org-run') {
    viewKey = 'org-run-' + refreshKey;
    ViewComponent = OrganizationRunView;
    viewProps = { initialRunId: orgRunId };
  } else if (view === 'org-dashboard') {
    viewKey = 'org-dashboard-' + refreshKey;
    ViewComponent = OrganizationDashboard;
    viewProps = { onNavigate: handleNavigate };
  } else {
    viewKey = 'tasks-' + refreshKey;
    ViewComponent = TaskModeView;
    viewProps = { onNavigate: handleNavigate };
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
        onNavigateToLanding={onNavigateToLanding}
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
