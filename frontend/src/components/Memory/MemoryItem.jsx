/**
 * MemoryItem.jsx — 单条记忆卡片 (V3.1 Phase B)
 *
 * Type icons:
 *   decision    → 决策
 *   conversation→ 对话
 *   reasoning   → 推理
 *   execution   → 执行
 *   revision    → 修订
 *   event       → 事件
 */
import { motion } from 'framer-motion';
import {
  BrainCircuit, MessageSquare, Lightbulb, Activity,
  GitCompare, AlertCircle, Clock, User,
} from 'lucide-react';

const TYPE_CONFIG = {
  decision:     { icon: BrainCircuit,  color: 'text-violet-600',  bg: 'bg-violet-50',  label: '决策' },
  conversation: { icon: MessageSquare, color: 'text-blue-600',    bg: 'bg-blue-50',    label: '对话' },
  reasoning:    { icon: Lightbulb,     color: 'text-amber-600',   bg: 'bg-amber-50',   label: '推理' },
  execution:    { icon: Activity,      color: 'text-emerald-600', bg: 'bg-emerald-50', label: '执行' },
  revision:     { icon: GitCompare,    color: 'text-orange-600',  bg: 'bg-orange-50',  label: '修订' },
  event:        { icon: AlertCircle,   color: 'text-rose-600',    bg: 'bg-rose-50',    label: '事件' },
};

export default function MemoryItem({ item, index = 0 }) {
  const cfg = TYPE_CONFIG[item.type] || TYPE_CONFIG.event;
  const Icon = cfg.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03, duration: 0.2 }}
      className="bg-white rounded-xl border border-hairline p-4 hover:shadow-sm transition-shadow"
    >
      <div className="flex items-start gap-3">
        {/* Type badge */}
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${cfg.bg}`}>
          <Icon size={15} className={cfg.color} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.color}`}>
              {cfg.label}
            </span>
            {item.actor && (
              <span className="flex items-center gap-1 text-[11px] text-ink-faint">
                <User size={10} />
                {item.actor}
              </span>
            )}
          </div>

          {/* Content */}
          <p className="text-sm text-ink leading-relaxed">{item.content}</p>

          {/* Metadata */}
          {item.metadata && Object.keys(item.metadata).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(item.metadata).map(([key, val]) => (
                val !== null && val !== undefined && val !== '' && (
                  <span
                    key={key}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-gray-50 text-ink-faint border border-hairline"
                  >
                    {key.replace(/_/g, ' ')}: {String(val).slice(0, 40)}
                  </span>
                )
              ))}
            </div>
          )}

          {/* Timestamp */}
          {item.timestamp && (
            <div className="mt-2 flex items-center gap-1 text-[10px] text-ink-faint">
              <Clock size={10} />
              <span>{new Date(item.timestamp).toLocaleString('zh-CN')}</span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
