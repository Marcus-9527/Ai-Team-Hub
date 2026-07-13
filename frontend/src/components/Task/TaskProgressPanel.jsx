import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Users, Loader2 } from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { dispatchTaskEvent } from '../../services/taskEventBus';
import TeamPanel from './TeamPanel';

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
    const url = `${BASE}/api/tasks/${task.id}/events`;
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
            <span className={`w-4 h-4 rounded-full ${sc.dot}`} />
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
