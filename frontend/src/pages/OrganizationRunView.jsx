/** OrganizationRunView — monitor & control a single run. */

import { useState, useEffect, useCallback } from 'react';
import {
  Activity, Clock, CheckCircle2, AlertCircle, Loader2,
  PauseCircle, PlayCircle, XCircle, ExternalLink, RefreshCw,
} from 'lucide-react';
import * as api from '../services/api';

const STATUS_COLOR = {
  active: '#818cf8', running: '#34d399', paused: '#f59e0b',
  cancelled: '#ef4444', completed: '#34d399',
};

export default function OrganizationRunView({ initialRunId = '' }) {
  const [runId, setRunId] = useState(initialRunId);
  const [input, setInput] = useState(initialRunId);
  const [status, setStatus] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError('');
    const [s, tl, sm] = await Promise.all([
      api.getRunStatus(runId).catch(e => (setError(e.message), null)),
      api.getRunTimeline(runId).catch(() => []),
      api.getRunSummary(runId).catch(() => null),
    ]);
    setStatus(s);
    setTimeline(tl || []);
    setSummary(sm);
    setLoading(false);
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  const act = async (fn, label) => {
    try {
      await fn(runId);
      load();
    } catch (e) { setError(`${label} 失败: ${e.message}`); }
  };

  const pickRun = () => { if (input.trim()) setRunId(input.trim()); };

  if (!runId) return (
    <div className="flex-1 flex items-center justify-center bg-[#faf8f5]">
      <div className="flex flex-col items-center gap-3">
        <Activity size={40} className="text-[#9ca3af] opacity-30" />
        <p className="text-sm text-[#9ca3af]">输入 Run ID 查看运行状态</p>
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            placeholder="run-xxx-xxx"
            className="px-3 py-2 rounded-lg border border-[#e2ddd7] text-sm w-64 outline-none focus:border-[#fc1c46]"
            onKeyDown={e => e.key === 'Enter' && pickRun()} />
          <button onClick={pickRun}
            className="px-4 py-2 rounded-lg bg-[#1d1d1d] text-white text-sm font-medium hover:bg-[#333] transition-all">
            查看
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col overflow-y-auto bg-[#faf8f5] p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Activity size={18} className="text-[#fc1c46]" />
          <h2 className="text-lg font-semibold text-[#1d1d1d]">运行监控</h2>
        </div>
        <div className="flex items-center gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            placeholder="Run ID" className="px-3 py-1.5 rounded-lg border border-[#e2ddd7] text-xs w-48 outline-none focus:border-[#fc1c46]"
            onKeyDown={e => e.key === 'Enter' && pickRun()} />
          <button onClick={pickRun} className="text-xs px-3 py-1.5 rounded-lg bg-white border border-[#e2ddd7] text-[#5c5c5c] hover:text-[#1d1d1d] transition-all">跳转</button>
          <button onClick={load} className="text-xs px-3 py-1.5 rounded-lg bg-white border border-[#e2ddd7] text-[#5c5c5c] hover:text-[#1d1d1d] transition-all flex items-center gap-1">
            <RefreshCw size={12} />刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600">{error}</div>
      )}

      {loading ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 size={24} className="animate-spin text-[#9ca3af]" /></div>
      ) : (
        <div className="space-y-4 max-w-4xl">
          {/* Status Card */}
          <div className="p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm">
            <h3 className="text-sm font-semibold text-[#1d1d1d] mb-3 flex items-center gap-2">
              <Clock size={14} className="text-[#818cf8]" /> 运行状态
            </h3>
            {status && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">运行 ID</p>
                  <p className="font-mono text-xs text-[#1d1d1d] break-all">{status.run_id}</p>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">状态</p>
                  <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded font-medium"
                    style={{ background: `${STATUS_COLOR[status.status] || '#9ca3af'}18`, color: STATUS_COLOR[status.status] || '#9ca3af' }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: STATUS_COLOR[status.status] || '#9ca3af' }} />
                    {status.status}
                  </span>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">当前动作</p>
                  <p className="text-[#1d1d1d]">{status.current_action?.action_type || '—'} / {status.current_action?.status || '—'}</p>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">进度</p>
                  <p className="text-[#1d1d1d]">{status.progress_state?.responded ? '✅ 已响应' : '⏳ 等待中'}</p>
                </div>
              </div>
            )}
          </div>

          {/* Timeline */}
          <div className="p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm">
            <h3 className="text-sm font-semibold text-[#1d1d1d] mb-3">事件时间线</h3>
            {timeline.length === 0 ? (
              <p className="text-xs text-[#9ca3af] py-2">暂无事件</p>
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {timeline.map((ev, i) => (
                  <div key={ev.event_id || i} className="flex items-start gap-3 text-xs py-1.5 border-b border-[#f4f2ef] last:border-0">
                    <span className="text-[10px] text-[#9ca3af] font-mono w-32 flex-shrink-0">
                      {ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : '—'}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#f4f2ef] text-[#5c5c5c] flex-shrink-0">
                      {ev.event_type}
                    </span>
                    <span className="text-[#5c5c5c] truncate">{ev.payload?.action_type || ev.payload?.status || ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Summary */}
          <div className="p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm">
            <h3 className="text-sm font-semibold text-[#1d1d1d] mb-3">执行摘要</h3>
            {summary && summary.status !== 'not_found' ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">类型</p>
                  <p className="text-[#1d1d1d]">{summary.run_type || '—'}</p>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">时长</p>
                  <p className="text-[#1d1d1d]">{summary.duration_seconds != null ? `${summary.duration_seconds.toFixed(0)}s` : '—'}</p>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">动作数</p>
                  <p className="text-[#1d1d1d]">{summary.action_count ?? '—'}</p>
                </div>
                <div>
                  <p className="text-[11px] text-[#9ca3af] mb-1">失败</p>
                  <p className="text-[#1d1d1d]">{summary.failure_count ?? '—'}</p>
                </div>
                <div className="col-span-2">
                  <p className="text-[11px] text-[#9ca3af] mb-1">参与队友</p>
                  <p className="text-[#1d1d1d]">{(summary.teammates || []).join(', ') || '—'}</p>
                </div>
                <div className="col-span-2">
                  <p className="text-[11px] text-[#9ca3af] mb-1">触发器</p>
                  <p className="text-[#1d1d1d]">{summary.trigger_count ?? '—'} 个</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-[#9ca3af] py-2">摘要不可用</p>
            )}
          </div>

          {/* Control Buttons */}
          <div className="p-4 rounded-xl bg-white border border-[#e2ddd7] shadow-sm">
            <h3 className="text-sm font-semibold text-[#1d1d1d] mb-3">控制</h3>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => act(api.pauseRun, '暂停')}
                disabled={status?.status !== 'active' && status?.status !== 'running'}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-[#f59e0b]/10 text-[#d97706] hover:bg-[#f59e0b]/20">
                <PauseCircle size={16} /> 暂停
              </button>
              <button onClick={() => act(api.resumeRun, '恢复')}
                disabled={status?.status !== 'paused'}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-[#34d399]/10 text-[#059669] hover:bg-[#34d399]/20">
                <PlayCircle size={16} /> 恢复
              </button>
              <button onClick={() => act(api.cancelRun, '取消')}
                disabled={status?.status === 'cancelled' || status?.status === 'completed'}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-red-50 text-red-600 hover:bg-red-100">
                <XCircle size={16} /> 取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
