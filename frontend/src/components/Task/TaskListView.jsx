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

// ── Status config (label via i18n) ──
const STATUS_COLOR = {
  CREATED:    { color: 'text-gray-500',  bg: 'bg-gray-100', icon: Clock },
  PLANNING:   { color: 'text-blue-600',  bg: 'bg-blue-100', icon: Loader2 },
  EXECUTING:  { color: 'text-indigo-600', bg: 'bg-indigo-100', icon: PlayCircle },
  PAUSED:     { color: 'text-amber-600', bg: 'bg-amber-100', icon: PauseCircle },
  COMPLETED:  { color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle2 },
  FAILED:     { color: 'text-red-600',   bg: 'bg-red-100',   icon: XCircle },
  CANCELLED:  { color: 'text-gray-500',  bg: 'bg-gray-100',  icon: XCircle },
};
const FILTER_OPTIONS = [
  { value: '',          key: 'task.filter.all' },
  { value: 'CREATED',   key: 'task.filter.created' },
  { value: 'EXECUTING', key: 'task.filter.executing' },
  { value: 'COMPLETED', key: 'task.filter.completed' },
  { value: 'FAILED',    key: 'task.filter.failed' },
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
      title: t('team.delete_title'),
      message: t('team.delete_msg', task.title),
      confirmText: t('team.remove'),
      onConfirm: async () => {
        try {
          await taskApi.deleteTask(task.id);
          refreshTasks();
        } catch (e) {
          alert(t('task.delete_failed') + e.message);
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
        <h2 className="font-bold text-[15px] text-ink">{t('task.list_title')}</h2>
        <span className="text-xs text-ink-faint">({tasks.length})</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary-press transition-all"
          >
            <Plus size={14} />
            <span>{t('task.create_btn')}</span>
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
            {t(f.key)}
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
            <p className="text-sm">{t('task.no_tasks')}</p>
            <button
              onClick={() => setShowCreate(true)}
              className="mt-3 px-4 py-2 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary-press transition-all"
            >
              <Plus size={14} className="inline mr-1" />
              {t('task.create_first')}
            </button>
          </div>
        )}

        {/* Task cards */}
        <div className="space-y-3">
          {tasks.map(task => {
            const sc = STATUS_COLOR[task.status] || STATUS_COLOR.CREATED;
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
                        {t('task.status.' + task.status)}
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
                        <span>{t('task.steps_count', task.steps_count)}</span>
                      )}
                    </div>
                    {/* Delivery badges */}
                    {(task.review_status !== 'pending' || (task.files_changed || []).length > 0 || task.test_result) && (
                      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                        {task.review_status !== 'pending' && (
                          <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium ${
                            task.review_status === 'approved' ? 'bg-green-100 text-green-600' :
                            task.review_status === 'rejected' ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-500'
                          }`}>
                            {task.review_status === 'approved' ? <CheckCircle2 size={9} /> :
                             task.review_status === 'rejected' ? <XCircle size={9} /> : <Clock size={9} />}
                            {t('task.delivery.' + (task.review_status || 'pending'))}
                          </span>
                        )}
                        {(task.files_changed || []).length > 0 && (
                          <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-600 text-[9px] font-medium">
                            📄 {(task.files_changed || []).length} files
                          </span>
                        )}
                        {task.test_result && (
                          <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${
                            task.test_result.includes('passed') || task.test_result.includes('PASSED')
                              ? 'bg-green-100 text-green-600'
                              : 'bg-amber-100 text-amber-600'
                          }`}>
                            🧪 {task.test_result.length > 20 ? task.test_result.slice(0, 20) + '...' : task.test_result}
                          </span>
                        )}
                      </div>
                    )}
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
            <h3 className="text-base font-bold text-ink mb-1">{t('task.create_title')}</h3>
            <p className="text-xs text-ink-mute mb-4">{t('task.create_desc')}</p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.title')}</label>
                <input
                  value={createData.title}
                  onChange={e => setCreateData(d => ({ ...d, title: e.target.value }))}
                  placeholder={t('task.title_ph')}
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.description')}</label>
                <textarea
                  value={createData.description}
                  onChange={e => setCreateData(d => ({ ...d, description: e.target.value }))}
                  placeholder={t('task.desc_ph')}
                  rows={3}
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-none"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-ink-mute block mb-1">{t('task.priority')}</label>
                <select
                  value={createData.priority}
                  onChange={e => setCreateData(d => ({ ...d, priority: Number(e.target.value) }))}
                  className="w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                >
                  <option value={1}>{t('task.priority.high')}</option>
                  <option value={2}>{t('task.priority.medium')}</option>
                  <option value={3}>{t('task.priority.low')}</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-ink-mute hover:bg-gray-100 transition-all"
              >
                {t('task.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !createData.title.trim()}
                className="px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold hover:bg-primary-press disabled:opacity-50 transition-all"
              >
                {creating ? t('task.creating') : t('task.create_btn')}
              </button>
            </div>
          </motion.div>
        </div>
      )}

      <ConfirmDialog state={[confirm, setConfirm]} />
    </div>
  );
}
