/**
 * MemoryTimeline.jsx — 时间线视图 (V3.1 Phase B)
 *
 * 按时间降序列出所有记忆条目，带时间轴装饰。
 */
import { motion } from 'framer-motion';
import { Clock } from 'lucide-react';
import MemoryItem from './MemoryItem';

export default function MemoryTimeline({ items = [] }) {
  if (!items.length) {
    return (
      <div className="bg-white rounded-xl border border-hairline p-8 text-center">
        <Clock size={24} className="mx-auto mb-2 text-ink-faint" />
        <p className="text-sm text-ink-faint">暂无记忆记录</p>
        <p className="text-xs text-ink-faint mt-1">任务执行过程中产生的记忆将显示在这里</p>
      </div>
    );
  }

  // Group by date
  const groups = {};
  for (const item of items) {
    const date = item.timestamp
      ? new Date(item.timestamp).toLocaleDateString('zh-CN')
      : '未知时间';
    if (!groups[date]) groups[date] = [];
    groups[date].push(item);
  }

  return (
    <div className="space-y-6">
      {Object.entries(groups).map(([date, dateItems]) => (
        <div key={date}>
          {/* Date header */}
          <div className="flex items-center gap-2 mb-3">
            <div className="h-[1px] flex-1 bg-gray-100" />
            <span className="text-[11px] font-medium text-ink-faint px-2">{date}</span>
            <div className="h-[1px] flex-1 bg-gray-100" />
          </div>

          {/* Timeline entries */}
          <div className="space-y-2 ml-1">
            {/* Timeline line */}
            <div className="relative">
              <div className="absolute left-[15px] top-0 bottom-0 w-[2px] bg-gray-100" />
              <div className="space-y-2">
                {dateItems.map((item, idx) => (
                  <div key={item.id || idx} className="relative flex gap-3">
                    {/* Timeline dot */}
                    <div className="w-8 flex flex-col items-center flex-shrink-0 pt-4">
                      <div className="w-2 h-2 rounded-full bg-gray-300 ring-2 ring-white z-10" />
                    </div>
                    {/* Card */}
                    <div className="flex-1 min-w-0">
                      <MemoryItem item={item} index={idx} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
