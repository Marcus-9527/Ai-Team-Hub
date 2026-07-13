/**
 * TaskAnalytics.jsx — 任务分析仪表板
 *
 * 展示聚合统计数据：执行数量、成功率、平均质量、token消耗、成本
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, Activity, TrendingUp, Star,
  Cpu, DollarSign, BarChart3, RefreshCw,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import { useTranslation } from '../../i18n';

function StatCard({ icon: Icon, labelKey, value, sub, color }) {
  const t = useTranslation();
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
      <div className="text-[11px] text-ink-faint mt-0.5">{t(labelKey)}</div>
      {sub != null && <div className="text-[10px] text-ink-faint mt-0.5">{sub}</div>}
    </motion.div>
  );
}

export default function TaskAnalytics({ taskId }) {
  const t = useTranslation();
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const data = await taskApi.getTaskAnalytics(taskId);
      setAnalytics(data);
    } catch (e) {
      console.error('[TaskAnalytics] load failed:', e);
      setAnalytics(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (taskId) load(); }, [taskId]);

  // SSE refresh
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (
        (type === 'execution_completed' || type === 'execution_quality_updated')
        && task_id === taskId
      ) {
        load();
      }
    });
    return unsub;
  }, [taskId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  if (!analytics) {
    return (
      <div className="text-center py-12">
        <BarChart3 size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">{t('task.analytics.empty')}</p>
        <p className="text-xs text-ink-faint mt-1">{t('task.analytics.empty_hint')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={Activity}
          labelKey="task.analytics.exec_count"
          value={analytics.execution_count ?? analytics.total_executions}
          color="bg-blue-100"
        />
        <StatCard
          icon={TrendingUp}
          labelKey="task.analytics.success_rate"
          value={analytics.success_rate != null ? `${(analytics.success_rate * 100).toFixed(1)}%` : '-'}
          color="bg-green-100"
        />
        <StatCard
          icon={Star}
          labelKey="task.analytics.avg_quality"
          value={analytics.average_quality != null ? analytics.average_quality.toFixed(2) : '-'}
          sub={analytics.average_quality != null ? '/ 5' : undefined}
          color="bg-purple-100"
        />
        <StatCard
          icon={DollarSign}
          labelKey="task.analytics.total_cost"
          value={analytics.total_cost != null ? `$${analytics.total_cost.toFixed(4)}` : '-'}
          color="bg-amber-100"
        />
      </div>

      {/* Token consumption */}
      {analytics.total_tokens != null && (
        <div className="bg-white rounded-xl border border-hairline p-4">
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={15} className="text-ink-faint" />
            <h4 className="text-xs font-bold text-ink">{t('task.analytics.token_usage')}</h4>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <div className="flex items-center justify-between text-xs text-ink-mute mb-1">
                <span>{t('task.analytics.used')}</span>
                <span className="font-semibold text-ink">{analytics.total_tokens.toLocaleString()}</span>
              </div>
              {/* Visual bar */}
              <div className="w-full h-2.5 bg-gray-100 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: '100%' }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                  className="h-full rounded-full bg-indigo-500"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Summary footer */}
      <div className="bg-gray-50 rounded-xl border border-hairline p-3 text-center">
        <p className="text-[11px] text-ink-faint">
          {t('task.analytics.summary', analytics.task_title || taskId, analytics.task_status || '-')}
        </p>
      </div>
    </div>
  );
}
