/**
 * PlanView.jsx — 任务计划查看组件
 *
 * 展示 TaskPlan 和 Review 状态，包括：
 * - 计划详情（标题、描述、置信度、风险评估）
 * - 计划步骤预览
 * - Review 状态
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, FileText, AlertTriangle, Target,
  CheckCircle2, XCircle, RefreshCw,
  Clock, User,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import { useTranslation } from '../../i18n';

export default function PlanView({ taskId }) {
  const t = useTranslation();
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await taskApi.getTaskPlan(taskId);
      setPlan(data);
    } catch (e) {
      setError(e.message);
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (taskId) load(); }, [taskId]);

  // SSE: reload on plan_created
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if ((type === 'plan_created' || type === 'task_started') && task_id === taskId) {
        load();
      }
    });
    return unsub;
  }, [taskId]);

  const formatCost = (cost) => {
    if (!cost || cost === '0' || cost === '0.00') return t('task.plan.unknown');
    if (cost.startsWith('$')) return cost;
    return `$${parseFloat(cost).toFixed(4)}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="text-center py-12">
        <FileText size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">{error || t('task.plan.empty')}</p>
        <p className="text-xs text-ink-faint mt-1">{t('task.plan.empty_hint')}</p>
      </div>
    );
  }

  const riskLabel = plan.risk_level === 'high' ? t('task.risk.high') : plan.risk_level === 'medium' ? t('task.risk.medium') : t('task.risk.low');

  return (
    <div className="space-y-4">
      {/* Plan Header */}
      <div className="bg-white rounded-xl border border-hairline p-5">
        <h3 className="text-sm font-bold text-ink mb-2">{plan.title || t('task.plan.fallback_title')}</h3>
        {plan.description && (
          <p className="text-sm text-ink-mute mb-3 leading-relaxed">{plan.description}</p>
        )}

        {/* Meta grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="text-[10px] text-ink-faint">{t('task.plan.confidence')}</div>
            <div className="text-xs font-semibold text-ink">{plan.confidence || '-'}</div>
          </div>
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="text-[10px] text-ink-faint">{t('task.plan.risk')}</div>
            <div className={`text-xs font-semibold ${
              plan.risk_level === 'high' ? 'text-red-600' :
              plan.risk_level === 'medium' ? 'text-amber-600' :
              'text-green-600'
            }`}>
              {riskLabel}
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="text-[10px] text-ink-faint">{t('task.plan.estimated_cost')}</div>
            <div className="text-xs font-semibold text-ink">{formatCost(plan.estimated_cost)}</div>
          </div>
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="text-[10px] text-ink-faint">{t('task.plan.steps_count')}</div>
            <div className="text-xs font-semibold text-ink">{plan.steps_count || plan.steps?.length || 0}</div>
          </div>
        </div>

        {plan.rationale && (
          <div className="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-200">
            <div className="flex items-center gap-1.5 text-[11px] text-amber-700 font-semibold mb-1">
              <AlertTriangle size={12} />
              <span>{t('task.plan.rationale')}</span>
            </div>
            <p className="text-xs text-amber-800 leading-relaxed">{plan.rationale}</p>
          </div>
        )}
      </div>

      {/* Plan Steps */}
      {plan.steps && plan.steps.length > 0 && (
        <div className="bg-white rounded-xl border border-hairline p-5">
          <h4 className="text-xs font-bold text-ink mb-3">{t('task.plan.steps', plan.steps.length)}</h4>
          <div className="space-y-2">
            {plan.steps.map((step, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.04 }}
                className="flex items-start gap-3 p-3 rounded-lg bg-gray-50 border border-hairline"
              >
                <div className="w-6 h-6 rounded-full bg-indigo-100 flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-bold text-indigo-600">{idx + 1}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink">{step.objective || step.description || t('task.step_label', idx + 1)}</p>
                  {step.teammate_id && (
                    <span className="flex items-center gap-1 text-[11px] text-ink-faint mt-1">
                      <User size={10} /> {step.teammate_id}
                    </span>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* Review Status */}
      {plan.status && (
        <div className="bg-white rounded-xl border border-hairline p-4">
          <div className="flex items-center gap-2 text-xs text-ink-mute">
            <Clock size={13} />
            <span>{t('task.plan.status_label')}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              plan.status === 'approved' ? 'bg-green-100 text-green-600' :
              plan.status === 'rejected' ? 'bg-red-100 text-red-600' :
              plan.status === 'reviewing' ? 'bg-amber-100 text-amber-600' :
              'bg-gray-100 text-gray-600'
            }`}>
              {t('task.plan.status.' + (plan.status || 'pending'))}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
