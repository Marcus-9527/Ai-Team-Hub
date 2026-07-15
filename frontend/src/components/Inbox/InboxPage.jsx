/**
 * InboxPage.jsx — 我的工作台
 *
 * 三个板块：
 *   正在执行   → EXECUTING / PLANNING task
 *   需要我决策 → pending Brain proposal
 *   最近完成   → COMPLETED task
 *
 * 点击任务卡片 → 内联展开 TaskDetailView
 * 点击审批卡片 → 直接批准/拒绝
 *
 * ponytail: 15s polling 替代 SSE 订阅, 等延迟敏感再加
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Inbox, Loader2, PlayCircle, Clock, CheckCircle2, XCircle,
  FileCheck, ThumbsUp, ThumbsDown, Target,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import TaskDetailView from '../Task/TaskDetailView';

const STATUS_CFG = {
  EXECUTING: { icon: PlayCircle, color: 'text-indigo-600', bg: 'bg-indigo-100' },
  PLANNING:  { icon: Clock,      color: 'text-blue-600',   bg: 'bg-blue-100' },
  COMPLETED: { icon: CheckCircle2, color: 'text-green-600', bg: 'bg-green-100' },
  FAILED:    { icon: XCircle,    color: 'text-red-600',    bg: 'bg-red-100' },
};

function Section({ title, icon: Icon, children }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon size={16} className="text-ink-faint" />
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function TaskCard({ task, onClick }) {
  const t = useTranslation();
  const cfg = STATUS_CFG[task.status] || STATUS_CFG.EXECUTING;
  const StatusIcon = cfg.icon;
  return (
    <motion.button
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => onClick(task.id)}
      className="w-full text-left bg-white rounded-xl border border-hairline p-4 hover:border-primary/20 hover:shadow-sm transition-all mb-2"
    >
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${cfg.bg}`}>
          <StatusIcon size={16} className={cfg.color} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink truncate">{task.title}</h3>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${cfg.bg} ${cfg.color}`}>
              {t('task.status.' + task.status)}
            </span>
          </div>
          {(task.review_status || (task.files_changed || []).length > 0 || task.test_result) && (
            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              {task.review_status && (
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
                  📄 {task.files_changed.length} files
                </span>
              )}
              {task.test_result && (
                <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${
                  task.test_result.includes('passed') ? 'bg-green-100 text-green-600' : 'bg-amber-100 text-amber-600'
                }`}>
                  🧪 {task.test_result.length > 20 ? task.test_result.slice(0, 20) + '…' : task.test_result}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.button>
  );
}

function ProposalCard({ proposal, onApprove, onReject, actioning }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-amber-200/60 p-4 mb-2"
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-amber-100 flex items-center justify-center flex-shrink-0">
          <FileCheck size={16} className="text-amber-600" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-ink">{proposal.target_label || proposal.target_type}</h3>
          <p className="text-xs text-ink-faint mt-0.5">需要你的批准</p>
          <div className="flex gap-2 mt-2">
            <button
              onClick={() => onApprove(proposal.id)}
              disabled={actioning === proposal.id}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-100 text-green-700 text-[11px] font-semibold hover:bg-green-200 transition-all disabled:opacity-50"
            >
              {actioning === proposal.id ? <Loader2 size={12} className="animate-spin" /> : <ThumbsUp size={12} />}
              批准
            </button>
            <button
              onClick={() => onReject(proposal.id)}
              disabled={actioning === proposal.id}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-100 text-red-700 text-[11px] font-semibold hover:bg-red-200 transition-all disabled:opacity-50"
            >
              <ThumbsDown size={12} />
              拒绝
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

export default function InboxPage({ onNavigate }) {
  const t = useTranslation();
  const [running, setRunning] = useState([]);
  const [pending, setPending] = useState([]);
  const [completed, setCompleted] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTask, setSelectedTask] = useState(null);
  const [actioning, setActioning] = useState(null);

  const load = async () => {
    try {
      const [execData, planData, pendData, doneData] = await Promise.all([
        taskApi.listTasks({ status: 'EXECUTING', limit: 10 }),
        taskApi.listTasks({ status: 'PLANNING', limit: 10 }),
        api.listPendingProposals().catch(() => ({ proposals: [] })),
        taskApi.listTasks({ status: 'COMPLETED', limit: 5 }),
      ]);
      setRunning([...(planData.tasks || []), ...(execData.tasks || [])].slice(0, 5));
      setPending((pendData.proposals || []).slice(0, 5));
      setCompleted((doneData.tasks || []).slice(0, 5));
    } catch (e) { console.error('[Inbox] load:', e); }
    setLoading(false);
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 15_000);
    return () => clearInterval(iv);
  }, []);

  // ── Inline task detail ──
  if (selectedTask) {
    return <TaskDetailView taskId={selectedTask} onBack={() => setSelectedTask(null)} />;
  }

  const handleApprove = async (id) => {
    setActioning(id);
    try { await api.approveProposal(id); load(); } catch (e) { console.error(e); }
    setActioning(null);
  };

  const handleReject = async (id) => {
    setActioning(id);
    try { await api.rejectProposal(id); load(); } catch (e) { console.error(e); }
    setActioning(null);
  };

  if (loading && running.length === 0 && pending.length === 0 && completed.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-ink">我的工作</h1>
          <button
            onClick={() => onNavigate?.('new-topic')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary-press transition-all"
          >
            <Target size={14} />
            新任务
          </button>
        </div>

        {running.length > 0 && (
          <Section title="正在执行" icon={PlayCircle}>
            {running.map(t => <TaskCard key={t.id} task={t} onClick={setSelectedTask} />)}
          </Section>
        )}

        {pending.length > 0 && (
          <Section title="需要我决策" icon={FileCheck}>
            {pending.map(p => (
              <ProposalCard key={p.id} proposal={p} onApprove={handleApprove} onReject={handleReject} actioning={actioning} />
            ))}
          </Section>
        )}

        {completed.length > 0 && (
          <Section title="最近完成" icon={CheckCircle2}>
            {completed.map(t => <TaskCard key={t.id} task={t} onClick={setSelectedTask} />)}
          </Section>
        )}

        {!loading && running.length === 0 && pending.length === 0 && completed.length === 0 && (
          <div className="text-center py-16">
            <Inbox size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">还没有任务，创建一个开始工作吧</p>
          </div>
        )}
      </div>
    </div>
  );
}
