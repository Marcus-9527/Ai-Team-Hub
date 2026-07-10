/**
 * MemoryPanel.jsx — Memory Workspace 主面板 (V3.1 Phase B)
 *
 * 展示任务关联的 4 级记忆：
 *   Global · Workspace · Channel · Task
 *
 * 类型标签过滤器：
 *   全部 · 决策 · 对话 · 推理 · 执行 · 事件
 *
 * 使用 TaskContext 的 selectedTaskId。
 * 订阅 taskEventBus 的 memory_updated 事件实时刷新。
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Globe, Layers, Hash, ListTodo, RefreshCw,
  Loader2, Filter, Search,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import MemoryTimeline from './MemoryTimeline';
import MemoryItem from './MemoryItem';

// ── Level tabs ──
const LEVELS = [
  { key: 'global',    label: '全局',    icon: Globe,    desc: '全系统共享记忆' },
  { key: 'workspace', label: '工作区',  icon: Layers,   desc: '当前工作区上下文' },
  { key: 'channel',   label: '频道',    icon: Hash,     desc: '频道对话记录' },
  { key: 'task',      label: '任务',    icon: ListTodo, desc: '任务执行记忆' },
];

const TYPE_FILTERS = [
  { key: '',       label: '全部' },
  { key: 'decision',     label: '决策' },
  { key: 'conversation', label: '对话' },
  { key: 'reasoning',    label: '推理' },
  { key: 'execution',    label: '执行' },
  { key: 'event',        label: '事件' },
];

export default function MemoryPanel({ taskId }) {
  const [memory, setMemory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeLevel, setActiveLevel] = useState('task');
  const [typeFilter, setTypeFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // ── Fetch memory ──
  const loadMemory = useCallback(async () => {
    if (!taskId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await taskApi.getTaskMemory(taskId);
      setMemory(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { loadMemory(); }, [loadMemory]);

  // ── SSE real-time ──
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if ((type === 'memory_updated' || type === 'execution_completed' || type === 'step_completed') && task_id === taskId) {
        loadMemory();
      }
    });
    return unsub;
  }, [taskId, loadMemory]);

  // ── Filtered items ──
  const currentItems = useMemo(() => {
    if (!memory) return [];
    // Map backend global_ to global
    const levelMap = {
      global: memory.global_ || memory.global || [],
      workspace: memory.workspace || [],
      channel: memory.channel || [],
      task: memory.task || [],
    };
    let items = levelMap[activeLevel] || [];

    // Type filter
    if (typeFilter) {
      items = items.filter(i => i.type === typeFilter);
    }

    // Search
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      items = items.filter(i =>
        i.content?.toLowerCase().includes(q) ||
        i.actor?.toLowerCase().includes(q)
      );
    }

    return items;
  }, [memory, activeLevel, typeFilter, searchQuery]);

  // ── Loading / Error ──
  if (loading && !memory) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
          <span>记忆加载失败: {error}</span>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Level tabs */}
      <div className="flex gap-1 mb-4">
        {LEVELS.map(level => {
          const Icon = level.icon;
          const isActive = activeLevel === level.key;
          return (
            <button
              key={level.key}
              onClick={() => setActiveLevel(level.key)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all ${
                isActive
                  ? 'bg-primary/10 text-primary shadow-sm'
                  : 'text-ink-mute hover:bg-gray-50 hover:text-ink'
              }`}
              title={level.desc}
            >
              <Icon size={13} />
              {level.label}
            </button>
          );
        })}
      </div>

      {/* Search + Refresh */}
      <div className="flex items-center gap-2 mb-4">
        <div className="flex-1 relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="搜索记忆..."
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-hairline rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary/30"
          />
        </div>
        <button
          onClick={loadMemory}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-ink-mute border border-hairline hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {/* Type filter chips */}
      <div className="flex flex-wrap gap-1 mb-4">
        <Filter size={12} className="text-ink-faint mr-1 self-center" />
        {TYPE_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setTypeFilter(f.key)}
            className={`text-[10px] px-2 py-1 rounded-full font-medium transition-all ${
              typeFilter === f.key
                ? 'bg-primary text-white'
                : 'bg-gray-100 text-ink-mute hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
        {memory && (
          <span className="text-[10px] text-ink-faint self-center ml-auto">
            {currentItems.length} 条
          </span>
        )}
      </div>

      {/* Items */}
      <AnimatePresence mode="wait">
        <motion.div
          key={`${activeLevel}-${typeFilter}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <MemoryTimeline items={currentItems} />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
