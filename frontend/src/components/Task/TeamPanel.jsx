import { useState, useEffect, useMemo } from 'react';
import { CheckCircle2, Loader2, Clock, XCircle, User } from 'lucide-react';
import * as api from '../../services/api';

const STEP_STATUS = {
  PENDING:    { color: 'text-gray-400', bg: 'bg-gray-100', icon: Clock },
  SCHEDULED:  { color: 'text-blue-500', bg: 'bg-blue-100', icon: Clock },
  RUNNING:    { color: 'text-indigo-500', bg: 'bg-indigo-100', icon: Loader2 },
  COMPLETED:  { color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle2 },
  FAILED:     { color: 'text-red-600',  bg: 'bg-red-100', icon: XCircle },
  SKIPPED:    { color: 'text-gray-400', bg: 'bg-gray-100', icon: XCircle },
};

export default function TeamPanel({ steps = [] }) {
  const [teammates, setTeammates] = useState([]);
  useEffect(() => {
    api.listTeammates().then(setTeammates).catch(() => {});
  }, []);

  const tmMap = useMemo(() => {
    const m = {};
    for (const t of teammates) m[t.id] = t;
    return m;
  }, [teammates]);

  // Group steps by teammate
  const tmSteps = useMemo(() => {
    const map = {};
    for (const s of steps) {
      const tid = s.teammate_id || 'unassigned';
      if (!map[tid]) map[tid] = [];
      map[tid].push(s);
    }
    return map;
  }, [steps]);

  // Aggregate per-teammate status (most severe first)
  const tmStatus = useMemo(() => {
    const out = {};
    for (const [tid, ss] of Object.entries(tmSteps)) {
      if (ss.some(s => s.status === 'RUNNING')) out[tid] = 'running';
      else if (ss.some(s => s.status === 'FAILED')) out[tid] = 'failed';
      else if (ss.some(s => s.status === 'SCHEDULED')) out[tid] = 'planning';
      else if (ss.every(s => s.status === 'COMPLETED')) out[tid] = 'completed';
      else out[tid] = 'waiting';
    }
    return out;
  }, [tmSteps]);

  const STATUS_BADGE = {
    running:   'bg-indigo-100 text-indigo-600',
    planning:  'bg-blue-100 text-blue-600',
    completed: 'bg-green-100 text-green-600',
    failed:    'bg-red-100 text-red-600',
    waiting:   'bg-gray-100 text-gray-500',
  };

  const tmIds = Object.keys(tmSteps);

  if (tmIds.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold text-ink">团队成员</h3>
      <div className="grid gap-2">
        {tmIds.map(tid => {
          const tm = tmMap[tid];
          const st = tmStatus[tid] || 'waiting';
          const ss = tmSteps[tid];
          const done = ss.filter(s => s.status === 'COMPLETED').length;
          return (
            <div key={tid} className="bg-white rounded-xl border border-hairline p-3 flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-canvas-lavender flex items-center justify-center text-base flex-shrink-0">
                {tm?.avatar_emoji || <User size={16} className="text-ink-faint" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-ink truncate">{tm?.name || tid}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[st]}`}>
                    {st === 'running' ? '执行中' : st === 'completed' ? '完成' : st === 'failed' ? '失败' : st === 'planning' ? '规划中' : '等待'}
                  </span>
                </div>
                <p className="text-[10px] text-ink-faint mt-0.5">{tm?.role || ''} · {tm?.model_provider ? `${tm.model_provider}/${tm.model_name}` : ''}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <span className="text-[11px] font-semibold text-ink">{done}/{ss.length}</span>
                <p className="text-[10px] text-ink-faint">步骤</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Step progress */}
      <h3 className="text-sm font-bold text-ink mt-4">步骤进度</h3>
      <div className="grid gap-1.5">
        {steps.map((s, i) => {
          const ss = STEP_STATUS[s.status] || STEP_STATUS.PENDING;
          const Icon = ss.icon;
          return (
            <div key={s.id} className="flex items-center gap-2.5 px-1 py-1.5">
              <Icon size={14} className={`${ss.color} flex-shrink-0`} />
              <span className="text-xs text-ink truncate flex-1">{s.objective || `步骤 ${s.order}`}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${ss.color} ${ss.bg}`}>
                {s.status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
