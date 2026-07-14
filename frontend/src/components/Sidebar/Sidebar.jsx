import { useState, useEffect } from 'react';
import { Plus, Hash, Settings, MessageSquare, Inbox, ListTodo, Users, Brain, FileCheck, Zap, Activity } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import CreateChannelModal from '../Channel/CreateChannelModal';

const NAV_ITEMS = [
  { view: 'new-topic',  icon: MessageSquare, key: 'sidebar.new_topic' },
  { view: 'home',  icon: Inbox,         key: 'nav.inbox' },
  { view: 'tasks', icon: ListTodo,      key: 'nav.tasks' },
  { view: 'team',  icon: Users,         key: 'sidebar.ai_teammates' },
  { view: 'brain', icon: Brain,         key: 'nav.brain' },
  { view: 'proposals', icon: FileCheck, key: 'nav.proposals' },
  { view: 'autonomous', icon: Zap,      key: 'nav.autonomous' },
  { view: 'system-health', icon: Activity, key: 'nav.system_health' },
];

export default function Sidebar({
  activeView, onNavigate, showSettings, onOpenSettings,
  channelId, onChannelSelect, showDashboard,
}) {
  const t = useTranslation();
  const [channels, setChannels] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([api.listChannels(), api.listTeammates()])
      .then(([chs, tms]) => { setChannels(chs); setTeammates(tms); })
      .catch(() => {});
  }, []);

  const handleChannelClick = (id) => {
    onChannelSelect(id);
    onNavigate('chat');
  };

  return (
    <div className="w-60 bg-[#f4f2ef] border-r border-[#e2ddd7] flex flex-col h-full flex-shrink-0 select-none">
      {/* Organization */}
      <div className="px-4 py-3.5 border-b border-[#e2ddd7]">
        <p className="text-sm font-semibold text-[#1d1d1d]">AI Team Hub</p>
        <p className="text-[11px] text-[#9ca3af] mt-0.5">Workspace</p>
      </div>

      {/* Main Nav */}
      <div className="py-2 px-2 space-y-0.5">
        {NAV_ITEMS.map(({ view, icon: Icon, key }) => (
          <button
            key={view}
            onClick={() => onNavigate(view)}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all ${
              activeView === view && !showSettings
                ? 'bg-white text-[#1d1d1d] font-medium shadow-sm'
                : 'text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d]'
            }`}
          >
            <Icon size={16} className="flex-shrink-0 opacity-70" />
            <span>{t(key)}</span>
          </button>
        ))}
      </div>

      {/* Channels */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-2 mt-1">
          <span className="text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">
            {t('sidebar.channels')}
          </span>
          <button
            onClick={() => setShowCreate(true)}
            className="p-1 rounded hover:bg-white/60 text-[#9ca3af] hover:text-[#1d1d1d] transition-all"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="overflow-y-auto space-y-0.5 px-2 pb-2">
          {channels.map(ch => (
            <button
              key={ch.id}
              onClick={() => handleChannelClick(ch.id)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-all ${
                channelId === ch.id
                  ? 'bg-white text-[#1d1d1d] font-medium shadow-sm'
                  : 'text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d]'
              }`}
            >
              <Hash size={14} className="flex-shrink-0 opacity-40" />
              <span className="truncate">{ch.name}</span>
            </button>
          ))}
          {channels.length === 0 && (
            <p className="text-[11px] text-[#9ca3af] text-center py-3">{t('sidebar.no_channels')}</p>
          )}
        </div>

        {/* DM - AI Teammates */}
        <div className="border-t border-[#e2ddd7] mx-4" />
        <div className="px-4 py-2">
          <span className="text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">
            {t('sidebar.teammates')}
          </span>
        </div>
        <div className="overflow-y-auto space-y-0.5 px-2 pb-3">
          {teammates.map(tm => (
            <button
              key={tm.id}
              className="w-full flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-sm text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d] transition-all"
            >
              <span className="text-base flex-shrink-0 leading-none">{tm.avatar_emoji || '🤖'}</span>
              <div className="min-w-0 flex-1 text-left flex items-center gap-2">
                <span className="truncate">{tm.name}</span>
                <span className="text-[10px] bg-[#4a154b]/10 text-[#4a154b] px-1.5 py-0.5 rounded font-medium flex-shrink-0 leading-tight">
                  AI
                </span>
              </div>
            </button>
          ))}
          {teammates.length === 0 && (
            <p className="text-[11px] text-[#9ca3af] text-center py-3">{t('sidebar.add_first')}</p>
          )}
        </div>
      </div>

      {/* Settings */}
      <div className="border-t border-[#e2ddd7] px-2 py-2">
        <button
          onClick={onOpenSettings}
          className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all ${
            showSettings ? 'bg-white text-[#1d1d1d] font-medium shadow-sm' : 'text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d]'
          }`}
        >
          <Settings size={16} className="flex-shrink-0 opacity-70" />
          <span>{t('sidebar.settings')}</span>
        </button>
      </div>
      {showCreate && (
        <CreateChannelModal
          onClose={() => setShowCreate(false)}
          onCreate={(id) => { setShowCreate(false); onChannelSelect(id); onNavigate('chat'); }}
        />
      )}
    </div>
  );
}
