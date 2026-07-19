import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Target, Loader2, PlayCircle, MessageSquare,
} from 'lucide-react';
import * as taskApi from '../services/api/task';
import { useTranslation } from '../i18n';
import TaskDetailView from './Task/TaskDetailView';

/* ── Goal input (initial state) ── */
function GoalInput({ onSubmit, loading, onOpenTopic }) {
  const t = useTranslation();
  const [goal, setGoal] = useState('');

  const handleSubmit = () => {
    if (!goal.trim() || loading) return;
    onSubmit(goal.trim());
    setGoal('');
  };

  return (
    <div className="flex-1 flex items-center justify-center bg-canvas">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-lg mx-auto px-6"
      >
        <div className="text-center mb-6">
          <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
            <Target size={24} className="text-primary" />
          </div>
          <h2 className="text-lg font-bold text-ink mb-1">{t('task.goal.title')}</h2>
          <p className="text-xs text-ink-faint">{t('task.goal.subtitle')}</p>
        </div>
        <div className="relative">
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder={t('task.goal.placeholder')}
            className="w-full px-4 py-3.5 rounded-2xl border border-hairline text-sm text-ink bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-none"
            rows={4}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
            autoFocus
          />
          <button
            onClick={handleSubmit}
            disabled={!goal.trim() || loading}
            className="absolute bottom-3 right-3 flex items-center gap-1.5 px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold disabled:opacity-40 transition-all hover:bg-primary-press"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
            {t('task.goal.start')}
          </button>
        </div>
        <button
          onClick={onOpenTopic}
          className="w-full mt-3 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl border border-hairline text-xs font-medium text-ink-mute hover:bg-surface-hover transition-all"
        >
          <MessageSquare size={14} /> 或开始一个对话话题（群聊模式）
        </button>
      </motion.div>
    </div>
  );
}

/* ── TaskModeView: main export ── */
export default function TaskModeView({ onNavigate }) {
  const t = useTranslation();
  const [task, setTask] = useState(null);
  const [creating, setCreating] = useState(false);
  const loadTask = useCallback(async (taskId) => {
    if (!taskId) return;
    try {
      const data = await taskApi.getTask(taskId);
      setTask(data);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const handleSubmitGoal = async (goal) => {
    setCreating(true);
    try {
      const newTask = await taskApi.createTask({
        title: goal,
        description: goal,
        priority: 2,
      });
      setTask(newTask);
      // Backend auto-runs plan+execute in background on createTask.
      // Do NOT call /plan or /execute here — that double-triggers the
      // orchestrator and spawns duplicate steps that hang forever.
      loadTask(newTask.id);
    } catch (e) {
      alert(t('task.create_failed_alert') + e.message);
    }
    setCreating(false);
  };

  return (
    <div className="flex-1 flex flex-col h-full">
      {!task ? (
        <GoalInput onSubmit={handleSubmitGoal} loading={creating} onOpenTopic={() => onNavigate?.('new-topic')} />
      ) : (
        <TaskDetailView taskId={task.id} onBack={() => setTask(null)} />
      )}
    </div>
  );
}
