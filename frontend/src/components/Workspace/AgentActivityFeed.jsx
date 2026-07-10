/**
 * AgentActivityFeed.jsx — 实时 AI 团队活动时间线
 *
 * 消费 taskEventBus，展示任务生命周期事件：
 *   CREATED, STARTED, STEP_STARTED, STEP_COMPLETED,
 *   FAILED, COMPLETED, APPROVAL_REQUIRED
 *
 * 实时追加，自动按时间排序。
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity, Loader2, RefreshCw, AlertTriangle,
  CheckCircle2, XCircle, Clock, User,
  PlayCircle, FileText, ThumbsUp, Zap,
} from 'lucide-react';
import { subscribeTaskEvents } from '../../services/taskEventBus';

// ── Event type display config ──
const EVENT_CONFIG = {
  // Internal event type (from SSE) → display mapping
  task_started:        { label: '任务已开始',     icon: PlayCircle,  color: 'text-blue-600',   bg: 'bg-blue-100' },
  task_completed:      { label: '任务已完成',     icon: CheckCircle2, color: 'text-green-600',  bg: 'bg-green-100' },
  step_started:        { label: '步骤已开始',     icon: PlayCircle,  color: 'text-indigo-600',  bg: 'bg-indigo-100' },
  step_completed:      { label: '步骤已完成',     icon: CheckCircle2, color: 'text-green-600',  bg: 'bg-green-100' },
  execution_started:   { label: '开始执行',       icon: Zap,         color: 'text-indigo-600',  bg: 'bg-indigo-100' },
  execution_completed: { label: '执行完成',       icon: CheckCircle2, color: 'text-green-600',  bg: 'bg-green-100' },
  approval_required:   { label: '等待审批',       icon: ThumbsUp,    color: 'text-amber-600',  bg: 'bg-amber-100' },
  approval_completed:  { label: '审批完成',       icon: ThumbsUp,    color: 'text-green-600',  bg: 'bg-green-100' },
  plan_created:        { label: '计划已创建',     icon: FileText,    color: 'text-purple-600', bg: 'bg-purple-100' },
  task_failed:         { label: '任务失败',       icon: XCircle,     color: 'text-red-600',    bg: 'bg-red-100' },
  step_failed:         { label: '步骤失败',       icon: XCircle,     color: 'text-red-600',    bg: 'bg-red-100' },
  execution_quality_updated: { label: '质量评分更新', icon: Activity, color: 'text-purple-600', bg: 'bg-purple-100' },
};

const EVENT_DISPLAY_ORDER = {
  task_started: 0,
  plan_created: 1,
  task_completed: 99,
  task_failed: 98,
};

const MAX_EVENTS = 100;

// ── Map SSE event to display-friendly shape ──
function normalizeEvent(event) {
  const { type, task_id, step_id, teammate_id, model_name, data } = event || {};
  const cfg = EVENT_CONFIG[type] || { label: type, icon: Activity, color: 'text-gray-500', bg: 'bg-gray-100' };

  // Build description
  let description = '';
  if (step_id && teammate_id) {
    description = `步骤 ${teammate_id}`;
  } else if (teammate_id) {
    description = teammate_id;
  } else if (step_id) {
    description = `步骤 ${step_id.slice(0, 8)}`;
  }

  // Determine display type for ordering
  let displayType = type;
  if (type === 'step_completed' || type === 'step_failed') {
    const stepData = event.step || {};
    if (stepData.objective) description = stepData.objective;
  }
  // Map step_failed to FAILED display
  if (type === 'execution_completed' && event.status === 'failed') {
    displayType = 'step_failed';
  }
  if (type === 'task_completed' && event.status === 'failed') {
    displayType = 'task_failed';
  }

  return {
    id: `${type}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    type: displayType,
    rawType: type,
    timestamp: Date.now(),
    task_id,
    teammate_id,
    description,
    model_name,
    ...cfg,
    data: event,
  };
}

export default function AgentActivityFeed({ taskId, maxEvents = 50 }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef(null);
  const limit = Math.min(maxEvents, MAX_EVENTS);

  // ── Subscribe to SSE events ──
  useEffect(() => {
    if (!taskId) return;

    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (task_id !== taskId) return;

      const normalized = normalizeEvent(event);
      setEvents(prev => {
        const next = [normalized, ...prev].slice(0, limit);
        return next;
      });
    });

    // Mark ready after first tick so "connected" state works
    setLoading(false);

    return unsub;
  }, [taskId, limit]);

  // ── Auto-scroll to top on new events ──
  useEffect(() => {
    if (containerRef.current && events.length > 0) {
      containerRef.current.scrollTop = 0;
    }
  }, [events.length]);

  // ── Icon resolver ──
  const getIcon = (cfg) => {
    const Icon = cfg.icon || Activity;
    const cls = cfg.color || 'text-gray-500';
    return <Icon size={12} className={cls} />;
  };

  // ── Format timestamp ──
  const formatTime = (ts) => {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  // ── Loading ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={16} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  // ── Empty ──
  if (events.length === 0) {
    return (
      <div className="text-center py-8">
        <Activity size={24} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-xs text-ink-faint">等待实时事件…</p>
        <p className="text-[10px] text-ink-faint mt-0.5">任务执行时这里会实时显示活动</p>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs text-ink-mute">
          <Activity size={13} />
          <span>实时活动 ({events.length})</span>
        </div>
      </div>

      {/* Timeline */}
      <div
        ref={containerRef}
        className="max-h-[400px] overflow-y-auto space-y-0.5 pr-1"
      >
        <AnimatePresence mode="popLayout">
          {events.map((evt, idx) => (
            <motion.div
              key={evt.id}
              layout
              initial={{ opacity: 0, x: -12, height: 0 }}
              animate={{ opacity: 1, x: 0, height: 'auto' }}
              exit={{ opacity: 0, x: 12, height: 0 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-gray-50 transition-colors"
            >
              {/* Timeline dot */}
              <div className={`mt-0.5 w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${evt.bg || 'bg-gray-100'}`}>
                {getIcon(evt)}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className={`text-[11px] font-semibold ${evt.color || 'text-ink'}`}>
                    {evt.label}
                  </span>
                  {evt.description && (
                    <span className="text-[10px] text-ink-faint truncate max-w-[140px]">
                      · {evt.description}
                    </span>
                  )}
                  {evt.model_name && (
                    <span className="text-[9px] text-ink-faint px-1 py-0.5 rounded bg-gray-100">
                      {evt.model_name.split('/').pop()}
                    </span>
                  )}
                </div>
                <div className="text-[9px] text-ink-faint mt-0.5">
                  {formatTime(evt.timestamp)}
                  {evt.teammate_id && (
                    <span className="ml-1.5">· {evt.teammate_id}</span>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
