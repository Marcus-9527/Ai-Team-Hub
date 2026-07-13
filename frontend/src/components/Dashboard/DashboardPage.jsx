/**
 * DashboardPage.jsx — Product Dashboard (Phase 15)
 *
 * One-page aggregator showing team overview, execution stats,
 * memory statistics, and teammate growth.
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Users, Activity, Brain, TrendingUp, DollarSign,
  Cpu, CheckCircle2, XCircle, Loader2, BarChart3,
} from 'lucide-react';

const BASE = import.meta.env.VITE_API_BASE || '';

async function fetchJSON(url) {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function StatCard({ icon: Icon, label, value, color, sub }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-hairline p-4"
    >
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${color || 'bg-gray-100'}`}>
          <Icon size={16} className={color?.replace('bg-', 'text-').replace('100', '600') || 'text-ink-mute'} />
        </div>
      </div>
      <div className="text-lg font-bold text-ink">{value ?? '-'}</div>
      <div className="text-[11px] text-ink-faint mt-0.5">{label}</div>
      {sub != null && <div className="text-[10px] text-ink-faint mt-0.5">{sub}</div>}
    </motion.div>
  );
}

function formatCost(μs) {
  if (μs == null) return '-';
  if (μs < 1000) return `${μs}µ$`;
  if (μs < 1_000_000) return `${(μs / 1000).toFixed(2)}m$`;
  return `$${(μs / 1_000_000).toFixed(4)}`;
}

export default function DashboardPage({ onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const d = await fetchJSON('/api/dashboard');
        setData(d);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <XCircle size={32} className="mx-auto mb-2 text-red-400" />
          <p className="text-sm text-red-500">{error}</p>
        </div>
      </div>
    );
  }

  const { execution: ex, teammate: tm, dag: dagS, memory: mem } = data || {};

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-100 flex items-center justify-center">
            <BarChart3 size={20} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-ink">产品仪表盘</h1>
            <p className="text-xs text-ink-faint">团队概览 · 执行统计 · 内存画像 · 队友成长</p>
          </div>
        </div>

        {/* ── Team Overview ── */}
        <section>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <Users size={14} /> 团队概览
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={Users} label="队友数量" value={tm?.total_teammates} color="bg-blue-100" />
            <StatCard icon={Activity} label="总执行次数" value={tm?.total_executions} color="bg-green-100" />
            <StatCard icon={TrendingUp} label="平均成功率" value={tm?.avg_success_rate != null ? `${(tm.avg_success_rate * 100).toFixed(1)}%` : '-'} color="bg-purple-100" />
            <StatCard icon={BarChart3} label="DAG 数量" value={dagS?.total_dags} color="bg-orange-100" />
          </div>
        </section>

        {/* ── Execution Overview ── */}
        <section>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <Activity size={14} /> 执行概况
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={CheckCircle2} label="已完成" value={ex?.completed} color="bg-green-100" />
            <StatCard icon={XCircle} label="失败" value={ex?.failed} color="bg-red-100" />
            <StatCard icon={Loader2} label="运行中" value={ex?.running} color="bg-blue-100" />
            <StatCard icon={Cpu} label="总 Token" value={ex?.total_tokens?.toLocaleString()} color="bg-indigo-100" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
            <StatCard icon={DollarSign} label="总成本" value={formatCost(ex?.total_cost_micro_usd)} color="bg-amber-100"
              sub={ex?.total_executions != null ? `${ex.total_executions} 次执行` : undefined} />
            <StatCard icon={Activity} label="执行总数" value={ex?.total_executions} color="bg-gray-100"
              sub={`${ex?.completed || 0} 成功 / ${ex?.failed || 0} 失败`} />
          </div>
        </section>

        {/* ── Memory Statistics ── */}
        <section>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <Brain size={14} /> 内存统计
          </h2>
          <div className="bg-white rounded-xl border border-hairline p-4">
            <div className="text-lg font-bold text-ink">{mem?.total_items ?? 0}</div>
            <div className="text-[11px] text-ink-faint mt-0.5">总记忆条目</div>
            {mem?.by_type && Object.keys(mem.by_type).length > 0 && (
              <div className="mt-3 space-y-1.5">
                {Object.entries(mem.by_type).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-2">
                    <span className="text-xs text-ink-mute w-24 truncate">{type}</span>
                    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${(count / mem.total_items) * 100}%` }}
                        className="h-full rounded-full bg-indigo-400"
                      />
                    </div>
                    <span className="text-xs font-mono text-ink-faint">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ── Teammate Growth ── */}
        <section>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <TrendingUp size={14} /> 队友成长
          </h2>
          <div className="bg-white rounded-xl border border-hairline divide-y divide-hairline">
            {(tm?.growth || []).length === 0 ? (
              <div className="p-4 text-center text-xs text-ink-faint">暂无队友</div>
            ) : (
              tm.growth.map((t, i) => (
                <div key={t.name + i} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="w-2 h-2 rounded-full bg-indigo-400" />
                  <span className="text-sm text-ink">{t.name}</span>
                  <span className="text-[10px] text-ink-faint ml-auto">
                    {t.created_at ? new Date(t.created_at).toLocaleDateString('zh-CN') : '-'}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>

      </div>
    </div>
  );
}
