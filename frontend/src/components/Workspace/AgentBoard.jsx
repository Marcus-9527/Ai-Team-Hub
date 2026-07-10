/**
 * AgentBoard.jsx — 当前任务中的 AI Teammate 面板
 *
 * 聚合步骤 + 执行记录 + teammate 元数据，展示每个 teammate 的实时状态。
 */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, Users, RefreshCw, AlertTriangle,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import * as api from '../../services/api';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import AgentCard from './AgentCard';

export default function AgentBoard({ taskId }) {
  const [teammates, setTeammates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Aggregate progress + executions + teammate metadata
  const load = useCallback(async () => {
    if (!taskId) return;
    try {
      setLoading(true);
      setError(null);
      const [progress, executionsData, tmList] = await Promise.all([
        taskApi.getTaskProgress(taskId).catch(() => null),
        taskApi.getTaskExecutions(taskId).catch(() => null),
        api.listTeammates().catch(() => []),
      ]);

      // Build teammate metadata map
      const metaMap = {};
      (tmList || []).forEach(t => {
        metaMap[t.id] = { name: t.name, avatar_emoji: t.avatar_emoji, role: t.role, model_name: t.model_name };
      });

      const steps = progress?.steps || [];
      const executions = executionsData?.executions || [];

      // Per-teammate aggregation map
      const map = new Map();

      steps.forEach(step => {
        const tid = step.teammate_id || '__unassigned__';
        if (!map.has(tid)) {
          map.set(tid, { teammate_id: tid, stepStatus: null, execStatus: null, current_step: null, duration: 0, steps_assigned: 0, steps_done: 0, model_name: null });
        }
        const entry = map.get(tid);
        entry.steps_assigned += 1;
        if (step.status === 'COMPLETED') entry.steps_done += 1;
        entry.stepStatus = step.status;
        entry.current_step = step.objective || `步骤 ${step.order}`;
      });

      executions.forEach(ex => {
        const tid = ex.teammate_id || '__unassigned__';
        if (!map.has(tid)) {
          map.set(tid, { teammate_id: tid, stepStatus: null, execStatus: null, current_step: null, duration: 0, steps_assigned: 0, steps_done: 0, model_name: null });
        }
        const entry = map.get(tid);
        if (ex.model_name) entry.model_name = ex.model_name;
        if (ex.execution_time_ms != null) {
          entry.duration = Math.max(entry.duration || 0, ex.execution_time_ms);
        }
        entry.execStatus = ex.status;
      });

      // Build final list
      const result = [];
      map.forEach((entry) => {
        if (entry.teammate_id === '__unassigned__') return;
        const meta = metaMap[entry.teammate_id] || {};
        result.push({
          ...entry,
          name: meta.name || entry.teammate_id,
          avatar_emoji: meta.avatar_emoji || '🤖',
          role: meta.role || '',
          model_name: entry.model_name || meta.model_name || null,
        });
      });

      // Sort: running first, then failed, then by name
      const ORDER = { running: 0, failed: 1, paused: 2, completed: 3, pending: 4, idle: 5 };
      result.sort((a, b) => {
        const oa = ORDER[a.status] ?? 99;
        const ob = ORDER[b.status] ?? 99;
        if (oa !== ob) return oa - ob;
        return (a.name || '').localeCompare(b.name || '');
      });

      setTeammates(result);
    } catch (e) {
      console.error('[AgentBoard] load failed:', e);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  // ── Initial load ──
  useEffect(() => { load(); }, [load]);

  // ── SSE real-time refresh ──
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (task_id === taskId) {
        load();
      }
    });
    return unsub;
  }, [taskId, load]);

  // ── Loading ──
  if (loading && teammates.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  // ── Error ──
  if (error && teammates.length === 0) {
    return (
      <div className="text-center py-12">
        <AlertTriangle size={32} className="mx-auto mb-2 text-red-400" />
        <p className="text-sm text-ink-faint">加载失败: {error}</p>
        <button
          onClick={load}
          className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-ink-mute border border-hairline hover:bg-gray-50"
        >
          <RefreshCw size={12} /> 重试
        </button>
      </div>
    );
  }

  // ── Empty ──
  if (teammates.length === 0) {
    return (
      <div className="text-center py-12">
        <Users size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">暂无队友参与此任务</p>
        <p className="text-xs text-ink-faint mt-1">为步骤分配 teammate 后会在这里显示</p>
      </div>
    );
  }

  return (
    <div>
      {/* Summary bar */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 text-xs text-ink-mute">
          <Users size={14} />
          <span>队友 ({teammates.length})</span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold text-ink-faint border border-hairline hover:bg-gray-50 disabled:opacity-50 transition-all"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {/* Agent cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {teammates.map(tm => (
          <AgentCard key={tm.teammate_id} teammate={tm} />
        ))}
      </div>
    </div>
  );
}
