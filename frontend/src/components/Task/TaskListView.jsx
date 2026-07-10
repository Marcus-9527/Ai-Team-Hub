/**
 * TaskListView.jsx — 任务列表视图
 *
 * 展示所有任务，支持按状态筛选、创建新任务。
 * 与 TaskDetailView 配合使用。
 */
import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  ListTodo, Plus, ArrowLeft, Loader2,
  CheckCircle2, XCircle, PauseCircle, PlayCircle,
  Clock, AlertTriangle, Trash2,
} from 'lucide-react';
import { useTaskContext } from '../../services/taskContext';
import * as taskApi from '../../services/api/task';
import { useTranslation } from '../../i18n';
import TaskDetailView from './TaskDetailView';
import ConfirmDialog from '../ConfirmDialog';

// ── Status config ──
const STATUS_CONFIG = {
  CREATED:    { label: '待处理',  color: 'text-gray-500',  bg: 'bg-gray-100', icon: Clock },
  PLANNING:   { label: '规划中',  color: 'text-blue-600',  bg: 'bg-blue-100', icon: Loader2 },
  EXECUTING:  { label: '执行中',  color: 'text-indigo-600', bg: 'bg-indigo-100', icon: PlayCircle },
  PAUSED:     { label: '已暂停',  color: 'text-amber-600', bg: 'bg-amber-100', icon: PauseCircle },
  COMPLETED:  { label: '已完成',  color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle2 },
  FAILED:     { label: '失败',    color: 'text-red-600',   bg: 'bg-red-100',   icon: XCircle },
  CANCELLED:  { label: '已取消',  color: 'text-gray-500',  bg: 'bg-gray-100',  icon: XCircle },
};
const FILTER_OPTIONS = [
  { value: '',     label: '全部' },
  { value: 'CREATED',   label: '待处理' },
  { value: 'EXECUTING', label: '执行中' },
  { value: 'COMPLETED', label: '已完成' },
  { value: 'FAILED',    label: '失败' },
];

