import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, ChevronDown, ChevronRight, RotateCcw, Loader2, AlertCircle, Bot, Clock, Activity } from 'lucide-react';
import * as api from '../../services/api';

const TYPE_LABELS = {
  'brain:identity': '身份 Identity',
  'brain:personality': '性格 Personality',
  'brain:principles': '原则 Principles',
  'brain:responsibilities': '职责 Responsibilities',
  'brain:skills': '技能 Skills',
  'brain:lessons': '经验 Lesson',
  'brain:decisions': '决策 Decisions',
  'brain:preferences': '偏好 Preferences',
  'brain:behavior_suggestion': '行为建议',
  'brain:proposal': '待批准修改',
};

const TYPE_ICONS = {
  'brain:identity': '🧬',
  'brain:personality': '🧠',
  'brain:principles': '⚖️',
  'brain:responsibilities': '📋',
  'brain:skills': '🛠️',
  'brain:lessons': '📖',
  'brain:decisions': '📝',
  'brain:preferences': '⭐',
  'brain:behavior_suggestion': '💡',
  'brain:proposal': '🔔',
};

export default function BrainPage({ onBack, lang }) {
  const [teammates, setTeammates] = useState([]);
  const [selectedTm, setSelectedTm] = useState(null);
  const [fragments, setFragments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedType, setExpandedType] = useState(null);
  const [versions, setVersions] = useState({});
  const [rollbacking, setRollbacking] = useState(null);
  const [promptPreview, setPromptPreview] = useState('');
  const [showPrompt, setShowPrompt] = useState(false);

  useEffect(() => {
    api.listTeammates().then(tms => {
      setTeammates(tms);
      if (tms.length > 0) selectTeammate(tms[0]);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  const selectTeammate = async (tm) => {
    setSelectedTm(tm);
    setExpandedType(null);
    setShowPrompt(false);
    try {
      const data = await api.listBrainFragments(tm.id);
      setFragments(data.fragments || []);
    } catch (e) { console.error(e); }
  };

  const toggleType = async (type) => {
    if (expandedType === type) { setExpandedType(null); return; }
    setExpandedType(type);
    if (!versions[type] && selectedTm) {
      try {
        const data = await api.listBrainFragmentVersions(selectedTm.id, type);
        setVersions(v => ({ ...v, [type]: data.versions || [] }));
      } catch (e) { console.error(e); }
    }
  };

  const handleRollback = async (type, targetVersion) => {
    setRollbacking(`${type}:${targetVersion}`);
    try {
      await api.rollbackBrainFragment(selectedTm.id, type, targetVersion);
      await selectTeammate(selectedTm);
    } catch (e) { console.error(e); }
    setRollbacking(null);
  };

  const handleShowPrompt = async () => {
    if (!selectedTm) return;
    setShowPrompt(!showPrompt);
    if (!showPrompt) {
      try {
        const data = await api.getBrainLoaderPrompt(selectedTm.id);
        setPromptPreview(data.prompt || '');
      } catch (e) { console.error(e); }
    }
  };

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-5xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Brain size={24} style={{ color: 'var(--color-primary)' }} />
          <h1 className="text-xl font-bold" style={{ color: 'var(--color-ink)' }}>Teammate Brain</h1>
        </div>
        <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          AI 队友的长期知识库 — 包含身份、经验、技能、决策等持久化片段
        </p>

        {/* Teammate selector */}
        <div className="flex flex-wrap gap-2">
          {teammates.map(tm => (
            <button
              key={tm.id}
              onClick={() => selectTeammate(tm)}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-all ${
                selectedTm?.id === tm.id
                  ? 'bg-primary text-white shadow-md'
                  : 'hover:bg-black/5'
              }`}
              style={selectedTm?.id !== tm.id ? { color: 'var(--color-ink)', border: '1px solid rgba(0,0,0,0.08)' } : {}}
            >
              <span>{tm.avatar_emoji || '🤖'}</span>
              {tm.name}
            </button>
          ))}
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin" size={32} style={{ color: 'var(--color-primary)' }} />
          </div>
        )}

        {/* Brain content */}
        {!loading && selectedTm && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Fragments panel */}
            <div className="lg:col-span-2 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>
                  🧬 {selectedTm.name} 的 Brain Fragments
                </h2>
                <button
                  onClick={handleShowPrompt}
                  className="text-xs px-3 py-1.5 rounded-lg transition-all"
                  style={{
                    background: 'rgba(0,0,0,0.05)',
                    color: showPrompt ? 'var(--color-primary)' : 'var(--color-ink-faint)',
                    border: '1px solid rgba(0,0,0,0.08)',
                  }}
                >
                  {showPrompt ? '收起 Prompt' : '预览 Prompt'}
                </button>
              </div>

              {fragments.length === 0 && (
                <div className="flex flex-col items-center py-12 gap-3" style={{ color: 'var(--color-ink-faint)' }}>
                  <Bot size={40} opacity={0.3} />
                  <p className="text-sm">暂无 Brain 片段。完成任务后 Reflection 系统会自动生成经验片段。</p>
                </div>
              )}

              {fragments.map(frag => {
                const type = frag.type;
                const label = TYPE_LABELS[type] || type;
                const icon = TYPE_ICONS[type] || '📦';
                const isExpanded = expandedType === type;
                const verList = versions[type] || [];
                return (
                  <motion.div
                    key={frag.id}
                    layout
                    className="rounded-xl overflow-hidden"
                    style={{ border: '1px solid rgba(0,0,0,0.06)', background: 'rgba(0,0,0,0.02)' }}
                  >
                    {/* Header */}
                    <button
                      onClick={() => toggleType(type)}
                      className="w-full flex items-center justify-between p-3.5 hover:bg-black/5 transition-all text-left"
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="text-lg">{icon}</span>
                        <div>
                          <span className="text-sm font-medium" style={{ color: 'var(--color-ink)' }}>{label}</span>
                          <span className="text-xs ml-2" style={{ color: 'var(--color-ink-faint)' }}>
                            v{frag.version} · {frag.source}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{
                          background: frag.confidence > 0.7 ? 'rgba(34,197,94,0.15)' : 'rgba(0,0,0,0.06)',
                          color: frag.confidence > 0.7 ? '#22c55e' : 'var(--color-ink-faint)',
                        }}>
                          {Math.round(frag.confidence * 100)}%
                        </span>
                        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </div>
                    </button>

                    {/* Content */}
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="px-3.5 pb-3.5 space-y-2"
                      >
                        <div className="text-xs leading-relaxed whitespace-pre-wrap rounded-lg p-3"
                          style={{ background: 'rgba(0,0,0,0.3)', color: 'var(--color-ink-faint)' }}>
                          {frag.content}
                        </div>

                        {/* Version history */}
                        {verList.length > 0 && (
                          <div className="space-y-1">
                            <p className="text-xs font-medium" style={{ color: 'var(--color-ink-faint)' }}>
                              版本历史 ({verList.length})
                            </p>
                            {verList.slice(0, 5).map(v => (
                              <div key={v.id} className="flex items-center justify-between text-xs px-3 py-1.5 rounded-lg"
                                style={{ background: 'rgba(0,0,0,0.03)' }}>
                                <span style={{ color: 'var(--color-ink-faint)' }}>
                                  v{v.version} · {v.source} · {v.created_at ? new Date(v.created_at).toLocaleDateString() : '-'}
                                </span>
                                {v.version < frag.version && (
                                  <button
                                    onClick={() => handleRollback(type, v.version)}
                                    disabled={rollbacking === `${type}:${v.version}`}
                                    className="flex items-center gap-1 px-2 py-0.5 rounded-md transition-all hover:bg-black/10"
                                    style={{ color: 'var(--color-primary)' }}
                                  >
                                    {rollbacking === `${type}:${v.version}`
                                      ? <Loader2 size={12} className="animate-spin" />
                                      : <RotateCcw size={12} />
                                    }
                                    回滚
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </motion.div>
                    )}
                  </motion.div>
                );
              })}
            </div>

            {/* Sidebar: Overview */}
            <div className="space-y-3">
              <div className="rounded-xl p-4" style={{ border: '1px solid rgba(0,0,0,0.06)', background: 'rgba(0,0,0,0.02)' }}>
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-ink)' }}>
                  <Activity size={14} style={{ color: 'var(--color-primary)' }} />
                  Brain 概览
                </h3>
                <div className="space-y-2 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                  <div className="flex justify-between py-1 border-b" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                    <span>片段总数</span>
                    <span className="font-medium" style={{ color: 'var(--color-ink)' }}>{fragments.length}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                    <span>类型数</span>
                    <span className="font-medium" style={{ color: 'var(--color-ink)' }}>
                      {new Set(fragments.map(f => f.type)).size}
                    </span>
                  </div>
                  <div className="flex justify-between py-1">
                    <span>可编辑片段</span>
                    <span className="font-medium" style={{ color: 'var(--color-ink)' }}>
                      {fragments.filter(f => f.editable).length}
                    </span>
                  </div>
                </div>
              </div>

              <div className="rounded-xl p-4" style={{ border: '1px solid rgba(0,0,0,0.06)', background: 'rgba(0,0,0,0.02)' }}>
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-ink)' }}>
                  <Clock size={14} style={{ color: 'var(--color-primary)' }} />
                  来源分布
                </h3>
                <div className="space-y-2 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                  {['manual', 'reflection', 'consolidation', 'rollback_from_v'].map(src => {
                    const count = fragments.filter(f => f.source === src || f.source.startsWith(src)).length;
                    if (count === 0) return null;
                    return (
                      <div key={src} className="flex justify-between py-1">
                        <span className="capitalize">{src.replace(/_/g, ' ')}</span>
                        <span className="font-medium" style={{ color: 'var(--color-ink)' }}>{count}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Prompt preview modal */}
        <AnimatePresence>
          {showPrompt && promptPreview && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              className="rounded-xl p-4 mt-3 max-h-96 overflow-y-auto"
              style={{ border: '1px solid rgba(252,28,70,0.2)', background: 'rgba(0,0,0,0.4)' }}
            >
              <pre className="text-xs leading-relaxed whitespace-pre-wrap font-mono" style={{ color: 'var(--color-ink-faint)' }}>
                {promptPreview}
              </pre>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
