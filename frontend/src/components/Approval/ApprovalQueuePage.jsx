/**
 * ApprovalQueuePage.jsx — 全局审批队列
 *
 * 展示所有任务的待审批请求，支持批量操作。
 * 使用现有 /api/approvals 和 /api/tasks/ID/approvals 接口。
 */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2, CheckCircle2, XCircle, Clock,
  User, MessageSquare, ThumbsUp, ThumbsDown, ArrowLeft,
} from 'lucide-react';
import * as api from '../../services/api';
import * as taskApi from '../../services/api/task';
import { useTranslation } from '../../i18n';

const STATUS_STYLE = {
  PENDING:   { label: 'task.approval.pending', color: 'text-amber-600', bg: 'bg-amber-100' },
  APPROVED:  { label: 'task.approval.approve', color: 'text-green-600', bg: 'bg-green-100' },
  REJECTED:  { label: 'task.approval.reject',  color: 'text-red-600',   bg: 'bg-red-100' },
  EXPIRED:   { label: '已过期',                   color: 'text-gray-400', bg: 'bg-gray-100' },
};

export default function ApprovalQueuePage({ onBack }) {
  const t = useTranslation();
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [filter, setFilter] = useState('PENDING');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const all = await listAllApprovals();
      setApprovals(all);
    } catch (e) {
      console.error('[ApprovalQueue] load failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleApprove = useCallback(async (aid) => {
    setActionLoading(aid);
    try { await taskApi.approveApproval(aid); await load(); }
    catch (e) { console.error('[ApprovalQueue] approve failed:', e); }
    finally { setActionLoading(null); }
  }, [load]);

  const handleReject = useCallback(async (aid) => {
    const reason = prompt('拒绝原因（可选）');
    if (reason === null) return;
    setActionLoading(aid);
    try {
      await taskApi.rejectApproval(aid, { reason: reason || '用户拒绝' });
      await load();
    } catch (e) { console.error('[ApprovalQueue] reject failed:', e); }
    finally { setActionLoading(null); }
  }, [load]);

  const filtered = filter ? approvals.filter(a => a.status === filter) : approvals;
  const pendingCount = approvals.filter(a => a.status === 'PENDING').length;

  return (
    <div className="flex-1 flex flex-col h-full bg-canvas">
      {/* Header */}
      <div className="h-14 flex items-center gap-3 px-5 border-b border-hairline bg-white flex-shrink-0">
        {onBack && (
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint">
            <ArrowLeft size={18} />
          </button>
        )}
        <CheckCircle2 size={18} className="text-ink-faint" />
        <h2 className="font-bold text-[15px] text-ink">审批中心</h2>
        {pendingCount > 0 && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-600">
            {pendingCount} 待审批
          </span>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1.5 px-5 py-2.5 border-b border-hairline bg-white flex-shrink-0">
        {[
          { value: 'PENDING', label: '待审批' },
          { value: '', label: '全部' },
          { value: 'APPROVED', label: '已批准' },
          { value: 'REJECTED', label: '已拒绝' },
        ].map(f => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
              filter === f.value
                ? 'bg-primary text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={24} className="animate-spin text-ink-faint" />
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center h-60 text-ink-faint">
            <CheckCircle2 size={48} className="mb-3 opacity-30" />
            <p className="text-sm">{filter === 'PENDING' ? '暂无待审批请求' : '无匹配记录'}</p>
          </div>
        )}

        <div className="space-y-3 max-w-3xl">
          {filtered.map((ap, idx) => {
            const asc = STATUS_STYLE[ap.status] || STATUS_STYLE.PENDING;
            return (
              <motion.div
                key={ap.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.03 }}
                className="bg-white rounded-xl border border-hairline p-4"
              >
                <div className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${asc.bg}`}>
                    {ap.status === 'APPROVED' ? <CheckCircle2 size={16} className="text-green-600" />
                     : ap.status === 'REJECTED' ? <XCircle size={16} className="text-red-600" />
                     : <Clock size={16} className="text-amber-600" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${asc.bg} ${asc.color}`}>
                        {asc.label}
                      </span>
                      {ap.step_id && (
                        <span className="text-[11px] text-ink-faint font-mono">步骤 {ap.step_id.slice(0,8)}</span>
                      )}
                      {ap.task_id && (
                        <span className="text-[11px] text-ink-faint">任务 {ap.task_id.slice(0,8)}</span>
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
                        <span>请求: {new Date(ap.requested_at).toLocaleString('zh-CN')}</span>
                      )}
                      {ap.approved_at && (
                        <span>处理: {new Date(ap.approved_at).toLocaleString('zh-CN')}</span>
                      )}
                      {ap.approved_by && (
                        <span className="flex items-center gap-1"><User size={10} /> {ap.approved_by}</span>
                      )}
                    </div>

                    {/* Actions */}
                    {ap.status === 'PENDING' && (
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={() => handleApprove(ap.id)}
                          disabled={actionLoading === ap.id}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-semibold hover:bg-green-700 disabled:opacity-50 transition-all"
                        >
                          {actionLoading === ap.id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : <ThumbsUp size={12} />}
                          批准
                        </button>
                        <button
                          onClick={() => handleReject(ap.id)}
                          disabled={actionLoading === ap.id}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500 text-white text-xs font-semibold hover:bg-red-600 disabled:opacity-50 transition-all"
                        >
                          <ThumbsDown size={12} /> 拒绝
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

async function listAllApprovals() {
  const BASE = import.meta.env.VITE_API_BASE || '';
  const f = async (url) => {
    const r = await fetch(`${BASE}${url}`);
    return r.ok ? r.json() : { approvals: [] };
  };
  const [pending, all] = await Promise.all([
    f('/api/approvals'),
    f('/api/approvals?all=1'),
  ]);
  return [...(pending.approvals || []), ...(all.approvals || [])]
    .filter((a, i, arr) => arr.findIndex(x => x.id === a.id) === i);
}
