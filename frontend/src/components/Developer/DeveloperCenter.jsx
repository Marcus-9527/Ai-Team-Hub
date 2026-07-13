import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Activity, GitBranch, KeyRound, Brain } from 'lucide-react';
import { useTranslation } from '../../i18n';

const BASE = import.meta.env.VITE_API_BASE || '';

async function getJSON(url) {
  const r = await fetch(`${BASE}${url}`);
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

function Card({ icon: Icon, title, desc, children }) {
  return (
    <div className="bg-white rounded-xl border border-hairline p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
          <Icon size={16} />
        </div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
      </div>
      <p className="text-[11px] text-ink-faint mb-3">{desc}</p>
      {children}
    </div>
  );
}

function ComingSoon() {
  const t = useTranslation();
  return (
    <div className="text-[11px] text-ink-faint py-2 italic">{t('dev.coming_soon')}</div>
  );
}

function Loading() {
  return <div className="text-[11px] text-ink-faint py-2">…</div>;
}

export default function DeveloperCenter() {
  const t = useTranslation();
  const [exec, setExec] = useState(null);
  const [dag, setDag] = useState(null);
  const [api, setApi] = useState(null);
  const [brain, setBrain] = useState(null);

  useEffect(() => {
    getJSON('/api/executions').then(d => setExec(d)).catch(() => setExec(false));
    getJSON('/api/dags').then(d => setDag(d)).catch(() => setDag(false));
    getJSON('/api/apikeys').then(d => setApi(d)).catch(() => setApi(false));
    getJSON('/api/brain').then(d => setBrain(d)).catch(() => setBrain(false));
  }, []);

  const dagList = Array.isArray(dag) ? dag : (dag && Array.isArray(dag.dags) ? dag.dags : []);
  const apiList = Array.isArray(api) ? api : [];
  const execList = exec && Array.isArray(exec.executions) ? exec.executions : [];
  const memCounts = brain?.memory_counts || {};
  const insights = brain?.recent_insights || [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-5">
        <h1 className="text-xl font-bold text-ink">{t('dev.center')}</h1>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* Execution */}
          <Card icon={Activity} title={t('dev.execution')} desc={t('dev.execution_desc')}>
            {exec === null ? <Loading /> :
             exec === false || execList.length === 0 ? <ComingSoon /> :
             execList.slice(0, 5).map(e => (
               <div key={e.id} className="text-[11px] text-ink-mute py-1 border-t border-hairline flex justify-between gap-2">
                 <span className="font-mono truncate">{String(e.id).slice(0, 8)}</span>
                 <span className="flex-shrink-0">{e.status}</span>
               </div>
             ))}
          </Card>

          {/* DAG */}
          <Card icon={GitBranch} title={t('dev.dag')} desc={t('dev.dag_desc')}>
            {dag === null ? <Loading /> :
             dag === false || dagList.length === 0 ? <ComingSoon /> :
             dagList.slice(0, 5).map((d, i) => (
               <div key={d.id || i} className="text-[11px] text-ink-mute py-1 border-t border-hairline truncate">
                 {d.name || d.id || `DAG ${i + 1}`}
               </div>
             ))}
          </Card>

          {/* API */}
          <Card icon={KeyRound} title={t('dev.api')} desc={t('dev.api_desc')}>
            {api === null ? <Loading /> :
             api === false || apiList.length === 0 ? <ComingSoon /> :
             apiList.slice(0, 5).map(k => (
               <div key={k.id} className="text-[11px] text-ink-mute py-1 border-t border-hairline flex justify-between gap-2">
                 <span className="truncate">{k.label}</span>
                 <span className="flex-shrink-0">{k.provider}</span>
               </div>
             ))}
          </Card>

          {/* Brain (Phase 6) */}
          <Card icon={Brain} title="Brain" desc="Memory + Insights + Evaluation">
            {brain === null ? <Loading /> :
             brain === false ? <ComingSoon /> :
             <>
               <div className="text-[11px] text-ink-mute py-1 border-t border-hairline">
                 记忆: {memCounts.total_items || 0} 条
               </div>
               <div className="text-[11px] text-ink-mute py-1 border-t border-hairline">
                 评价: {brain.evaluation_stats?.total_evaluations || 0} 次 (均分 {brain.evaluation_stats?.average_score || '-'})
               </div>
               {insights.length > 0 && (
                 <div className="text-[11px] text-ink-mute py-1 border-t border-hairline">
                   Insight: {insights[0]?.type} · {String(insights[0]?.content || '').slice(0, 30)}
                 </div>
               )}
             </>}
          </Card>
        </div>
      </div>
    </div>
  );
}
