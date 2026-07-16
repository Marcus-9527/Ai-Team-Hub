/** RunStatusView.jsx — consolidated automation run history. */
import { useState, useEffect, useCallback } from 'react';
import { Clock, CheckCircle2, AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import * as api from '../../services/api';

const STATUS_ICON = {
  completed: <CheckCircle2 size={14} className="text-[#34d399]" />,
  failed: <AlertCircle size={14} className="text-[#ef4444]" />,
  running: <Loader2 size={14} className="animate-spin text-[#818cf8]" />,
  pending: <Clock size={14} className="text-[#f59e0b]" />,
};
const STATUS_LABEL = {
  completed: '已完成', failed: '失败', running: '运行中', pending: '等待中',
};

export default function RunStatusView() {
  const [runs, setRuns] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [r, j] = await Promise.all([
      api.listAllAutomationRuns().catch(() => ({ runs: [] })),
      api.listAutomationJobs().catch(() => ({ jobs: [] })),
    ]);
    setRuns(r.runs || []);
    setJobs(j.jobs || []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const jobMap = {};
  jobs.forEach(j => { jobMap[j.id] = j; });

  return (
    <div className="flex-1 flex flex-col p-6 bg-[#faf8f5] overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-[#1d1d1d] flex items-center gap-2">
          <Clock size={18} className="text-[#fc1c46]" /> 运行状态
        </h2>
        <button onClick={load} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-white border border-[#e2ddd7] text-[#5c5c5c] hover:text-[#1d1d1d] transition-all">
          <RefreshCw size={12} /> 刷新
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 size={24} className="animate-spin text-[#9ca3af]" /></div>
      ) : runs.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-[#9ca3af] gap-2">
          <Clock size={40} className="opacity-30" />
          <p className="text-sm">暂无执行记录</p>
          <p className="text-xs">创建定时任务后，执行记录会显示在这里</p>
        </div>
      ) : (
        <div className="space-y-2">
          {runs.map(r => {
            const job = jobMap[r.job_id];
            const icon = STATUS_ICON[r.status] || STATUS_ICON.pending;
            const label = STATUS_LABEL[r.status] || r.status;
            return (
              <div key={r.id} className="p-3 rounded-xl bg-white border border-[#e2ddd7] shadow-sm flex items-center gap-3">
                {icon}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#1d1d1d] truncate">{job?.name || r.job_id?.slice(0, 8) || '—'}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                      style={{
                        background: r.status === 'completed' ? 'rgba(52,211,153,0.15)' : r.status === 'failed' ? 'rgba(239,68,68,0.15)' : 'rgba(129,140,248,0.15)',
                        color: r.status === 'completed' ? '#34d399' : r.status === 'failed' ? '#ef4444' : '#818cf8',
                      }}>
                      {label}
                    </span>
                    <span className="text-[10px] text-[#9ca3af]">({r.trigger})</span>
                  </div>
                  <p className="text-xs text-[#9ca3af] mt-0.5 truncate">{r.result || r.error || '—'}</p>
                </div>
                <div className="text-[11px] text-[#9ca3af] flex-shrink-0 text-right">
                  {r.started_at && <p>{new Date(r.started_at).toLocaleString()}</p>}
                  {r.completed_at && <p className="text-[10px]">{new Date(r.completed_at).toLocaleString()}</p>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
