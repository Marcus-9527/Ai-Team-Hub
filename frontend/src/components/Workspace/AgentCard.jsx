/**
 * AgentCard.jsx — 单个 Teammate 卡片
 *
 * 展示 teammate 在当前任务中的实时状态：
 *   teammate_id, name, avatar_emoji, role, status,
 *   model_name, current_step, execution_duration
 */
import { motion } from 'framer-motion';
import {
  User, Cpu, Clock, Activity,
  CheckCircle2, Loader2, XCircle, AlertTriangle,
  PauseCircle,
} from 'lucide-react';

const STATUS_CONFIG = {
  idle:        { label: '空闲',   color: 'text-gray-400', bg: 'bg-gray-100', icon: Activity },
  running:     { label: '执行中', color: 'text-indigo-600', bg: 'bg-indigo-100', icon: Loader2 },
  completed:   { label: '完成',   color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle2 },
  failed:      { label: '失败',   color: 'text-red-600',   bg: 'bg-red-100',   icon: XCircle },
  pending:     { label: '待执行', color: 'text-amber-600', bg: 'bg-amber-100', icon: Clock },
  paused:      { label: '暂停',   color: 'text-amber-600', bg: 'bg-amber-100', icon: PauseCircle },
};

const STATUS_PRIORITY = ['running', 'failed', 'paused', 'completed', 'pending', 'idle'];

function resolveStatus(stepStatus, execStatus) {
  if (execStatus === 'running' || execStatus === 'executing') return 'running';
  if (stepStatus === 'RUNNING') return 'running';
  if (stepStatus === 'FAILED' || execStatus === 'failed' || execStatus === 'error') return 'failed';
  if (stepStatus === 'COMPLETED') return 'completed';
  if (stepStatus === 'PAUSED') return 'paused';
  if (stepStatus === 'PENDING' || stepStatus === 'SCHEDULED') return 'pending';
  return 'idle';
}

function formatDuration(ms) {
  if (ms == null) return '-';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

export default function AgentCard({ teammate }) {
  const {
    teammate_id,
    name,
    avatar_emoji,
    role,
    model_name,
    current_step,
    status: rawStatus,
    stepStatus,
    execStatus,
    duration,
    steps_assigned,
    steps_done,
  } = teammate || {};

  const resolved = resolveStatus(stepStatus, execStatus);
  const sc = STATUS_CONFIG[resolved] || STATUS_CONFIG.idle;
  const StatusIcon = sc.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-hairline p-4 hover:shadow-sm transition-shadow"
    >
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center text-lg flex-shrink-0">
          {avatar_emoji || '🤖'}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-bold text-ink truncate">{name || teammate_id}</h4>
            {role && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-ink-faint">
                {role}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${sc.bg} ${sc.color}`}>
              <StatusIcon size={10} className={resolved === 'running' ? 'animate-spin' : ''} />
              {sc.label}
            </span>
            {model_name && (
              <span className="flex items-center gap-1 text-[10px] text-ink-faint">
                <Cpu size={10} />
                {model_name.length > 20 ? model_name.slice(0, 20) + '…' : model_name}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 mt-3">
        <div className="bg-gray-50 rounded-lg px-3 py-2">
          <div className="text-[10px] text-ink-faint">当前步骤</div>
          <div className="text-xs font-semibold text-ink truncate" title={current_step}>
            {current_step || '-'}
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg px-3 py-2">
          <div className="text-[10px] text-ink-faint flex items-center gap-1">
            <Clock size={9} /> 耗时
          </div>
          <div className="text-xs font-semibold text-ink">{formatDuration(duration)}</div>
        </div>
      </div>

      {/* Step progress bar */}
      {steps_assigned > 0 && (
        <div className="mt-3 pt-3 border-t border-hairline">
          <div className="flex items-center justify-between text-[10px] text-ink-faint mb-1">
            <span>步骤进度</span>
            <span>{steps_done}/{steps_assigned}</span>
          </div>
          <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${(steps_done / steps_assigned) * 100}%` }}
              transition={{ duration: 0.4, ease: 'easeOut' }}
              className={`h-full rounded-full ${
                resolved === 'failed' ? 'bg-red-400' :
                resolved === 'completed' ? 'bg-green-500' :
                'bg-indigo-500'
              }`}
            />
          </div>
        </div>
      )}

      {/* Teammate ID (debug) */}
      <div className="mt-2 text-[10px] text-ink-faint truncate font-mono">
        {teammate_id}
      </div>
    </motion.div>
  );
}
