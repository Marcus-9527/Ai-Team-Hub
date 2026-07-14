import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Users, Loader2, Cpu, GitBranch, UserPlus, Rocket, CheckCircle2 } from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { dispatchTaskEvent, subscribeTaskEvents } from '../../services/taskEventBus';
import TeamPanel from './TeamPanel';

// Live event timeline — what the backend actually did after the task was submitted.
const EVENT_META = {
  planning_started:    { icon: Cpu,          label: '开始规划方案',  color: 'text-blue-600' },
  dag_created:         { icon: GitBranch,    label: '已生成任务拆解', color: 'text-blue-600' },
  team_created:        { icon: UserPlus,     label: '已组建团队',    color: 'text-purple-600' },
  execution_started:   { icon: Rocket,       label: '开始执行',      color: 'text-indigo-600' },
  execution_completed: { icon: CheckCircle2, label: '执行完成',      color: 'text-green-600' },
  step_started:        { icon: Loader2,      label: '步骤开始',      color: 'text-indigo-600' },
  step_completed:      { icon: CheckCircle2, label: '步骤完成',      color: 'text-green-600' },
};

function eventDetail(type, data = {}) {
  if (type === 'dag_created' && data.node_count) return `${data.node_count} 个任务节点`;
  if (type === 'team_created' && data.team_count) return `${data.team_count} 名成员`;
  if (type === 'execution_completed') {
    if (data.status === 'FAILED') return data.error ? `失败：${data.error}` : '失败';
    if (data.status === 'COMPLETED') return '全部完成';
  }
  return '';
}

const STATUS = {
  CREATED:    { label: '待处理',  color: 'text-gray-500',  bg: 'bg-gray-100',  dot: 'bg-gray-400' },
  PLANNING:   { label: '规划中',  color: 'text-blue-600',  bg: 'bg-blue-100',  dot: 'bg-blue-500' },
  ASSIGNED:   { label: '已分配',  color: 'text-purple-600', bg: 'bg-purple-100', dot: 'bg-purple-500' },
  EXECUTING:  { label: '执行中',  color: 'text-indigo-600', bg: 'bg-indigo-100', dot: 'bg-indigo-500' },
  COMPLETED:  { label: '已完成',  color: 'text-green-600',  bg: 'bg-green-100', dot: 'bg-green-500' },
  FAILED:     { label: '失败',    color: 'text-red-600',    bg: 'bg-red-100',   dot: 'bg-red-500' },
  CANCELLED:  { label: '已取消',  color: 'text-gray-500',  bg: 'bg-gray-100',  dot: 'bg-gray-400' },
};

const PENDING = { label: '待处理', color: 'text-gray-500', bg: 'bg-gray-100', dot: 'bg-gray-400' };

export default function TaskProgressPanel({
  task, steps, loading, userMode = 'user',
  onBack, onRefresh, onViewAdvanced,
}) {
  const sc = STATUS[task?.status] || PENDING;
  const sseRef = useRef(null);

  // SSE connection to /api/tasks/{task_id}/events
  useEffect(() => {
    if (!task?.id) return;
    const BASE = import.meta.env.VITE_API_BASE || '';
    const API_KEY = import.meta.env.VITE_API_KEY || '';
    const url = `${BASE}/api/tasks/${task.id}/events` + (API_KEY ? `?api_key=${API_KEY}` : '');
    const es = new EventSource(url);
    sseRef.current = es;

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        dispatchTaskEvent({ ...event, task_id: task.id });
        onRefresh?.();
      } catch { /* ignore bad frames */ }
    };

    es.onerror = () => {
      // SSE will auto-reconnect; nothing to do
    };

    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  const total = steps.length;
  const done = steps.filter(s => s.status === 'COMPLETED').length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const active = ['PLANNING', 'ASSIGNED', 'EXECUTING'].includes(task?.status);

  // Live event timeline from the SSE taskEventBus.
  const [events, setEvents] = useState([]);
  useEffect(() => {
    if (!task?.id) return;
    setEvents([]);
    return subscribeTaskEvents((e) => {
      if (e.task_id !== task.id) return;
      setEvents(prev => [...prev, { ...e, _t: Date.now() }]);
    });
  }, [task?.id]);

  return (
    <div className="flex-1 overflow-y-auto bg-canvas">
      <div className="max-w-3xl mx-auto p-5 space-y-4">
        {/* Back + title + status */}
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint">
            <ArrowLeft size={18} />
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="font-bold text-[15px] text-ink truncate">{task?.title}</h2>
          </div>
          <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${sc.bg} ${sc.color}`}>
            {sc.label}
          </span>
        </div>

        {/* Status banner */}
        <div className="bg-white rounded-xl border border-hairline p-5 text-center">
          <div className={`w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-3 ${sc.bg}`}>
            {active
              ? <Loader2 size={22} className={`animate-spin ${sc.color}`} />
              : <span className={`w-4 h-4 rounded-full ${sc.dot}`} />}
          </div>
          <h3 className="text-base font-bold text-ink mb-1">
            {task?.status === 'EXECUTING' ? 'AI 团队正在工作' :
             task?.status === 'COMPLETED' ? '任务已完成' :
             task?.status === 'FAILED' ? '任务失败' :
             task?.status === 'PLANNING' ? '正在规划方案' :
             task?.status === 'ASSIGNED' ? '已分配团队' :
             task?.status === 'CREATED' ? '任务已创建' : '处理中'}
          </h3>
          {total > 0 && (
            <div className="flex items-center justify-center gap-1.5 text-xs text-ink-faint">
              {loading && <Loader2 size={12} className="animate-spin" />}
              <span>{done}/{total} 步骤完成</span>
            </div>
          )}
        </div>

        {/* Live event timeline — what the backend is actually doing */}
        {events.length > 0 && (
          <div className="bg-white rounded-xl border border-hairline p-4">
            <h3 className="text-sm font-bold text-ink mb-3">实时动态</h3>
            <div className="space-y-2">
              {events.map((ev) => {
                const meta = EVENT_META[ev.type];
                if (!meta) return null;
                const Icon = meta.icon;
                const detail = eventDetail(ev.type, ev.data);
                return (
                  <div key={ev._t} className="flex items-start gap-2.5">
                    <span className={`mt-0.5 ${meta.color}`}><Icon size={15} /></span>
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-medium text-ink">{meta.label}</span>
                      {detail && <span className="text-xs text-ink-faint ml-1.5">{detail}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Progress bar */}
        {total > 0 && (
          <div className="bg-white rounded-xl border border-hairline p-4">
            <div className="w-full h-2.5 bg-gray-100 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
                className={`h-full rounded-full ${
                  task?.status === 'FAILED' || task?.status === 'CANCELLED'
                    ? 'bg-red-400'
                    : task?.status === 'COMPLETED'
                    ? 'bg-green-500'
                    : 'bg-indigo-500'
                }`}
              />
            </div>
          </div>
        )}

        {/* AI Team */}
        {total > 0 && (
          <div className="bg-white rounded-xl border border-hairline p-4">
            <div className="flex items-center gap-2 mb-3">
              <Users size={14} className="text-ink-faint" />
              <h3 className="text-sm font-bold text-ink">AI 团队</h3>
            </div>
            <TeamPanel steps={steps} />
          </div>
        )}

        {/* Expert mode entry */}
        <div className="text-center pb-2">
          <button
            onClick={onViewAdvanced}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-ink-mute border border-hairline hover:bg-gray-50 transition-all"
          >
            <Users size={12} />
            专家模式
          </button>
        </div>
      </div>
    </div>
  );
}
