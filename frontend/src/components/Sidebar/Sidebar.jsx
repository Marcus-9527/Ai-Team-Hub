import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Hash, Plus, Settings, Users, ChevronDown, Bot,
  Trash2, UserPlus, Home,
} from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';

export default function Sidebar({
  activeChannelId, onSelectChannel, onOpenSettings,
  onCreateTeammate, onCreateChannel, showSettings, refreshKey, triggerRefresh,
}) {
  const t = useTranslation();
  const [channels, setChannels] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [channelsExpanded, setChannelsExpanded] = useState(true);
  const [teammatesExpanded, setTeammatesExpanded] = useState(true);

  useEffect(() => { loadData(); }, [refreshKey]);

  const loadData = async () => {
    try {
      const [ch, tm] = await Promise.all([api.listChannels(), api.listTeammates()]);
      setChannels(ch);
      setTeammates(tm);
    } catch (e) { console.error(e); }
  };

  const handleDeleteChannel = async (id, e) => {
    e.stopPropagation();
    if (!confirm('Delete this channel?')) return;
    await api.deleteChannel(id);
    triggerRefresh();
  };

  return (
    <div className="w-64 bg-primary-deep text-white flex flex-col h-full flex-shrink-0 select-none">
      {/* Clickable Logo/Header */}
      <button
        onClick={() => onSelectChannel(null)}
        className="w-full px-4 py-5 border-b border-white/10 hover:bg-white/[0.03] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-white/15 flex items-center justify-center group-hover:bg-white/20 transition-colors">
            <Bot size={20} className="text-white" />
          </div>
          <div>
            <h1 className="font-bold text-[15px] leading-tight">{t('app.title')}</h1>
            <p className="text-[11px] text-white/50 font-medium">{t('app.subtitle')}</p>
          </div>
        </div>
      </button>

      {/* Scrollable nav area */}
      <div className="flex-1 overflow-y-auto py-2">
        {/* Channels */}
        <div className="px-3 py-1.5 flex items-center gap-1">
          <button onClick={() => setChannelsExpanded(!channelsExpanded)} className="flex items-center gap-1.5 flex-1 text-left">
            <ChevronDown size={12} className={`text-white/30 transition-transform ${channelsExpanded ? '' : '-rotate-90'}`} />
            <span className="text-xs font-semibold tracking-wide uppercase text-white/40">{t('sidebar.channels')}</span>
          </button>
          <button onClick={onCreateChannel} className="p-1 rounded hover:bg-white/10 transition-colors"><Plus size={14} className="text-white/50" /></button>
        </div>
        <AnimatePresence mode="wait">
          {channelsExpanded && (
            <motion.div
              key="ch"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {channels.length === 0 && <p className="px-5 text-xs text-white/30 py-2">{t('sidebar.no_channels')}</p>}
              {channels.map(ch => (
                <div
                  key={ch.id}
                  onClick={() => onSelectChannel(ch.id)}
                  className={`group flex items-center gap-2 px-5 py-1.5 mx-2 rounded-md cursor-pointer text-sm transition-all ${
                    activeChannelId === ch.id ? 'bg-white/12 text-white font-medium' : 'text-white/60 hover:bg-white/8 hover:text-white/85'}`}
                >
                  <Hash size={14} className="text-white/40 flex-shrink-0" />
                  <span className="truncate">{ch.name}</span>
                  <button onClick={(e) => handleDeleteChannel(ch.id, e)} className="ml-auto opacity-0 group-hover:opacity-60 hover:opacity-100 p-0.5 rounded transition-all"><Trash2 size={12} /></button>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* AI Teammates */}
        <div className="mt-3 px-3 py-1.5 flex items-center gap-1">
          <button onClick={() => setTeammatesExpanded(!teammatesExpanded)} className="flex items-center gap-1.5 flex-1 text-left">
            <ChevronDown size={12} className={`text-white/30 transition-transform ${teammatesExpanded ? '' : '-rotate-90'}`} />
            <span className="text-xs font-semibold tracking-wide uppercase text-white/40">{t('sidebar.ai_teammates')}</span>
          </button>
          <button onClick={onCreateTeammate} className="p-1 rounded hover:bg-white/10 transition-colors"><Plus size={14} className="text-white/50" /></button>
        </div>
        <AnimatePresence mode="wait">
          {teammatesExpanded && (
            <motion.div
              key="tm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {teammates.length === 0 && (
                <button onClick={onCreateTeammate} className="w-full flex items-center gap-2 px-5 py-2 text-xs text-white/40 hover:text-white/70 hover:bg-white/5 rounded-md transition-all">
                  <UserPlus size={14} /><span>{t('sidebar.create_first')}</span>
                </button>
              )}
              {teammates.map(tm => (
                <div key={tm.id} className="group flex items-center gap-2 px-5 py-1.5 mx-2 rounded-md text-sm text-white/60 hover:bg-white/8 hover:text-white/85 cursor-default transition-all">
                  <span className="text-sm">{tm.avatar_emoji}</span>
                  <span className="truncate text-xs">{tm.name}</span>
                  <button
                    onClick={async () => {
                      if (confirm(`Delete "${tm.name}"?`)) {
                        // 1. 从所有包含该队友的频道中移除
                        const channelsWithTm = channels.filter(ch => (ch.teammate_ids || []).includes(tm.id));
                        for (const ch of channelsWithTm) {
                          await api.removeTeammateFromChannel(ch.id, tm.id);
                        }
                        // 2. 删除队友本身
                        await api.deleteTeammate(tm.id);
                        // 3. 等后端写入完成后再发系统消息 + 刷新
                        await new Promise(r => setTimeout(r, 300));
                        for (const ch of channelsWithTm) {
                          try {
                            await api.sendSystemMessage(ch.id, `${tm.avatar_emoji || '🤖'} ${tm.name} ${t('channel.left')}`);
                          } catch {}
                        }
                        triggerRefresh();
                      }
                    }}
                    className="ml-auto p-0.5 rounded opacity-0 group-hover:opacity-60 hover:opacity-100 hover:text-white transition-all"
                  ><Trash2 size={12} /></button>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="border-t border-white/10 p-3 bg-primary-deep">
        <button
          onClick={onOpenSettings}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-all ${
            showSettings ? 'bg-white/12 text-white font-medium' : 'text-white/60 hover:bg-white/8 hover:text-white'}`}
        >
          <Settings size={15} /><span>{t('sidebar.settings')}</span>
        </button>
      </div>
    </div>
  );
}
