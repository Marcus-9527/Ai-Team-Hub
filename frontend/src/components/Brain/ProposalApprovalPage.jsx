import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FileCheck, XCircle, Clock, AlertTriangle, Loader2,
  ChevronDown, ChevronRight, ThumbsUp, ThumbsDown, Bot,
} from 'lucide-react';
import * as api from '../../services/api';

const STATUS_LABELS = {
  created: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
};

const STATUS_COLORS = {
  created: '#f59e0b',
  approved: '#22c55e',
  rejected: '#ef4444',
  expired: '#6b7280',
};

export default function ProposalApprovalPage({ onBack, lang }) {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [actioning, setActioning] = useState(null);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [pending, all] = await Promise.all([
        api.listPendingProposals(),
        api.listProposals(),
      ]);
      const map = {};
      (pending.proposals || []).forEach(p => map[p.id] = p);
      (all.proposals || []).forEach(p => { map[p.id] = p; });
      const sorted = Object.values(map).sort((a, b) => b.created_at - a.created_at);
      setProposals(sorted);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleApprove = async (proposalId) => {
    setActioning(proposalId);
    await api.approveProposal(proposalId);
    await loadAll();
    setActioning(null);
  };

  const handleReject = async (proposalId) => {
    setActioning(proposalId);
    await api.rejectProposal(proposalId);
    await loadAll();
    setActioning(null);
  };

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FileCheck size={24} style={{ color: 'var(--color-primary)' }} />
            <h1 className="text-xl font-bold" style={{ color: 'var(--color-ink)' }}>Brain 提案审批</h1>
          </div>
          <button
            onClick={loadAll}
            className="text-xs px-3 py-1.5 rounded-lg transition-all flex items-center gap-1"
            style={{
              background: 'rgba(0,0,0,0.05)',
              color: 'var(--color-ink-faint)',
              border: '1px solid rgba(0,0,0,0.08)',
            }}
          >
            <Clock size={12} /> 刷新
          </button>
        </div>

        <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          AI Teammate 学习到的经验可能需要修改其核心人格——这些修改需要人工批准后才能生效。
        </p>

        {/* Stats */}
        <div className="flex gap-3 text-xs">
          {['created', 'approved', 'rejected', 'expired'].map(st => {
            const count = proposals.filter(p => p.status === st).length;
            return (
              <div key={st} className="rounded-lg px-3 py-2 flex items-center gap-1.5"
                style={{ border: '1px solid rgba(0,0,0,0.06)', background: 'rgba(0,0,0,0.02)' }}>
                <span className="w-2 h-2 rounded-full" style={{ background: STATUS_COLORS[st] }} />
                <span style={{ color: 'var(--color-ink-faint)' }}>{STATUS_LABELS[st]}</span>
                <span className="font-medium" style={{ color: 'var(--color-ink)' }}>{count}</span>
              </div>
            );
          })}
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin" size={32} style={{ color: 'var(--color-primary)' }} />
          </div>
        )}

        {/* No proposals */}
        {!loading && proposals.length === 0 && (
          <div className="flex flex-col items-center py-12 gap-3" style={{ color: 'var(--color-ink-faint)' }}>
            <Bot size={40} opacity={0.3} />
            <p className="text-sm">暂无提案。AI Teammate 执行任务后会根据 Reflection 生成待审批提案。</p>
          </div>
        )}

        {/* Proposal List */}
        <div className="space-y-3">
          {proposals.map(prop => {
            const isExpanded = expanded === prop.id;
            const isPending = prop.status === 'created';
            return (
              <motion.div
                key={prop.id}
                layout
                className="rounded-xl overflow-hidden"
                style={{
                  border: `1px solid ${
                    isPending ? 'rgba(245,158,11,0.3)' : 'rgba(0,0,0,0.06)'
                  }`,
                  background: isPending ? 'rgba(245,158,11,0.04)' : 'rgba(0,0,0,0.02)',
                }}
              >
                {/* Header */}
                <button
                  onClick={() => setExpanded(isExpanded ? null : prop.id)}
                  className="w-full flex items-center justify-between p-4 hover:bg-black/5 transition-all text-left"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ background: STATUS_COLORS[prop.status] || '#6b7280' }} />
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate" style={{ color: 'var(--color-ink)' }}>
                        {prop.target_label || prop.target_type}
                      </div>
                      <div className="text-xs mt-0.5 flex gap-2" style={{ color: 'var(--color-ink-faint)' }}>
                        <span>Teammate: {prop.teammate_id ? prop.teammate_id.substring(0, 8) : '?'}</span>
                        <span>·</span>
                        <span>{STATUS_LABELS[prop.status]}</span>
                        {prop.task_id && (
                          <>
                            <span>·</span>
                            <span>Task: {prop.task_id.substring(0, 8)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    {isPending && (
                      <div className="flex gap-1" onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => handleApprove(prop.id)}
                          disabled={actioning === prop.id}
                          className="p-1.5 rounded-md transition-all hover:bg-green-500/20"
                          style={{ color: '#22c55e' }}
                          title="批准"
                        >
                          {actioning === prop.id
                            ? <Loader2 size={14} className="animate-spin" />
                            : <ThumbsUp size={14} />
                          }
                        </button>
                        <button
                          onClick={() => handleReject(prop.id)}
                          disabled={actioning === prop.id}
                          className="p-1.5 rounded-md transition-all hover:bg-red-500/20"
                          style={{ color: '#ef4444' }}
                          title="拒绝"
                        >
                          <ThumbsDown size={14} />
                        </button>
                      </div>
                    )}
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </div>
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="px-4 pb-4 space-y-3"
                  >
                    {/* Status badge */}
                    <div className="flex gap-2 text-xs">
                      <span className="px-2 py-0.5 rounded-full"
                        style={{
                          background: `${STATUS_COLORS[prop.status]}20`,
                          color: STATUS_COLORS[prop.status],
                        }}>
                        {STATUS_LABELS[prop.status]}
                      </span>
                      {prop.resolved_by && (
                        <span style={{ color: 'var(--color-ink-faint)' }}>
                          由 {prop.resolved_by} 处理
                        </span>
                      )}
                    </div>

                    {/* Reason */}
                    {prop.reason && (
                      <div className="text-xs rounded-lg p-3"
                        style={{ background: 'rgba(0,0,0,0.03)', color: 'var(--color-ink-faint)' }}>
                        <span className="font-medium" style={{ color: 'var(--color-ink)' }}>理由:</span>
                        <p className="mt-1">{prop.reason}</p>
                      </div>
                    )}

                    {/* Diff */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {/* Original */}
                      <div className="text-xs rounded-lg p-3"
                        style={{ background: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.15)' }}>
                        <div className="font-medium mb-1" style={{ color: '#ef4444' }}>当前值</div>
                        <pre className="whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--color-ink-faint)' }}>
                          {prop.original_content || '(空)'}
                        </pre>
                      </div>

                      {/* Proposed */}
                      <div className="text-xs rounded-lg p-3"
                        style={{ background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.15)' }}>
                        <div className="font-medium mb-1" style={{ color: '#22c55e' }}>修改为</div>
                        <pre className="whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--color-ink)' }}>
                          {prop.proposed_content || '(空)'}
                        </pre>
                      </div>
                    </div>

                    {/* Diff summary */}
                    {prop.diff_summary && (
                      <div className="text-xs rounded-lg p-2"
                        style={{ background: 'rgba(0,0,0,0.03)', color: 'var(--color-ink-faint)' }}>
                        <span className="font-medium" style={{ color: 'var(--color-ink)' }}>变更摘要: </span>
                        {prop.diff_summary}
                      </div>
                    )}

                    {/* Action buttons (in case header clicks didn't fire) */}
                    {isPending && (
                      <div className="flex gap-2 pt-2 border-t"
                        style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                        <button
                          onClick={() => handleApprove(prop.id)}
                          disabled={actioning === prop.id}
                          className="flex items-center gap-1.5 text-xs px-4 py-2 rounded-lg transition-all"
                          style={{
                            background: 'rgba(34,197,94,0.15)',
                            color: '#22c55e',
                          }}
                        >
                          {actioning === prop.id
                            ? <Loader2 size={12} className="animate-spin" />
                            : <ThumbsUp size={12} />
                          }
                          批准修改
                        </button>
                        <button
                          onClick={() => handleReject(prop.id)}
                          disabled={actioning === prop.id}
                          className="flex items-center gap-1.5 text-xs px-4 py-2 rounded-lg transition-all"
                          style={{
                            background: 'rgba(239,68,68,0.1)',
                            color: '#ef4444',
                          }}
                        >
                          <ThumbsDown size={12} />
                          拒绝
                        </button>
                      </div>
                    )}
                  </motion.div>
                )}
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
