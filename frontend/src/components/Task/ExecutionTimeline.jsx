/**
 * ExecutionTimeline.jsx — 执行时间线组件
 *
 * 展示任务所有执行的时序视图，包含：
 * - 每次执行的时间、teammate、model、token消耗、耗时
 * - 实时 SSE 更新
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, Clock, User, Cpu, DollarSign,
  CheckCircle2, XCircle, Activity,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';

export default function ExecutionTimeline({ taskId }) {
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const data = await taskApi.getTaskExecutions(taskId);
      setExecutions(data.executions || []);
    } catch (e) {
      console.error('[ExecutionTimeline] load failed:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (taskId) load(); }, [taskId]);

  // SSE real-time updates
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if ((type === 'execution_started' || type === 'execution_completed') && task_id === taskId) {
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

  if (executions.length === 0) {
    return (
      <div className="text-center py-12">
        <Activity size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">暂无执行记录</p>
        <p className="text-xs text-ink-faint mt-1">任务执行后这里会显示时间线</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {executions.map((ex, idx) => (
        <motion.div
          key={ex.id || idx}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: idx * 0.04 }}
          className="bg-white rounded-xl border border-hairline p-4"
        >
          <div className="flex items-start gap-3">
            {/* Timeline dot */}
            <div className="flex flex-col items-center pt-1">
              <div className={`w-3 h-3 rounded-full border-2 ${
                ex.status === 'completed' || ex.status === 'success'
                  ? 'border-green-400 bg-green-50'
                  : ex.status === 'failed' || ex.status === 'error'
                  ? 'border-red-400 bg-red-50'
                  : 'border-indigo-400 bg-indigo-50'
              }`} />
              {idx < executions.length - 1 && <div className="w-[2px] h-6 bg-gray-200 my-1" />}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                {ex.teammate_id && (
                  <span className="flex items-center gap-1 text-xs text-ink-mute">
                    <User size={11} />
                    {ex.teammate_id}
                  </span>
                )}
                {ex.model_name && (
                  <span className="flex items-center gap-1 text-xs text-ink-mute">
                    <Cpu size={11} />
                    {ex.model_name}
                  </span>
                )}
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-2">
                {ex.tokens != null && (
                  <div className="bg-gray-50 rounded-lg px-3 py-2">
                    <div className="text-[10px] text-ink-faint">Token</div>
                    <div className="text-xs font-semibold text-ink">{ex.tokens.toLocaleString()}</div>
                  </div>
                )}
                {ex.cost != null && (
                  <div className="bg-gray-50 rounded-lg px-3 py-2">
                    <div className="text-[10px] text-ink-faint flex items-center gap-1">
                      <DollarSign size={10} /> 成本
                    </div>
                    <div className="text-xs font-semibold text-ink">${ex.cost.toFixed(4)}</div>
                  </div>
                )}
                {ex.duration != null && (
                  <div className="bg-gray-50 rounded-lg px-3 py-2">
                    <div className="text-[10px] text-ink-faint flex items-center gap-1">
                      <Clock size={10} /> 耗时
                    </div>
                    <div className="text-xs font-semibold text-ink">{ex.duration}ms</div>
                  </div>
                )}
                {ex.status && (
                  <div className="bg-gray-50 rounded-lg px-3 py-2">
                    <div className="text-[10px] text-ink-faint">状态</div>
                    <div className={`text-xs font-semibold flex items-center gap-1 ${
                      ex.status === 'completed' || ex.status === 'success'
                        ? 'text-green-600'
                        : ex.status === 'failed' || ex.status === 'error'
                        ? 'text-red-600'
                        : 'text-indigo-600'
                    }`}>
                      {ex.status === 'completed' || ex.status === 'success' ? (
                        <CheckCircle2 size={12} />
                      ) : ex.status === 'failed' || ex.status === 'error' ? (
                        <XCircle size={12} />
                      ) : (
                        <Activity size={12} />
                      )}
                      {ex.status}
                    </div>
                  </div>
                )}
              </div>

              {/* Trace */}
              {ex.trace_id && (
                <div className="mt-2 text-[10px] text-ink-faint">
                  Trace: <code className="font-mono bg-gray-100 px-1 rounded">{ex.trace_id}</code>
                </div>
              )}
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
