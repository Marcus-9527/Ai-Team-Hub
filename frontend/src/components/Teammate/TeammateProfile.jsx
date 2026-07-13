import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Bot, Brain, Database, Activity, BarChart3, Cpu,
  CheckCircle2, Star, Zap, Layers,
} from 'lucide-react';
import * as api from '../../services/api';

/**
 * Teammate Profile — Helio-style AI teammate workspace.
 * Consumes the existing /api/teammates/{id}/profile endpoint (read-only).
 */
export default function TeammateProfile({ teammateId, compact = false }) {
  const [tm, setTm] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!teammateId) return;
    setLoading(true);
    Promise.all([
      api.listTeammates().then(list => list.find(t => t.id === teammateId) || null),
      api.getTeammateProfile(teammateId).catch(() => null),
    ]).then(([base, prof]) => {
      setTm(base);
      setProfile(prof);
    }).catch(() => {
      setTm(null); setProfile(null);
    }).finally(() => setLoading(false));
  }, [teammateId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Activity size={20} className="animate-pulse text-ink-faint" />
      </div>
    );
  }
  if (!tm && !profile) {
    return <div className="p-5 text-center text-sm text-ink-faint">无法加载队友数据</div>;
  }

  const name = tm?.name || profile?.name || 'Teammate';
  const role = tm?.role || profile?.role || '—';
  const avatar = tm?.avatar_emoji || '🤖';
  const modelLabel = `${profile?.model_provider || tm?.model_provider || ''}/${profile?.model_name || tm?.model_name || ''}`;
  const capabilities = tm?.capabilities?.length ? tm.capabilities
    : (tm?.skills?.length ? tm.skills : (profile?.capabilities || []));

  const tasks = profile?.task_executions || { total: 0, success: 0, failed: 0 };
  const successRate = tasks.total > 0
    ? Math.round((tasks.success / tasks.total) * 100)
    : Math.round((profile?.success_rate || 0) * 100);
  const reviewScore = profile?.average_score || 0;
  const brainFrags = profile?.brain_fragments_count ?? 0;
  const learned = profile?.memory_count ?? 0;

  const stats = [
    { Icon: CheckCircle2, label: 'Tasks completed', value: String(tasks.success), tint: 'text-emerald-600 bg-emerald-50' },
    { Icon: Star, label: 'Review score', value: reviewScore ? reviewScore.toFixed(1) : '—', tint: 'text-amber-600 bg-amber-50' },
    { Icon: Zap, label: 'Success rate', value: `${successRate}%`, tint: 'text-indigo-600 bg-indigo-50' },
  ];
  const memory = [
    { Icon: Brain, label: 'Learned patterns', value: String(learned), tint: 'text-primary/10 text-primary' },
    { Icon: Layers, label: 'Brain fragments', value: String(brainFrags), tint: 'bg-purple-50 text-purple-600' },
  ];

  return (
    <div className={compact ? 'p-0' : 'p-5 max-w-2xl mx-auto'}>
      {/* Header */}
      <div className={`flex items-center gap-4 ${compact ? 'p-5 border-b border-hairline' : 'mb-6'}`}>
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="w-14 h-14 rounded-2xl bg-canvas-lavender flex items-center justify-center text-2xl flex-shrink-0"
        >
          {avatar}
        </motion.div>
        <div className="min-w-0">
          <h3 className="font-bold text-base text-ink truncate">{name}</h3>
          <p className="text-xs text-ink-faint mt-0.5">{role}</p>
          {modelLabel && modelLabel !== '/' && (
            <p className="text-[10px] text-ink-faint mt-0.5 flex items-center gap-1">
              <Cpu size={10} /> {modelLabel}
            </p>
          )}
        </div>
      </div>

      <div className="px-5 pb-5 space-y-5">
        {/* Capabilities */}
        {capabilities.length > 0 && (
          <Section icon={Bot} title="能力">
            <div className="flex flex-wrap gap-2">
              {capabilities.map(c => (
                <span key={c} className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-canvas-lavender text-ink-mute">
                  {c}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Stats */}
        <Section icon={BarChart3} title="统计">
          <div className="grid grid-cols-3 gap-3">
            {stats.map(s => (
              <div key={s.label} className="bg-gray-50 rounded-xl p-3 border border-hairline">
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center mb-2 ${s.tint}`}>
                  <s.Icon size={14} />
                </div>
                <div className="text-lg font-bold text-ink">{s.value}</div>
                <div className="text-[10px] text-ink-faint mt-0.5">{s.label}</div>
              </div>
            ))}
          </div>
        </Section>

        {/* Memory */}
        <Section icon={Database} title="Memory">
          <div className="grid grid-cols-2 gap-3">
            {memory.map(m => (
              <div key={m.label} className="bg-gray-50 rounded-xl p-3 border border-hairline">
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center mb-2 ${m.tint}`}>
                  <m.Icon size={14} />
                </div>
                <div className="text-lg font-bold text-ink">{m.value}</div>
                <div className="text-[10px] text-ink-faint mt-0.5">{m.label}</div>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, children }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={13} className="text-ink-faint" />
        <span className="text-[10px] font-semibold text-ink-faint uppercase tracking-wider">{title}</span>
      </div>
      {children}
    </div>
  );
}
