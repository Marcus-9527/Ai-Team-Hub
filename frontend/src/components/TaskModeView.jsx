import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Target, Loader2, PlayCircle,
} from 'lucide-react';
import * as taskApi from '../services/api/task';
import { useTranslation } from '../i18n';
import TaskDetailView from './Task/TaskDetailView';
import TaskProgressPanel from './Task/TaskProgressPanel';

/* ── Goal input (initial state) ── */
function GoalInput({ onSubmit, loading }) {
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
      </motion.div>
    </div>
  );
}

/* ── TaskModeView: main export ── */
export default function TaskModeView() {
  const t = useTranslation();
  const [task, setTask] = useState(null);
  const [steps, setSteps] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const loadTask = useCallback(async (taskId) => {
    if (!taskId) return;
    setLoading(true);
    try {
      const data = await taskApi.getTask(taskId);
      setTask(data);
      const prog = await taskApi.getTaskProgress(taskId).catch(() => null);
      setSteps(prog?.steps || data?.steps || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
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
      setSteps([]);
      // Backend auto-runs plan+execute in background on createTask.
      // Do NOT call /plan or /execute here — that double-triggers the
      // orchestrator and spawns duplicate steps that hang forever.
      loadTask(newTask.id);
    } catch (e) {
      alert(t('task.create_failed_alert') + e.message);
    }
    setCreating(false);
  };

  // Advanced mode fallback
  if (showAdvanced && task) {
    return (
      <div className="flex-1 flex flex-col h-full">
        <div className="h-10 flex items-center px-4 border-b border-hairline bg-white flex-shrink-0">
          <button
            onClick={() => setShowAdvanced(false)}
            className="flex items-center gap-1.5 text-xs text-ink-mute hover:text-ink transition-all"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
            {t('task.back_simple')}
          </button>
          <span className="ml-auto text-[10px] text-ink-faint">{t('task.advanced_mode')}</span>
        </div>
        <div className="flex-1 overflow-hidden">
          <TaskDetailView taskId={task.id} onBack={() => setShowAdvanced(false)} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full">
      {!task ? (
        <GoalInput onSubmit={handleSubmitGoal} loading={creating} />
      ) : (
        <TaskProgressPanel
          task={task}
          steps={steps}
          loading={loading}
          onBack={() => setTask(null)}
          onRefresh={() => loadTask(task.id)}
          onViewAdvanced={() => setShowAdvanced(true)}
        />
      )}
    </div>
  );
}
