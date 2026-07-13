/**
 * ApprovalPanel.jsx — 审批中心组件
 *
 * 展示所有审批请求，支持审批/拒绝操作。
 * 实时 SSE 更新审批状态。
 */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, CheckCircle2, XCircle, Clock,
  User, MessageSquare, AlertTriangle,
  ThumbsUp, ThumbsDown,
} from 'lucide-react';
import * as taskApi from '../../services/api/task';
import { subscribeTaskEvents } from '../../services/taskEventBus';
import { useTranslation } from '../../i18n';

const APPROVAL_STATUS = {
  PENDING:   { label: 'task.approval.pending', color: 'text-amber-600', bg: 'bg-amber-100' },
  APPROVED:  { label: 'task.approval.approve', color: 'text-green-600', bg: 'bg-green-100' },
  REJECTED:  { label: 'task.approval.reject', color: 'text-red-600',   bg: 'bg-red-100' },
};

export default function ApprovalPanel({ taskId }) {
  const t = useTranslation();
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const data = await taskApi.listApprovals(taskId);
      setApprovals(data || []);
    } catch (e) {
      console.error('[ApprovalPanel] load failed:', e);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { if (taskId) load(); }, [taskId, load]);

  // SSE: reload on approval events
  useEffect(() => {
    if (!taskId) return;
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (
        (type === 'approval_required' || type === 'approval_completed')
        && task_id === taskId
      ) {
        load();
      }
    });
    return unsub;
  }, [taskId, load]);

  const handleApprove = useCallback(async (approvalId) => {
    setActionLoading(approvalId);
    try {
      await taskApi.approveApproval(approvalId, { reason: t('task.approve_reason') });
      await load();
    } catch (e) {
      alert(t('task.approve_failed') + e.message);
    } finally {
      setActionLoading(null);
    }
  }, [load]);

  const handleReject = useCallback(async (approvalId) => {
    const reason = prompt(t('task.reject_reason_ph'));
    if (reason === null) return; // cancelled
    setActionLoading(approvalId);
    try {
      await taskApi.rejectApproval(approvalId, { reason: reason || t('task.reject_default') });
      await load();
    } catch (e) {
      alert(t('task.reject_failed') + e.message);
    } finally {
      setActionLoading(null);
    }
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-ink-faint" />
      </div>
    );
  }

  if (approvals.length === 0) {
    return (
      <div className="text-center py-12">
        <CheckCircle2 size={32} className="mx-auto mb-2 text-ink-faint opacity-40" />
        <p className="text-sm text-ink-faint">{t('task.approval.empty')}</p>
        <p className="text-xs text-ink-faint mt-1">{t('task.approval.empty_hint')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {approvals.map((ap, idx) => {
        const asc = APPROVAL_STATUS[ap.status] || APPROVAL_STATUS.PENDING;
        return (
          <motion.div
            key={ap.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05 }}
            className="bg-white rounded-xl border border-hairline p-4"
          >
            <div className="flex items-start gap-3">
              {/* Status indicator */}
              <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${asc.bg}`}>
                {ap.status === 'APPROVED' ? (
                  <CheckCircle2 size={16} className="text-green-600" />
                ) : ap.status === 'REJECTED' ? (
                  <XCircle size={16} className="text-red-600" />
                ) : (
                  <Clock size={16} className="text-amber-600" />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${asc.bg} ${asc.color}`}>
                    {t(asc.label)}
                  </span>
                  {ap.step_id && (
                    <span className="text-[11px] text-ink-faint">{t('task.step_label', ap.step_id.slice(0, 8))}</span>
                  )}
                </div>

                {ap.reason && (
                  <div className="flex items-start gap-1.5 mt-2 text-xs text-ink-mute">
                    <MessageSquare size={11} className="mt-0.5 flex-shrink-0" />
                    <span>{ap.reason}</span>
                  </div>
                )}

                <div className="flex items-center gap-3 mt-2 text-[10px] text-ink-faint">
                  {ap.requested_at && (
                    <span>{t('task.approval.request_at')}: {new Date(ap.requested_at).toLocaleString('zh-CN')}</span>
                  )}
                  {ap.approved_at && (
                    <span>{t('task.approval.handled_at')}: {new Date(ap.approved_at).toLocaleString('zh-CN')}</span>
                  )}
                  {ap.approved_by && (
                    <span className="flex items-center gap-1">
                      <User size={10} /> {ap.approved_by}
                    </span>
                  )}
                </div>

                {/* Action buttons (only for pending) */}
                {ap.status === 'PENDING' && (
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => handleApprove(ap.id)}
                      disabled={actionLoading === ap.id}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-semibold hover:bg-green-700 disabled:opacity-50 transition-all"
                    >
                      {actionLoading === ap.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <ThumbsUp size={12} />
                      )}
                      {t('task.approval.approve')}
                    </button>
                    <button
                      onClick={() => handleReject(ap.id)}
                      disabled={actionLoading === ap.id}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500 text-white text-xs font-semibold hover:bg-red-600 disabled:opacity-50 transition-all"
                    >
                      <ThumbsDown size={12} />
                      {t('task.approval.reject')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
