/**
 * TaskDetailView.jsx — Phase 27 Product Layer
 *
 * Tab 结构：
 *   [Overview] [Run] [Activity] [Delivery]
 *
 * Overview:    任务元信息 + TechLead 决策 + Delivery 摘要
 * Run:         步骤时间线 + 执行记录 + 质量评分 + DAG 可视化
 * Activity:    ActivityFeed + Memory + TeamBoard
 * Delivery:    Review 状态 + Git Commit + 文件变更 + 测试结果
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Loader2, PlayCircle, PauseCircle,
  XCircle, CheckCircle2, Clock, AlertTriangle,
  ListTodo, FileText, User, Activity,
  RefreshCw, BarChart3, ThumbsUp, BrainCircuit,
  GitBranch, Network,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { useTranslation } from '../../i18n';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import ExecutionTimeline from './ExecutionTimeline';
import ExecutionResultCard from './ExecutionResultCard';
import PlanView from './PlanView';
import ApprovalPanel from './ApprovalPanel';
import TaskAnalytics from './TaskAnalytics';
import MemoryPanel from '../Memory/MemoryPanel';
import AgentBoard from '../Workspace/AgentBoard';
import AgentActivityFeed from '../Workspace/AgentActivityFeed';

// ── Tab config – Phase 27: Overview / Run / Activity / Delivery ──
const TABS = [
  { key: 'overview',  i18n: 'task.tab.overview',   icon: ListTodo },
  { key: 'run',       i18n: 'task.tab.run',         icon: Activity },
  { key: 'activity',  i18n: 'task.tab.activity',    icon: User },
  { key: 'delivery',  i18n: 'task.tab.delivery',    icon: CheckCircle2 },
];

// ── Status config ──
const STATUS_COLOR = {
  CREATED:    { color: 'text-gray-500',  bg: 'bg-gray-100' },
  PLANNING:   { color: 'text-blue-600',  bg: 'bg-blue-100' },
  EXECUTING:  { color: 'text-indigo-600', bg: 'bg-indigo-100' },
  PAUSED:     { color: 'text-amber-600', bg: 'bg-amber-100' },
  COMPLETED:  { color: 'text-green-600', bg: 'bg-green-100' },
  FAILED:     { color: 'text-red-600',   bg: 'bg-red-100' },
  CANCELLED:  { color: 'text-gray-500',  bg: 'bg-gray-100' },
};

const STEP_STATUS_COLOR = {
  PENDING:    { color: 'text-gray-400',  icon: Clock },
  SCHEDULED:  { color: 'text-blue-500',  icon: Clock },
  RUNNING:    { color: 'text-indigo-500', icon: Loader2 },
  COMPLETED:  { color: 'text-green-500', icon: CheckCircle2 },
  FAILED:     { color: 'text-red-500',   icon: XCircle },
  SKIPPED:    { color: 'text-gray-400',  icon: XCircle },
};

export default function TaskDetailView({ taskId, onBack }) {
  const t = useTranslation();
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [progress, setProgress] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [dag, setDag] = useState(null);

  // ── Fetch task detail ──
  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await taskApi.getTask(taskId);
      setTask(data);
      try {
        const [prog, appr] = await Promise.all([
          taskApi.getTaskProgress(taskId).catch(() => null),
          taskApi.listApprovals(taskId).catch(() => []),
        ]);
        if (prog) setProgress(prog);
        if (appr) setApprovals(appr);
      } catch {}
      // Load DAG for Run tab
      try {
        const dagData = await taskApi.getTaskDag?.(taskId);
        if (dagData) setDag(dagData);
      } catch {}
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { loadTask(); }, [loadTask]);

  // ── SSE real-time events ──
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (task_id === taskId) {
        loadTask();
      }
    });
    return unsub;
  }, [taskId, loadTask]);

  // ── Action handlers ──
  const handleAction = useCallback(async (action, handler) => {
    setActionLoading(action);
    try {
      const updated = await handler(taskId);
      if (updated) setTask(updated);
      await loadTask();
    } catch (e) {
      alert(`${t('task.action_failed')} ${action}: ` + e.message);
    } finally {
      setActionLoading(null);
    }
  }, [taskId, loadTask]);

  // ── Progress ──
  const stepList = progress?.steps || task?.steps || [];
  const totalSteps = progress?.total_steps || stepList.length;
  const completedSteps = progress?.completed_steps || stepList.filter(s => s.status === 'COMPLETED').length;
  const progressPct = totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;

  // ── Loading / Error ──
  if (loading && !task) {
    return (
      <div className="flex-1 flex flex-col h-full bg-canvas">
        <div className="h-14 flex items-center px-5 border-b border-hairline bg-white">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint"><ArrowLeft size={18} /></button>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-ink-faint" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col h-full bg-canvas">
        <div className="h-14 flex items-center px-5 border-b border-hairline bg-white">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint"><ArrowLeft size={18} /></button>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="flex items-center gap-2 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        </div>
      </div>
    );
  }

  if (!task) return null;

  const sc = STATUS_COLOR[task.status] || STATUS_COLOR.CREATED;

  // ── Available actions per status ──
  const AVAILABLE_ACTIONS = {
    CREATED: [
      { key: 'plan', label: t('task.action.plan'), icon: PlayCircle, handler: taskApi.planTask, color: 'bg-blue-600 hover:bg-blue-700' },
    ],
    PLANNING: [
      { key: 'execute', label: t('task.action.execute'), icon: PlayCircle, handler: taskApi.executeTask, color: 'bg-indigo-600 hover:bg-indigo-700' },
      { key: 'fail',    label: t('task.action.fail'), icon: XCircle,    handler: taskApi.failTask,   color: 'bg-red-500 hover:bg-red-600' },
    ],
    EXECUTING: [
      { key: 'pause',   label: t('task.action.pause'), icon: PauseCircle, handler: taskApi.pauseTask,  color: 'bg-amber-500 hover:bg-amber-600' },
      { key: 'complete', label: t('task.action.complete'), icon: CheckCircle2, handler: taskApi.completeTask, color: 'bg-green-600 hover:bg-green-700' },
      { key: 'fail',    label: t('task.action.fail'), icon: XCircle,     handler: taskApi.failTask,   color: 'bg-red-500 hover:bg-red-600' },
    ],
    PAUSED: [
      { key: 'resume',  label: t('task.action.resume'), icon: PlayCircle,  handler: taskApi.resumeTask,  color: 'bg-indigo-600 hover:bg-indigo-700' },
      { key: 'cancel',  label: t('task.action.cancel_task'), icon: XCircle, handler: taskApi.cancelTask, color: 'bg-gray-500 hover:bg-gray-600' },
    ],
    COMPLETED: [],
    FAILED: [
      { key: 'plan',    label: t('task.action.replan'), icon: RefreshCw, handler: taskApi.planTask, color: 'bg-blue-600 hover:bg-blue-700' },
    ],
    CANCELLED: [],
  };

  const actions = AVAILABLE_ACTIONS[task.status] || [];

  // ── DAG Visualizer ──
  const DAGVisualizer = ({ dag }) => {
    if (!dag?.dag || !dag?.nodes?.length) return null;
    const nodes = dag.nodes;
    return (
      <div className="bg-white rounded-xl border border-hairline p-4 mt-4">
        <h3 className="text-sm font-bold text-ink mb-3 flex items-center gap-2">
          <Network size={15} className="text-ink-faint" />
          {t('task.dag_plan')}
        </h3>
        <div className="flex flex-wrap gap-2">
          {nodes.map((n, i) => (
            <div
              key={n.id}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border ${
                n.status === 'COMPLETED' ? 'bg-green-50 border-green-200 text-green-700' :
                n.status === 'FAILED' ? 'bg-red-50 border-red-200 text-red-700' :
                n.status === 'RUNNING' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' :
                'bg-gray-50 border-gray-200 text-gray-600'
              }`}
            >
              <span className="font-mono text-[10px] opacity-60">#{i + 1}</span>
              <span className="truncate max-w-[120px]">{n.description || n.teammate}</span>
              {n.deps?.length > 0 && (
                <span className="text-[10px] opacity-50 ml-1">←{n.deps.length}</span>
              )}
            </div>
          ))}
        </div>
        {dag.dag.name && (
          <p className="text-[11px] text-ink-faint mt-2">{dag.dag.name}</p>
        )}
      </div>
    );
  };

  // ═══════════════════════════════════════════
  // Tab: Overview
  // ═══════════════════════════════════════════
  const OverviewTab = () => (
    <>
      {/* Task Info Card */}
      <div className="bg-white rounded-xl border border-hairline p-5">
        {actions.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {actions.map(a => (
              <button
                key={a.key}
                onClick={() => handleAction(a.key, a.handler)}
                disabled={actionLoading === a.key}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-xs font-semibold transition-all disabled:opacity-50 ${a.color}`}
              >
                {actionLoading === a.key ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <a.icon size={13} />
                )}
                {a.label}
              </button>
            ))}
            <button
              onClick={() => handleAction('cancel', taskApi.cancelTask)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-ink-mute border border-hairline hover:bg-gray-50 transition-all"
            >
              <XCircle size={13} />
              {t('task.action.cancel')}
            </button>
          </div>
        )}

        {task.description && (
          <div className="mb-4">
            <h4 className="text-xs font-semibold text-ink-mute mb-1">{t('task.description')}</h4>
            <p className="text-sm text-ink leading-relaxed">{task.description}</p>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-ink-faint block">{t('task.meta.created_by')}</span>
            <span className="text-ink font-medium">{task.created_by}</span>
          </div>
          <div>
            <span className="text-ink-faint block">{t('task.meta.priority')}</span>
            <span className="text-ink font-medium">
              {task.priority === 1 ? t('task.priority.high') : task.priority === 2 ? t('task.priority.medium') : t('task.priority.low')}
            </span>
          </div>
          {task.created_at && (
            <div>
              <span className="text-ink-faint block">{t('task.meta.created_at')}</span>
              <span className="text-ink">{new Date(task.created_at).toLocaleString('zh-CN')}</span>
            </div>
          )}
          {task.completed_at && (
            <div>
              <span className="text-ink-faint block">{t('task.meta.completed_at')}</span>
              <span className="text-ink">{new Date(task.completed_at).toLocaleString('zh-CN')}</span>
            </div>
          )}
        </div>

        {/* Progress bar */}
        {totalSteps > 0 && (
          <div className="mt-4 pt-4 border-t border-hairline">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-ink-mute">{t('task.progress_label')}</span>
              <span className="text-xs text-ink-faint">
                {t('task.progress_meta', completedSteps, totalSteps, progressPct)}
              </span>
            </div>
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${progressPct}%` }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
                className={`h-full rounded-full ${
                  task.status === 'FAILED' || task.status === 'CANCELLED'
                    ? 'bg-red-400'
                    : task.status === 'COMPLETED'
                    ? 'bg-green-500'
                    : 'bg-indigo-500'
                }`}
              />
            </div>
          </div>
        )}
      </div>

      {/* TechLead Decision */}
      {task.techlead_decision && (
        <div className="mt-4 bg-white rounded-xl border border-hairline p-5">
          <h3 className="text-sm font-bold text-ink mb-3 flex items-center gap-2">
            <BrainCircuit size={15} className="text-ink-faint" />
            {'🧠 ' + t('task.techlead')}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs mb-3">
            <div>
              <span className="text-ink-faint block mb-1">{t('task.techlead_risk')}</span>
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${
                task.techlead_decision.risk_level === 'HIGH' ? 'bg-red-100 text-red-600' :
                task.techlead_decision.risk_level === 'MEDIUM' ? 'bg-amber-100 text-amber-600' :
                'bg-green-100 text-green-600'
              }`}>
                {task.techlead_decision.risk_level || 'N/A'}
              </span>
            </div>
            <div>
              <span className="text-ink-faint block mb-1">{t('task.techlead_confidence')}</span>
              <span className="font-semibold text-ink">{((task.techlead_decision.confidence || 0) * 100).toFixed(0)}%</span>
            </div>
            <div>
              <span className="text-ink-faint block mb-1">{t('task.techlead_steps')}</span>
              <span className="font-semibold text-ink">{(task.techlead_decision.teammate_recommendations || []).length} steps</span>
            </div>
          </div>
          {task.techlead_decision.analysis && (
            <div className="mb-3 p-3 rounded-lg bg-gray-50 border border-hairline">
              <p className="text-xs text-ink-mute leading-relaxed">{task.techlead_decision.analysis}</p>
            </div>
          )}
        </div>
      )}

      {/* Analytics Summary */}
      <div className="mt-4">
        <TaskAnalytics taskId={taskId} />
      </div>
    </>
  );

  // ═══════════════════════════════════════════
  // Tab: Run — steps + execution + quality + DAG
  // ═══════════════════════════════════════════
  const RunTab = () => (
    <>
      {/* Steps Timeline */}
      <div className="bg-white rounded-xl border border-hairline p-5">
        <h3 className="text-sm font-bold text-ink mb-3 flex items-center gap-2">
          <Activity size={16} className="text-ink-faint" />
          {t('task.steps_label')}
          <span className="text-xs text-ink-faint font-normal">({stepList.length})</span>
        </h3>

        {stepList.length === 0 && (
          <div className="py-8 text-center">
            <p className="text-sm text-ink-faint">{t('task.no_steps')}</p>
          </div>
        )}

        <div className="space-y-2">
          {stepList.map((step, idx) => {
            const ssc = STEP_STATUS_COLOR[step.status] || STEP_STATUS_COLOR.PENDING;
            const StepIcon = ssc.icon;
            const isRunning = step.status === 'RUNNING';

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className={`border ${
                  isRunning ? 'border-indigo-300 ring-1 ring-indigo-100' : 'border-hairline'
                } p-3 rounded-lg`}
              >
                <div className="flex items-center gap-3">
                  <div className={`flex-shrink-0 ${ssc.color}`}>
                    <StepIcon size={16} className={step.status === 'RUNNING' ? 'animate-spin' : ''} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-ink">{step.objective || `Step ${step.order}`}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${ssc.color.replace('text-', 'bg-').replace('gray-', 'gray-').replace('500', '100')} ${ssc.color}`}>
                        {step.status}
                      </span>
                    </div>
                    {step.teammate_id && (
                      <p className="text-[11px] text-ink-faint mt-0.5">{step.teammate_id}</p>
                    )}
                    {step.error && (
                      <p className="text-[11px] text-red-500 mt-0.5 truncate">{step.error}</p>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* DAG Visualization */}
      <DAGVisualizer dag={dag} />

      {/* Execution Timeline */}
      <div className="mt-4">
        <ExecutionTimeline taskId={taskId} />
      </div>

      {/* Approval Panel */}
      {approvals.length > 0 && (
        <div className="mt-4">
          <ApprovalPanel taskId={taskId} />
        </div>
      )}
    </>
  );

  // ═══════════════════════════════════════════
  // Tab: Activity — ActivityFeed + Memory + Team
  // ═══════════════════════════════════════════
  const ActivityTab = () => (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-hairline p-4">
        <AgentActivityFeed taskId={taskId} />
      </div>
      <AgentBoard taskId={taskId} />
      <MemoryPanel taskId={taskId} />
    </div>
  );

  // ═══════════════════════════════════════════
  // Tab: Delivery — review, commit, files, tests
  // ═══════════════════════════════════════════
  const DeliveryTab = () => (
    <div className="bg-white rounded-xl border border-hairline p-5">
      <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
        <CheckCircle2 size={15} className="text-ink-faint" />
        {t('task.delivery.title')}
      </h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        {/* Review status */}
        <div>
          <span className="text-ink-faint block mb-1">{t('task.delivery.review')}</span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${
            task.review_status === 'approved' ? 'bg-green-100 text-green-600' :
            task.review_status === 'rejected' ? 'bg-red-100 text-red-600' :
            'bg-gray-100 text-gray-500'
          }`}>
            {task.review_status === 'approved' ? <CheckCircle2 size={11} /> :
             task.review_status === 'rejected' ? <XCircle size={11} /> : <Clock size={11} />}
            {t('task.delivery.' + (task.review_status || 'pending'))}
          </span>
          {task.review_rounds > 1 && (
            <span className="ml-2 text-ink-faint">({t('task.delivery.rounds', task.review_rounds)})</span>
          )}
        </div>

        {/* Git commit */}
        {task.git_commit && (
          <div>
            <span className="text-ink-faint block mb-1">{t('task.delivery.commit')}</span>
            <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded font-mono">{task.git_commit.slice(0, 12)}</code>
          </div>
        )}

        {/* Files changed */}
        {(task.files_changed || []).length > 0 && (
          <div className="md:col-span-2">
            <span className="text-ink-faint block mb-1">{t('task.delivery.files')} ({(task.files_changed || []).length})</span>
            <div className="flex flex-wrap gap-1">
              {(task.files_changed || []).map((f, i) => (
                <code key={i} className="text-[11px] bg-gray-50 border border-hairline px-1.5 py-0.5 rounded font-mono">{f}</code>
              ))}
            </div>
          </div>
        )}

        {/* Commands run */}
        {(task.commands_run || []).length > 0 && (
          <div className="md:col-span-2">
            <span className="text-ink-faint block mb-1">{t('task.delivery.commands')}</span>
            <div className="bg-gray-50 rounded-lg p-2 space-y-1">
              {(task.commands_run || []).map((c, i) => (
                <code key={i} className="block text-[11px] font-mono text-ink-mute">$ {c}</code>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Test result */}
      {task.test_result && (
        <div className="mt-3 pt-3 border-t border-hairline">
          <span className="text-ink-faint block mb-1 text-xs font-semibold">{t('task.delivery.test_result')}</span>
          <pre className="bg-gray-50 rounded-lg p-2.5 text-xs text-ink-mute whitespace-pre-wrap break-words max-h-32 overflow-y-auto font-mono">
            {task.test_result.length > 500 ? task.test_result.slice(0, 500) + '...' : task.test_result}
          </pre>
        </div>
      )}

      {/* Review comments */}
      {task.review_comments && (
        <div className="mt-3 pt-3 border-t border-hairline">
          <span className="text-ink-faint block mb-1 text-xs font-semibold">{t('task.delivery.comments')}</span>
          <pre className="text-xs text-ink-mute whitespace-pre-wrap break-words leading-relaxed font-sans">
            {task.review_comments}
          </pre>
        </div>
      )}

      {/* Quality */}
      <div className="mt-4">
        <ExecutionResultCard taskId={taskId} />
      </div>
    </div>
  );

  // ── Render active tab ──
  const renderTabContent = () => {
    switch (activeTab) {
      case 'run':       return <RunTab />;
      case 'activity':  return <ActivityTab />;
      case 'delivery':  return <DeliveryTab />;
      default:          return <OverviewTab />;
    }
  };

  // ── Header ──
  return (
    <div className="flex-1 flex flex-col h-full bg-canvas">
      {/* Header */}
      <div className="h-14 flex items-center px-5 border-b border-hairline bg-white">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint mr-3">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-bold text-ink truncate">{task.title}</h2>
        </div>
        <span className={`flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full ${sc.bg} ${sc.color} ml-2`}>
          {t('task.status.' + task.status)}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-hairline bg-white px-4">
        {TABS.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all ${
                isActive
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-ink-mute hover:text-ink hover:border-gray-300'
              }`}
            >
              <Icon size={14} />
              {t(tab.i18n)}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            {renderTabContent()}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
