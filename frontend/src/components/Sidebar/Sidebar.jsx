import { useState, useEffect } from 'react';
import { Plus, Hash, Settings, MessageSquare, Inbox, ListTodo, Users, Zap, X, BrainCircuit, LogOut } from 'lucide-react';
import { clearSession } from '../../services/auth';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import CreateChannelModal from '../Channel/CreateChannelModal';
import CreateTeammateModal from '../Teammate/CreateTeammateModal';
import ConfirmDialog from '../ConfirmDialog';

const NAV_ITEMS = [
  { view: 'inbox',     icon: Inbox,        label: '收件箱' },
  { view: 'tasks',     icon: ListTodo,     label: '任务' },
  { view: 'team',      icon: Users,        label: '团队' },
  { view: 'brain',     icon: BrainCircuit,  label: '队友记忆' },
  { view: 'ai-ops',    icon: Zap,          label: '自动化' },
];

export default function Sidebar({
  activeView, onNavigate, showSettings, onOpenSettings,
  channelId, onChannelSelect,
}) {
  const t = useTranslation();
  const [channels, setChannels] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showCreateTeammate, setShowCreateTeammate] = useState(false);
  const [confirm, setConfirm] = useState(null);

  // ponytail: shared state for both section menus (null | 'menu' | 'manage')
  const [sect, setSect] = useState(null); // { type: 'ch'|'tm', mode: 'menu'|'manage' }
  const [sel, setSel] = useState(new Set());

  useEffect(() => {
    Promise.all([api.listChannels(), api.listTeammates()])
      .then(([chs, tms]) => { setChannels(chs); setTeammates(tms); })
      .catch(() => {});
  }, []);

  const handleChannelClick = (id) => {
    if (sect?.type === 'ch' && sect.mode === 'manage') {
      setSel(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
      return;
    }
    onChannelSelect(id);
    onNavigate('chat');
  };

  const openMenu = (type) => setSect(s => s?.type === type && s.mode === 'menu' ? null : { type, mode: 'menu' });
  const openManage = (type) => setSect({ type, mode: 'manage' });
  const closeMenu = () => setSect(null);

  const bulkDelete = (type) => {
    const items = type === 'ch' ? channels : teammates;
    const label = type === 'ch' ? '频道' : '队友';
    const ids = [...sel];
    setConfirm({
      title: `批量删除 ${label}`,
      message: `确定删除选中的 ${ids.length} 个${label}？`,
      confirmText: '批量删除',
      onConfirm: async () => {
        const fn = type === 'ch' ? api.deleteChannel : api.deleteTeammate;
        await Promise.all(ids.map(id => fn(id)));
        if (type === 'ch') setChannels(cs => cs.filter(c => !ids.includes(c.id)));
        else setTeammates(ts => ts.filter(t => !ids.includes(t.id)));
        setSel(new Set());
        closeMenu();
      },
    });
  };

  const chManage = sect?.type === 'ch' && sect.mode === 'manage';
  const tmManage = sect?.type === 'tm' && sect.mode === 'manage';

  return (
    <div className="w-60 bg-[#f4f2ef] border-r border-[#e2ddd7] flex flex-col h-full flex-shrink-0 select-none">
      {/* Organization */}
      <div className="px-4 py-3.5 border-b border-[#e2ddd7]">
        <p className="text-sm font-semibold text-[#1d1d1d]">AI Team Hub</p>
        <p className="text-[11px] text-[#9ca3af] mt-0.5">Workspace</p>
      </div>

      {/* Main Nav */}
      <div className="py-2 px-2 space-y-0.5">
        {NAV_ITEMS.map(({ view, icon: Icon, label }) => (
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
            <span>{label}</span>
          </button>
        ))}
      </div>

      {/* Channels */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-2 mt-1 relative">
          <span className="text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">
            {t('sidebar.channels')}
          </span>
          <button
            onClick={() => chManage ? (closeMenu(), setSel(new Set())) : openMenu('ch')}
            className="p-1 rounded hover:bg-white/60 text-[#9ca3af] hover:text-[#1d1d1d] transition-all"
          >
            {chManage ? <X size={14} /> : <span className="text-xs font-bold leading-none tracking-wider">⋯</span>}
          </button>
          {sect?.type === 'ch' && sect.mode === 'menu' && (
            <div className="absolute right-2 top-full mt-1 bg-white rounded-lg shadow-lg border border-[#e2ddd7] z-50 py-1 min-w-[130px]">
              <button onClick={() => { setShowCreate(true); closeMenu(); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#1d1d1d] hover:bg-[#f4f2ef] transition-all text-left">{t('sidebar.create_channel')}</button>
              <button onClick={() => openManage('ch')} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#1d1d1d] hover:bg-[#f4f2ef] transition-all text-left">管理频道</button>
            </div>
          )}
        </div>

        <div className="overflow-y-auto space-y-0.5 px-2 pb-2">
          {channels.map(ch => (
            <div key={ch.id} className="group flex items-center">
              {chManage && (
                <label className="flex items-center justify-center w-6 h-6 cursor-pointer flex-shrink-0" onClick={e => e.stopPropagation()}>
                  <input type="checkbox" checked={sel.has(ch.id)} onChange={() => { setSel(p => { const n = new Set(p); n.has(ch.id) ? n.delete(ch.id) : n.add(ch.id); return n; }); }} className="w-3.5 h-3.5 accent-[#4a154b]" />
                </label>
              )}
              <button
                onClick={() => handleChannelClick(ch.id)}
                className={`flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-left transition-all ${
                  channelId === ch.id && !chManage
                    ? 'bg-white text-[#1d1d1d] font-medium shadow-sm'
                    : 'text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d]'
                }`}
              >
                <Hash size={14} className="flex-shrink-0 opacity-40" />
                <span className="truncate">{ch.name}</span>
              </button>
              {!chManage && (
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirm({ title: t('sidebar.delete_channel'), message: `确定删除频道「${ch.name}」？`, onConfirm: async () => { await api.deleteChannel(ch.id); setChannels(cs => cs.filter(c => c.id !== ch.id)); } }); }}
                  className="hidden group-hover:flex items-center justify-center w-5 h-5 rounded text-[#9ca3af] hover:text-red-500 hover:bg-black/10 transition-all text-xs flex-shrink-0 mr-1"
                >×</button>
              )}
            </div>
          ))}
          {channels.length === 0 && (
            <p className="text-[11px] text-[#9ca3af] text-center py-3">{t('sidebar.no_channels')}</p>
          )}
        </div>

        {chManage && sel.size > 0 && (
          <div className="px-3 pb-2">
            <button onClick={() => bulkDelete('ch')} className="w-full py-1.5 text-xs font-semibold rounded-lg bg-red-50 text-red-600 hover:bg-red-100 transition-all border border-red-200">删除选中频道 ({sel.size})</button>
          </div>
        )}

        {/* DM - AI Teammates */}
        <div className="border-t border-[#e2ddd7] mx-4" />
        <div className="flex items-center justify-between px-4 py-2 relative">
          <span className="text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">
            {t('sidebar.teammates')}
          </span>
          <button
            onClick={() => tmManage ? (closeMenu(), setSel(new Set())) : openMenu('tm')}
            className="p-1 rounded hover:bg-white/60 text-[#9ca3af] hover:text-[#1d1d1d] transition-all"
          >
            {tmManage ? <X size={14} /> : <span className="text-xs font-bold leading-none tracking-wider">⋯</span>}
          </button>
          {sect?.type === 'tm' && sect.mode === 'menu' && (
            <div className="absolute right-2 top-full mt-1 bg-white rounded-lg shadow-lg border border-[#e2ddd7] z-50 py-1 min-w-[130px]">
              <button onClick={() => { setShowCreateTeammate(true); closeMenu(); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#1d1d1d] hover:bg-[#f4f2ef] transition-all text-left">{t('sidebar.create_teammate')}</button>
              <button onClick={() => openManage('tm')} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#1d1d1d] hover:bg-[#f4f2ef] transition-all text-left">管理队友</button>
            </div>
          )}
        </div>
        <div className="overflow-y-auto space-y-0.5 px-2 pb-3">
          {teammates.map(tm => (
            <div key={tm.id} className="group flex items-center">
              {tmManage && (
                <label className="flex items-center justify-center w-6 h-6 cursor-pointer flex-shrink-0" onClick={e => e.stopPropagation()}>
                  <input type="checkbox" checked={sel.has(tm.id)} onChange={() => { setSel(p => { const n = new Set(p); n.has(tm.id) ? n.delete(tm.id) : n.add(tm.id); return n; }); }} className="w-3.5 h-3.5 accent-[#4a154b]" />
                </label>
              )}
              <button
                className={`flex-1 flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-sm text-left transition-all ${
                  tmManage && sel.has(tm.id) ? 'bg-[#4a154b]/5 text-[#1d1d1d]' : 'text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d]'
                }`}
                onClick={() => {
                  if (tmManage) { setSel(p => { const n = new Set(p); n.has(tm.id) ? n.delete(tm.id) : n.add(tm.id); return n; }); }
                }}
              >
                <span className="text-base flex-shrink-0 leading-none">{tm.avatar_emoji || '🤖'}</span>
                <div className="min-w-0 flex-1 text-left flex items-center gap-2">
                  <span className="truncate">{tm.name}</span>
                  <span className="text-[10px] bg-[#4a154b]/10 text-[#4a154b] px-1.5 py-0.5 rounded font-medium flex-shrink-0 leading-tight">AI</span>
                </div>
              </button>
              {!tmManage && (
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirm({ title: t('sidebar.delete_teammate', tm.name), message: `确定删除队友「${tm.name}」？`, onConfirm: async () => { await api.deleteTeammate(tm.id); setTeammates(ts => ts.filter(t => t.id !== tm.id)); } }); }}
                  className="hidden group-hover:flex items-center justify-center w-5 h-5 rounded text-[#9ca3af] hover:text-red-500 hover:bg-black/10 transition-all text-xs flex-shrink-0 mr-1"
                >×</button>
              )}
            </div>
          ))}
          {teammates.length === 0 && (
            <p className="text-[11px] text-[#9ca3af] text-center py-3">{t('sidebar.add_first')}</p>
          )}
        </div>

        {tmManage && sel.size > 0 && (
          <div className="px-3 pb-3">
            <button onClick={() => bulkDelete('tm')} className="w-full py-1.5 text-xs font-semibold rounded-lg bg-red-50 text-red-600 hover:bg-red-100 transition-all border border-red-200">删除选中队友 ({sel.size})</button>
          </div>
        )}
      </div>

      {/* Settings + Logout */}
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
        <button
          onClick={() => { clearSession(); onNavigateToLanding?.(); }}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-[#5c5c5c] hover:bg-white/60 hover:text-[#1d1d1d] transition-all"
        >
          <LogOut size={16} className="flex-shrink-0 opacity-70" />
          <span>退出登录</span>
        </button>
      </div>
      {showCreate && (
        <CreateChannelModal
          onClose={() => setShowCreate(false)}
          onCreate={(id) => { setShowCreate(false); onChannelSelect(id); onNavigate('chat'); }}
        />
      )}
      {showCreateTeammate && (
        <CreateTeammateModal
          onClose={() => setShowCreateTeammate(false)}
          onCreated={() => {
            setShowCreateTeammate(false);
            api.listTeammates().then(setTeammates).catch(() => {});
          }}
        />
      )}
      <ConfirmDialog state={[confirm, setConfirm]} />
    </div>
  );
}
