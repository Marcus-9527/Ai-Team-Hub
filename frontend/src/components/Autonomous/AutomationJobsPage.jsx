/** AutomationJobsPage.jsx — Teammate Autonomous Automation Engine v2 frontend. */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Zap, Plus, Play, Trash2, RefreshCw, Clock, Bot, Loader2 } from 'lucide-react';
import * as api from '../../services/api';

export default function AutomationJobsPage() {
  const [jobs, setJobs] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [runs, setRuns] = useState({});
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', teammate_id: '', goal: '', trigger_type: 'manual' });

  const load = useCallback(async () => {
    setLoading(true);
    const [j, t] = await Promise.all([
      api.listAutomationJobs().catch(() => ({ jobs: [] })),
      api.listTeammates().catch([]),
    ]);
    setJobs(j.jobs || []);
    setTeammates(Array.isArray(t) ? t : []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!form.name) return;
    await api.createAutomationJob(form);
    setShowCreate(false);
    setForm({ name: '', teammate_id: '', goal: '', trigger_type: 'manual' });
    load();
  };

  const handleDelete = async (id) => {
    await api.deleteAutomationJob(id);
    load();
  };

  const handleTrigger = async (id) => {
    await api.triggerAutomationJob(id);
    const rs = await api.listAutomationRuns(id).catch(() => ({ runs: [] }));
    setRuns(p => ({ ...p, [id]: rs.runs || [] }));
  };

  const showRuns = async (id) => {
    const rs = await api.listAutomationRuns(id).catch(() => ({ runs: [] }));
    setRuns(p => ({ ...p, [id]: rs.runs || [] }));
  };

  const TRIGGER_LABEL = { cron: '定时', event: '事件', webhook: 'Webhook', manual: '手动' };
  const STATUS_COLOR = { active: '#34d399', paused: '#f59e0b', archived: '#6b7280' };

  return (
    <div className="flex-1 flex flex-col p-6 bg-[#faf8f5] overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[#1d1d1d] flex items-center gap-2">
            <Zap size={20} className="text-[#fc1c46]" /> 自动化 v2 — AI 员工自主工作
          </h1>
          <p className="text-sm text-[#9ca3af] mt-0.5">为队友创建定时/事件/手动触发的工作任务</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#1d1d1d] text-white text-sm font-medium hover:bg-[#333] transition-all">
          <Plus size={16} /> 新建任务
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-6 p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm space-y-3">
          <input placeholder="任务名称 *" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-[#e2ddd7] text-sm focus:outline-none focus:border-[#1d1d1d]" />
          <select value={form.teammate_id} onChange={e => setForm(p => ({ ...p, teammate_id: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-[#e2ddd7] text-sm focus:outline-none focus:border-[#1d1d1d] bg-white">
            <option value="">不指定队友（自动分配）</option>
            {teammates.map(t => <option key={t.id} value={t.id}>{t.name} ({t.role})</option>)}
          </select>
          <select value={form.trigger_type} onChange={e => setForm(p => ({ ...p, trigger_type: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-[#e2ddd7] text-sm focus:outline-none focus:border-[#1d1d1d] bg-white">
            <option value="manual">手动触发</option>
            <option value="cron">定时（cron）</option>
            <option value="event">事件触发</option>
            <option value="webhook">Webhook</option>
          </select>
          <textarea placeholder="工作目标（goal）" value={form.goal} onChange={e => setForm(p => ({ ...p, goal: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-[#e2ddd7] text-sm focus:outline-none focus:border-[#1d1d1d] min-h-[60px]" />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm text-[#5c5c5c] hover:text-[#1d1d1d]">取消</button>
            <button onClick={handleCreate} className="px-4 py-2 rounded-lg bg-[#1d1d1d] text-white text-sm font-medium hover:bg-[#333] transition-all">创建</button>
          </div>
        </motion.div>
      )}

      {/* Jobs list */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 size={24} className="animate-spin text-[#9ca3af]" /></div>
      ) : jobs.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-[#9ca3af] gap-2">
          <Bot size={40} className="opacity-30" />
          <p className="text-sm">还没有自动化任务</p>
          <p className="text-xs">点击"新建任务"创建一个 AI 员工自主工作流程</p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map(job => (
            <div key={job.id} className="p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-[#1d1d1d] text-sm">{job.name}</h3>
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                      style={{ backgroundColor: STATUS_COLOR[job.status] + '20', color: STATUS_COLOR[job.status] }}>
                      {job.status}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#e2ddd7] text-[#5c5c5c] font-medium">
                      {TRIGGER_LABEL[job.trigger_type] || job.trigger_type}
                    </span>
                  </div>
                  <p className="text-xs text-[#9ca3af] mt-1 truncate">{job.goal || '—'}</p>
                  <div className="flex items-center gap-3 mt-1.5 text-[11px] text-[#9ca3af]">
                    <span className="flex items-center gap-1"><Bot size={12} />{teammates.find(t => t.id === job.teammate_id)?.name || '自动分配'}</span>
                    {job.last_run && <span className="flex items-center gap-1"><Clock size={12} />上次：{new Date(job.last_run).toLocaleString()}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0 ml-4">
                  <button onClick={() => handleTrigger(job.id)} title="手动触发" className="p-2 rounded-lg hover:bg-[#f4f2ef] text-[#5c5c5c] hover:text-[#34d399] transition-all"><Play size={14} /></button>
                  <button onClick={() => showRuns(job.id)} title="执行历史" className="p-2 rounded-lg hover:bg-[#f4f2ef] text-[#5c5c5c] hover:text-[#1d1d1d] transition-all"><RefreshCw size={14} /></button>
                  <button onClick={() => handleDelete(job.id)} title="删除" className="p-2 rounded-lg hover:bg-red-50 text-[#5c5c5c] hover:text-red-500 transition-all"><Trash2 size={14} /></button>
                </div>
              </div>
              {/* Runs */}
              {runs[job.id] && runs[job.id].length > 0 && (
                <div className="mt-3 pt-3 border-t border-[#e2ddd7] space-y-1">
                  <p className="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">执行记录</p>
                  {runs[job.id].slice(0, 5).map(r => (
                    <div key={r.id} className="flex items-center justify-between text-xs py-1">
                      <span className="text-[#1d1d1d]">{r.result || r.status} <span className="text-[#9ca3af]">({r.trigger})</span></span>
                      <span className="text-[#9ca3af]">{r.completed_at ? new Date(r.completed_at).toLocaleString() : '运行中…'}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
