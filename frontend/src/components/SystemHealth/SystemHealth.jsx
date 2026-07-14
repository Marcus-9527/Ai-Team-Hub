import { useState, useEffect } from 'react';
import * as api from '../../services/api';

const CHECK = [
  { key: 'api',       label: 'API Server',       check: () => api.healthCheck() },
  { key: 'providers', label: 'Model Providers',   check: () => api.fetchAllModels().then(m => ({ status: 'ok', meta: `${m.models?.length || 0} models` })).catch(() => ({ status: 'error' })) },
  { key: 'teammates', label: 'Teammates',         check: () => api.listTeammates().then(t => ({ status: 'ok', meta: `${t.length} configured` })).catch(() => ({ status: 'error' })) },
  { key: 'channels',  label: 'Channels',          check: () => api.listChannels().then(c => ({ status: 'ok', meta: `${c.length} channels` })).catch(() => ({ status: 'error' })) },
  { key: 'brain',     label: 'Brain System',      check: () => api.getBrainOverview().then(b => ({ status: 'ok', meta: `${Object.keys(b.fragments || {}).length} fragments` })).catch(() => ({ status: 'error' })) },
  { key: 'memory',    label: 'Memory System',     check: () => api.listBrainFragments('_system').then(() => ({ status: 'ok', meta: 'operational' })).catch(() => ({ status: 'error' })) },
  { key: 'tools',     label: 'Tool Gateway',      check: () => api.healthCheck().then(() => ({ status: 'ok', meta: 'available' })).catch(() => ({ status: 'error' })) },
];

export default function SystemHealth() {
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState(true);

  const run = () => {
    setLoading(true);
    Promise.all(CHECK.map(c => c.check().then(r => ({ status: 'ok', ...r })).catch(() => ({ status: 'error' }))))
      .then((vals) => {
        const m = {};
        CHECK.forEach((c, i) => { m[c.key] = vals[i]; });
        setResults(m);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { run(); const iv = setInterval(run, 15000); return () => clearInterval(iv); }, []);

  const ok = (r) => r?.status === 'ok';
  const bg = (r) => ok(r) ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600';
  const dot = (r) => ok(r) ? 'bg-emerald-500' : 'bg-red-500';

  const overall = CHECK.every(c => ok(results[c.key]));

  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <span className={`w-3 h-3 rounded-full ${overall ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <h1 className="text-lg font-bold" style={{ color: 'var(--color-ink)' }}>System Health</h1>
          </div>
          <button onClick={run} disabled={loading}
            className="text-xs px-3 py-1.5 rounded-lg border transition-all"
            style={{ borderColor: 'rgba(0,0,0,0.08)', color: 'var(--color-ink-faint)' }}>
            {loading ? '检查中...' : '刷新'}
          </button>
        </div>
        <div className="space-y-2">
          {CHECK.map(c => {
            const r = results[c.key];
            return (
              <div key={c.key}
                className="flex items-center justify-between px-4 py-3 rounded-xl border"
                style={{ background: 'var(--color-surface)', borderColor: 'var(--color-hairline)' }}>
                <div className="flex items-center gap-3">
                  <span className={`w-2.5 h-2.5 rounded-full ${dot(r)}`} />
                  <span className="text-sm font-medium" style={{ color: 'var(--color-ink)' }}>{c.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  {r?.meta && <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>{r.meta}</span>}
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded ${bg(r)}`}>
                    {r ? (ok(r) ? 'OK' : 'DOWN') : '—'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        <div className={`mt-6 text-center text-xs px-4 py-3 rounded-xl ${overall ? 'text-emerald-600 bg-emerald-500/5' : 'text-red-600 bg-red-500/5'}`}>
          {overall ? '✓ All systems operational' : '⚠ Some systems are down — check each component'}
        </div>
      </div>
    </div>
  );
}
