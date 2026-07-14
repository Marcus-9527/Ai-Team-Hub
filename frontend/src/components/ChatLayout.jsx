import { useState, useEffect, useCallback } from 'react';
import { Bot, ChevronLeft, ChevronRight, Cpu, Circle, CheckCircle2, ListTodo, PlayCircle, Plus } from 'lucide-react';
import * as api from '../services/api';
import { useTranslation } from '../i18n';
import ChannelView from './Channel/ChannelView';
import CreateTeammateModal from './Teammate/CreateTeammateModal';
import CreateChannelModal from './Channel/CreateChannelModal';
import ConfirmDialog from './ConfirmDialog';

/* ── Right: AI Assistant Panel ── */
function AssistantPanel({ channelId, refreshKey, collapsed, onToggle, onRefresh }) {
  const t = useTranslation();
  const [teammates, setTeammates] = useState([]);
  const [channel, setChannel] = useState(null);
  const [states, setStates] = useState({});
  const [showAdd, setShowAdd] = useState(false);
  const [menuTmId, setMenuTmId] = useState(null);
  const [confirm, setConfirm] = useState(null);

  useEffect(() => {
    if (!channelId) return;
    Promise.all([
      api.listChannels().then(chs => chs.find(c => c.id === channelId)),
      api.listTeammates(),
    ]).then(([ch, all]) => {
      setChannel(ch);
      setTeammates(all);
    }).catch(() => {});
  }, [channelId, refreshKey]);

  // Poll teammate states
  useEffect(() => {
    if (!channelId) return;
    const poll = () => {
      api.listTeammateStates().then(list => {
        const m = {};
        for (const s of list) m[s.teammate_id || s.id] = s.state || s.current_state || 'idle';
        setStates(m);
      }).catch(() => {});
    };
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, [channelId, refreshKey]);

  const STATE_DOT = {
    thinking: 'bg-indigo-400',
    working:  'bg-amber-400',
    idle:     'bg-gray-300',
    active:   'bg-emerald-400',
  };
  const STATE_LABEL = {
    thinking: t('team.state_thinking'),
    working:  t('team.state_working'),
    idle:     t('team.state_idle'),
  };

  const channelTeammates = (channel?.teammate_ids || [])
    .map(id => teammates.find(tm => tm.id === id))
    .filter(Boolean);

  if (!channelId) return null;

  if (collapsed) {
    return (
      <div className="w-11 bg-white border-l border-[#e2ddd7] flex flex-col items-center py-3 flex-shrink-0">
        <button onClick={onToggle} className="p-1.5 rounded-lg hover:bg-gray-100 text-[#9ca3af] hover:text-[#1d1d1d] transition-all">
          <ChevronLeft size={16} />
        </button>
        <Bot size={16} className="text-[#9ca3af] opacity-40 mt-3" />
        <span className="mt-2 text-[10px] text-[#9ca3af] [writing-mode:vertical-rl]">{t('chat.assistants')}</span>
      </div>
    );
  }

  return (
    <div className="w-60 bg-white border-l border-[#e2ddd7] flex flex-col h-full flex-shrink-0 relative">
      <button
        onClick={onToggle}
        className="absolute -left-3 top-3 z-20 p-1 rounded-full bg-white border border-[#e2ddd7] text-[#9ca3af] hover:text-[#1d1d1d] shadow-sm transition-all"
      >
        <ChevronRight size={14} />
      </button>
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[#e2ddd7]">
        <Bot size={14} className="text-[#9ca3af]" />
        <span className="text-xs font-semibold text-[#5c5c5c] uppercase tracking-wider flex-1">{t('chat.assistants')}</span>
        <div className="relative">
          <button onClick={() => setShowAdd(v => !v)} className="p-1 rounded hover:bg-gray-100 text-[#9ca3af] hover:text-[#1d1d1d] transition-all">
            <Plus size={14} />
          </button>
          {showAdd && (
            <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-[#e2ddd7] z-50 py-1 min-w-[160px]">
              {teammates.filter(tm => !channel?.teammate_ids?.includes(tm.id)).map(tm => (
                <button key={tm.id} onClick={async () => { await api.addTeammateToChannel(channelId, tm.id); setShowAdd(false); setChannel(c => ({ ...c, teammate_ids: [...(c?.teammate_ids || []), tm.id] })); onRefresh?.(); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#1d1d1d] hover:bg-[#f4f2ef] transition-all text-left">
                  <span>{tm.avatar_emoji || '🤖'}</span>
                  <span className="truncate">{tm.name}</span>
                </button>
              ))}
              {teammates.filter(tm => !channel?.teammate_ids?.includes(tm.id)).length === 0 && (
                <p className="text-xs text-[#9ca3af] text-center py-2">暂无可用队友</p>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-2 px-3 space-y-2">
        {channelTeammates.map(tm => {
          const st = states[tm.id] || 'idle';
          const dotColor = STATE_DOT[st] || STATE_DOT.idle;
          const stLabel = STATE_LABEL[st] || st;
          return (
            <div key={tm.id} className="group relative flex items-start gap-3 p-2.5 rounded-xl border border-[#e2ddd7] bg-white">
              <div className="relative flex-shrink-0">
                <span className="text-lg">{tm.avatar_emoji || '🤖'}</span>
                <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${dotColor}`} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <p className="text-sm font-semibold text-[#1d1d1d] truncate">{tm.name}</p>
                  <span className="text-[9px] text-[#9ca3af] whitespace-nowrap">{stLabel}</span>
                </div>
                <p className="text-[10px] text-[#9ca3af] truncate mt-0.5">{tm.role || ''}</p>
                <div className="flex items-center gap-1 mt-1 text-[9px] text-[#9ca3af]/60">
                  <Cpu size={9} />
                  <span className="truncate">{tm.model_name || tm.model_provider || '-'}</span>
                </div>
              </div>
              <div className="relative flex-shrink-0">
                <button onClick={() => setMenuTmId(menuTmId === tm.id ? null : tm.id)} className="p-0.5 rounded hover:bg-gray-100 text-[#9ca3af] hover:text-[#1d1d1d] transition-all opacity-0 group-hover:opacity-100">
                  <span className="text-xs font-bold leading-none tracking-wider">⋯</span>
                </button>
                {menuTmId === tm.id && (
                  <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-[#e2ddd7] z-50 py-1 min-w-[130px]">
                    <button onClick={() => { setMenuTmId(null); setConfirm({ title: '移出频道', message: `确定将「${tm.name}」移出当前频道？`, confirmText: '移出', onConfirm: async () => { await api.removeTeammateFromChannel(channelId, tm.id); setChannel(c => ({ ...c, teammate_ids: (c?.teammate_ids || []).filter(id => id !== tm.id) })); onRefresh?.(); } }); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-all text-left">移出频道</button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {channelTeammates.length === 0 && (
          <p className="text-[11px] text-[#9ca3af] text-center py-4">{t('teammate.none_in_channel')}</p>
        )}
      </div>
      <ConfirmDialog state={[confirm, setConfirm]} />
    </div>
  );
}

/* ── ChatLayout: 2-column (Channel + Assistant Panel) ── */

export default function ChatLayout({ channelId, setChannelId, triggerRefresh, refreshKey, onNavigate, onOpenSettings }) {
  const [showCreate, setShowCreate] = useState(false);
  const [showTeammate, setShowTeammate] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  return (
    <div className="flex-1 flex h-full overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0">
        {channelId ? (
          <ChannelView channelId={channelId} triggerRefresh={triggerRefresh} refreshKey={refreshKey} onOpenSettings={onOpenSettings} />
        ) : (
          <div className="flex-1 flex items-center justify-center bg-white">
            <div className="text-center max-w-sm px-6">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-[#f0edf0] flex items-center justify-center">
                <Bot size={28} className="text-[#9ca3af]" />
              </div>
              <h3 className="text-lg font-bold text-[#1d1d1d] mb-1.5">{t('empty.chat_title')}</h3>
              <p className="text-xs text-[#9ca3af] mb-6 leading-relaxed">{t('empty.chat_desc')}</p>
              <div className="flex flex-col gap-2">
                {[
                  { label: t('empty.new_feature'), icon: PlayCircle, action: 'new-topic' },
                  { label: t('empty.fix_bug'), icon: CheckCircle2, action: 'new-topic' },
                  { label: t('empty.analyze'), icon: ListTodo, action: 'new-topic' },
                ].map(({ label, icon: Icon, action }) => (
                  <button
                    key={label}
                    onClick={() => onNavigate?.(action)}
                    className="flex items-center gap-3 px-4 py-2.5 bg-white rounded-xl border border-[#e2ddd7] hover:border-[#fc1c46]/30 hover:shadow-sm transition-all text-left w-full"
                  >
                    <div className="w-8 h-8 rounded-lg bg-[#fc1c46]/10 flex items-center justify-center text-[#fc1c46] flex-shrink-0">
                      <Icon size={15} />
                    </div>
                    <span className="text-sm font-semibold text-[#1d1d1d]">{label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
      <AssistantPanel
        channelId={channelId}
        refreshKey={refreshKey}
        collapsed={rightCollapsed}
        onToggle={() => setRightCollapsed(v => !v)}
        onRefresh={triggerRefresh}
      />
      {showCreate && (
        <CreateChannelModal
          onClose={() => setShowCreate(false)}
          onCreate={(id) => { setShowCreate(false); setChannelId(id); }}
        />
      )}
      {showTeammate && (
        <CreateTeammateModal
          onClose={() => setShowTeammate(false)}
          onCreated={() => { setShowTeammate(false); triggerRefresh(); }}
        />
      )}
    </div>
  );
}
