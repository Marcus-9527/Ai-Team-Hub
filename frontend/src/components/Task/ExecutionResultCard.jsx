/**
 * ExecutionResultCard.jsx — 执行结果评分卡片
 *
 * 展示 ExecutionResult 评分数据：
 * outcome, completeness, coherence, accuracy, overall_quality
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, Star, Target, GitMerge, Crosshair,
  BarChart3, User,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import { useTranslation } from '../../i18n';

const QUALITY_KEYS = {
  outcome:          { icon: Target, color: 'text-green-600' },
  completeness:     { icon: BarChart3, color: 'text-blue-600' },
  coherence:        { icon: GitMerge, color: 'text-indigo-600' },
  accuracy:         { icon: Crosshair, color: 'text-amber-600' },
  overall_quality:  { icon: Star, color: 'text-purple-600' },
};

function ScoreBar({ name, value, config, t }) {
  const Icon = config.icon;
  const pct = Math.round((value / 5) * 100);
  return (
    <div className="bg-white rounded-lg border border-hairline p-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="flex items-center gap-1.5 text-xs font-medium text-ink-mute">
          <Icon size={13} className={config.color} />
          {t('task.quality.' + name)}
        </span>
        <span className="text-xs font-bold text-ink">{value?.toFixed(1) ?? '-'} / 5</span>
      </div>
      <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className={`h-full rounded-full ${config.color.replace('text-', 'bg-').replace('600', '500')}`}
        />
      </div>
    </div>
  );
}

export default function ExecutionResultCard({ taskId }) {
  const t = useTranslation();
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const data = await taskApi.getTaskResults(taskId);
      setResults(data.results || []);
    } catch (e) {
      console.error('[ExecutionResultCard] load failed:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (taskId) load(); }, [taskId]);

  // SSE live update
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (type === 'execution_quality_updated' && task_id === taskId) {
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

  if (results.length === 0) {
    return (
      <div className="text-center py-12">
        <BarChart3 size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">{t('task.quality.empty')}</p>
        <p className="text-xs text-ink-faint mt-1">{t('task.quality.empty_hint')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {results.map((r, idx) => (
        <motion.div
          key={r.id || idx}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.05 }}
          className="bg-gray-50 rounded-xl border border-hairline p-4"
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-xs text-ink-mute">
              {r.evaluator && (
                <span className="flex items-center gap-1">
                  <User size={11} /> {r.evaluator}
                </span>
              )}
              {r.plan_matched != null && (
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                  r.plan_matched ? 'bg-green-100 text-green-600' : 'bg-amber-100 text-amber-600'
                }`}>
                  {r.plan_matched ? t('task.plan_matched') : t('task.plan_deviated')}
                </span>
              )}
            </div>
          </div>

          {/* Score bars */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {Object.entries(QUALITY_KEYS).map(([key, cfg]) => (
              <ScoreBar key={key} name={key} value={r[key]} config={cfg} t={t} />
            ))}
          </div>
        </motion.div>
      ))}
    </div>
  );
}