export default function TaskListView({ onBack }) {
  const t = useTranslation();
  const { tasks, loading, error, activeFilter, setFilter, selectTask, selectedTaskId, refreshTasks } = useTaskContext();
  const [showCreate, setShowCreate] = useState(false);
  const [createData, setCreateData] = useState({ title: '', description: '', priority: 2 });
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState(null);

  // ── Create task ──
  const handleCreate = useCallback(async () => {
    if (!createData.title.trim()) return;
    setCreating(true);
    try {
      const task = await taskApi.createTask({
        title: createData.title.trim(),
        description: createData.description.trim(),
        priority: createData.priority,
      });
      setShowCreate(false);
      setCreateData({ title: '', description: '', priority: 2 });
      refreshTasks();
      selectTask(task.id);
    } catch (e) {
      alert('创建任务失败: ' + e.message);
    } finally {
      setCreating(false);
    }
  }, [createData, refreshTasks, selectTask]);

  // ── Delete task ──
  const handleDelete = (task, e) => {
    e.stopPropagation();
    setConfirm({
      title: '删除任务',
      message: `确定要删除「${task.title}」吗？所有步骤和记录将被清除。`,
      confirmText: '删除',
      onConfirm: async () => {
        try {
          await taskApi.deleteTask(task.id);
          refreshTasks();
        } catch (e) {
          alert('删除失败: ' + e.message);
        }
      },
    });
  };

  // If a task is selected, show detail view
  if (selectedTaskId) {
    return <TaskDetailView taskId={selectedTaskId} onBack={() => selectTask(null)} />;
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-canvas">
      {/* Header */}
      <div className="h-14 flex items-center gap-3 px-5 border-b border-hairline bg-white flex-shrink-0">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint hover:text-ink transition-all">
          <ArrowLeft size={18} />
        </button>
        <ListTodo size={18} className="text-ink-faint" />
        <h2 className="font-bold text-[15px] text-ink">{t('task.list_title') || '任务列表'}</h2>
        <span className="text-xs text-ink-faint">({tasks.length})</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary-press transition-all"
          >
            <Plus size={14} />
            <span>{t('task.create_btn') || '新任务'}</span>
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-1.5 px-5 py-2.5 border-b border-hairline bg-white flex-shrink-0 overflow-x-auto">
        {FILTER_OPTIONS.map(f => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all whitespace-nowrap ${
              activeFilter === f.value
                ? 'bg-primary text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        {loading && tasks.length === 0 && (
          <div className="flex items-center justify-center h-40">
            <Loader2 size={24} className="animate-spin text-ink-faint" />
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 p-4 mb-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        {!loading && tasks.length === 0 && (
          <div className="flex flex-col items-center justify-center h-60 text-ink-faint">
            <ListTodo size={48} className="mb-3 opacity-30" />
            <p className="text-sm">{t('task.no_tasks') || '暂无任务'}</p>
            <button
              onClick={() => setShowCreate(true)}
              className="mt-3 px-4 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary-press transition-all"
            >
              <Plus size={14} className="inline mr-1" />
              {t('task.create_first') || '创建第一个任务'}
            </button>
          </div>
        )}

        {/* Task cards */}
        <div className="space-y-3">
          {tasks.map(task => {
            const sc = STATUS_CONFIG[task.status] || STATUS_CONFIG.CREATED;
            const StatusIcon = sc.icon;
            const progressPct = task.steps_count > 0
              ? Math.round(((task.steps_count - (task.status === 'COMPLETED' ? 0 : 1)) / task.steps_count) * 100)
              : 0;

            return (
              <motion.div
                key={task.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                onClick={() => selectTask(task.id)}
                className="group bg-white rounded-xl border border-hairline p-4 cursor-pointer hover:border-hairline-strong hover:shadow-sm transition-all"
              >
                <div className="flex items-start gap-3">
                  {/* Status icon */}
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${sc.bg}`}>
                    <StatusIcon size={16} className={sc.color} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-sm text-ink truncate">{task.title}</h3>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${sc.bg} ${sc.color}`}>
                        {sc.label}
                      </span>
                    </div>
                    {task.description && (
                      <p className="text-xs text-ink-mute mt-1 line-clamp-2">{task.description}</p>
                    )}
                    <div className="flex items-center gap-3 mt-2 text-[10px] text-ink-faint">
                      <span>{task.created_by}</span>
                      {task.created_at && (
                        <span>{new Date(task.created_at).toLocaleString('zh-CN')}</span>
                      )}
                      {task.steps_count > 0 && (
                        <span>{task.steps_count} 个步骤</span>
                      )}
                    </div>
                    {/* Progress bar */}
                    {task.status === 'EXECUTING' && task.steps_count > 0 && (
                      <div className="mt-2.5 w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${progressPct}%` }}
                          className="h-full bg-indigo-500 rounded-full"
                        />
                      </div>
                    )}
                  </div>
                  {/* Delete button */}
                  <button
                    onClick={(e) => handleDelete(task, e)}
                    className="p-1.5 rounded-lg opacity-0 group-hover:opacity-60 hover:opacity-100 hover:bg-red-50 transition-all flex-shrink-0"
                  >
                    <Trash2 size={14} className="text-ink-faint hover:text-semantic-error" />
                  </button>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Create Task Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setShowCreate(false)}>
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[420px] max-w-[90vw] p-6"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-base font-bold text-ink mb-1">{t('task.create_title') || '创建任务'}</h3>
            <p className="text-xs text-ink-mute mb-4">{t('task.create_desc') || '创建一个多步骤执行任务'}</p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.title') || '标题'}</label>
                <input
                  value={createData.title}
                  onChange={e => setCreateData(d => ({ ...d, title: e.target.value }))}
                  placeholder="输入任务标题..."
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.description') || '描述'}</label>
                <textarea
                  value={createData.description}
                  onChange={e => setCreateData(d => ({ ...d, description: e.target.value }))}
                  placeholder="描述任务目标..."
                  rows={3}
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-none"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.priority') || '优先级'}</label>
                <select
                  value={createData.priority}
                  onChange={e => setCreateData(d => ({ ...d, priority: Number(e.target.value) }))}
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                >
                  <option value={1}>高</option>
                  <option value={2}>中</option>
                  <option value={3}>低</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-ink-mute hover:bg-gray-100 transition-all"
              >
                {t('task.cancel') || '取消'}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !createData.title.trim()}
                className="px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold hover:bg-primary-press disabled:opacity-50 transition-all"
              >
                {creating ? '创建中...' : (t('task.create_btn') || '创建')}
              </button>
            </div>
          </motion.div>
        </div>
      )}

      <ConfirmDialog state={[confirm, setConfirm]} />
    </div>
  );
}
