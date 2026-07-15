/**
 * AIOpsCenter.jsx — AI Operations Center (Phase 27)
 *
 * Evolved from AutonomousCenter. Adds running tasks overview
 * and recent execution stats on top of teammate states + proposals.
 */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Bot, Cpu, Clock, ThumbsUp, ThumbsDown, Zap, RefreshCw,
  AlertCircle, CheckCircle2, Activity, Loader2,
} from 'lucide-react';
import * as api from '../../services/api';

const STATE_DOT = {
  thinking: '#818cf8',
  working:  '#f59e0b',
  idle:     '#d1d5db',
  active:   '#34d399',
  offline:  '#6b7280',
};
const STATE_LABEL = {
  thinking: '思考中',
  working:  '工作中',
  idle:     '空闲',
  active:   '活跃',
  offline:  '离线',
};

export default function AIOpsCenter() {
  const [states, setStates] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actioning, setActioning] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, prop] = await Promise.all([
        api.listTeammateStates().catch(() => ({ states: [] })),
        api.listPendingProposals().catch(() => ({ proposals: [] })),
      ]);
      setStates(st.states || []);
      setProposals(prop.proposals || []);
      // Load recent executions
      try {
        const stats = await api.fetch('/api/executions/stats').catch(() => null);
        if (stats) setRuns(stats.recent_runs || []);
      } catch {}
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll states every 5s
  useEffect(() => {
    const iv = setInterval(() => {
      api.listTeammateStates().then(r => setStates(r.states || [])).catch(() => {});
    }, 5000);
    return () => clearInterval(iv);
  }, []);

  const handleApprove = async (id) => {
    setActioning(id);
    await api.approveProposal(id).catch(console.error);
    await load();
    setActioning(null);
  };
  const handleReject = async (id) => {
    setActioning(id);
    await api.rejectProposal(id).catch(console.error);
    await load();
    setActioning(null);
  };

  const runnableStates = runs.filter(r => r.status === 'RUNNING' || r.status === 'PENDING');

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-5xl mx-auto p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap size={24} style={{ color: 'var(--color-primary)' }} />
            <h1 className="text-xl font-bold" style={{ color: 'var(--color-ink)' }}>AI 自动化</h1>
          </div>
          <button
            onClick={load}
            className="text-xs px-3 py-1.5 rounded-lg transition-all flex items-center gap-1"
            style={{ background: 'rgba(0,0,0,0.05)', color: 'var(--color-ink-faint)', border: '1px solid rgba(0,0,0,0.08)' }}
          >
            <RefreshCw size={12} /> 刷新
          </button>
        </div>

        {loading && (
          <div className="flex justify-center py-12">
            <RefreshCw size={32} className="animate-spin" style={{ color: 'var(--color-primary)' }} />
          </div>
        )}

        {/* Running / Pending executions */}
        {runnableStates.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold mb-2 flex items-center gap-2" style={{ color: 'var(--color-ink)' }}>
              <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-primary)' }} /> 运行中的任务
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium" style={{ background: 'rgba(129,140,248,0.15)', color: '#818cf8' }}>
                {runnableStates.length}
              </span>
            </h2>
            <div className="space-y-1.5">
              {runnableStates.map(r => (
                <div key={r.execution_id || r.id} className="rounded-xl p-2.5 flex items-center gap-2"
                  style={{ border: '1px solid rgba(129,140,248,0.2)', background: 'rgba(129,140,248,0.04)' }}>
                  <span className="w-2 h-2 rounded-full flex-shrink-0 bg-indigo-400 animate-pulse" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm truncate" style={{ color: 'var(--color-ink)' }}>
                      {r.task_id ? r.task_id.slice(0, 8) : 'unknown'}
                    </p>
                    <p className="text-[10px]" style={{ color: 'var(--color-ink-faint)' }}>
                      {r.teammate || ''} — {r.model || ''}
                    </p>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-medium text-indigo-600 bg-indigo-100">{r.status}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Teammate runtime states */}
        <section>
          <h2 className="text-sm font-semibold mb-2 flex items-center gap-2" style={{ color: 'var(--color-ink)' }}>
            <Activity size={14} style={{ color: 'var(--color-primary)' }} /> 队友运行时状态
          </h2>
          {states.length === 0 ? (
            <p className="text-xs py-4" style={{ color: 'var(--color-ink-faint)' }}>暂无队友状态。在频道发消息后这里会显示实时状态。</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {states.map(s => {
                const st = s.state || s.current_state || 'idle';
                return (
                  <div key={s.teammate_id || s.id} className="rounded-xl p-3 flex items-center gap-2"
                    style={{ border: '1px solid rgba(0,0,0,0.06)', background: 'rgba(0,0,0,0.02)' }}>
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: STATE_DOT[st] || STATE_DOT.idle }} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: 'var(--color-ink)' }}>{s.teammate_name || s.name || 'Teammate'}</p>
                      <p className="text-[10px]" style={{ color: 'var(--color-ink-faint)' }}>{STATE_LABEL[st] || st}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Pending brain proposals */}
        <section>
          <h2 className="text-sm font-semibold mb-2 flex items-center gap-2" style={{ color: 'var(--color-ink)' }}>
            <Bot size={14} style={{ color: 'var(--color-primary)' }} /> 待审批提案
            {proposals.length > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>
                {proposals.length}
              </span>
            )}
          </h2>
          {proposals.length === 0 ? (
            <p className="text-xs py-4" style={{ color: 'var(--color-ink-faint)' }}>暂无待审批提案。</p>
          ) : (
            <div className="space-y-2">
              {proposals.map(p => (
                <motion.div key={p.id} layout className="rounded-xl p-3"
                  style={{ border: '1px solid rgba(245,158,11,0.25)', background: 'rgba(245,158,11,0.04)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: 'var(--color-ink)' }}>{p.target_label || p.target_type}</p>
                      <p className="text-[10px] truncate" style={{ color: 'var(--color-ink-faint)' }}>{p.reason || ''}</p>
                    </div>
                    <div className="flex gap-1.5 flex-shrink-0">
                      <button onClick={() => handleApprove(p.id)} disabled={actioning === p.id}
                        className="p-1.5 rounded-md transition-all hover:bg-green-500/20" style={{ color: '#34d399' }} title="批准">
                        {actioning === p.id ? <RefreshCw size={13} className="animate-spin" /> : <ThumbsUp size={13} />}
                      </button>
                      <button onClick={() => handleReject(p.id)} disabled={actioning === p.id}
                        className="p-1.5 rounded-md transition-all hover:bg-red-500/20" style={{ color: '#ef4444' }} title="拒绝">
                        <ThumbsDown size={13} />
                      </button>
                    </div>
                  </div>
                  {p.proposed_content && (
                    <pre className="text-[11px] mt-2 rounded-lg p-2 whitespace-pre-wrap leading-relaxed" style={{ background: 'rgba(0,0,0,0.3)', color: 'var(--color-ink-faint)' }}>
                      {p.proposed_content.slice(0, 300)}
                    </pre>
                  )}
                </motion.div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
