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
import * as api from '../../services/api';

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
        const d = await api.getDashboard();
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

        {/* Execution Stats */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <Activity size={15} className="text-indigo-500" /> 执行统计
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={CheckCircle2} label="完成" value={ex?.completed || 0} color="bg-green-100" />
            <StatCard icon={XCircle} label="失败" value={ex?.failed || 0} color="bg-red-100" />
            <StatCard icon={Cpu} label="进行中" value={ex?.in_progress || 0} color="bg-blue-100" />
            <StatCard icon={TrendingUp} label="总执行" value={ex?.total || 0} color="bg-purple-100" />
          </div>
        </div>

        {/* Teammate Stats */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
            <Users size={15} className="text-indigo-500" /> 队友画像
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <StatCard icon={Users} label="队友数" value={tm?.count || 0} color="bg-indigo-100" />
            <StatCard icon={Brain} label="记忆条目" value={mem?.total_items || 0} color="bg-amber-100" sub={`${mem?.fragment_types || 0} 种类型`} />
            <StatCard icon={DollarSign} label="总花费" value={formatCost(tm?.total_cost_μs)} color="bg-emerald-100" />
          </div>
        </div>

        {/* DAG Stats */}
        {dagS && (
          <div>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <BarChart3 size={15} className="text-indigo-500" /> DAG 执行分布
            </h2>
            <div className="bg-white rounded-xl border border-hairline p-4">
              <div className="text-xs text-ink-faint">
                <span className="font-medium text-ink">节点:</span> {dagS.total_nodes || 0} · <span className="font-medium text-ink">边:</span> {dagS.total_edges || 0} · <span className="font-medium text-ink">深度:</span> {dagS.max_depth || 0}
              </div>
              <div className="mt-3 text-[11px] text-ink-faint">
                {dagS.status_counts ? Object.entries(dagS.status_counts).map(([k, v]) => (
                  <span key={k} className="mr-4">
                    <span className="font-medium text-ink capitalize">{k}:</span> {v}
                  </span>
                )) : '暂无 DAG 数据'}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
