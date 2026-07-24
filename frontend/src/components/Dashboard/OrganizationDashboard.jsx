/**
 * OrganizationDashboard.jsx — Phase 8.0
 *
 * Product-level view of the AI team: members, runs, tasks, growth.
 * "This is an AI team, not a chat window."
 */
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Users, Activity, CheckCircle2, TrendingUp, Brain,
  Loader2, UserCheck, Cpu, Award, BarChart3,
  Play, Pause, XCircle, ExternalLink, ChevronRight,
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
        <span className="text-xs font-medium text-ink-faint">{label}</span>
      </div>
      <div className="text-xl font-bold text-ink">{value ?? '-'}</div>
      {sub != null && <div className="text-[10px] text-ink-faint mt-0.5">{sub}</div>}
    </motion.div>
  );
}

function MemberCard({ member, onViewProfile }) {
  const roleColors = {
    engineer: 'bg-blue-100 text-blue-600',
    techlead: 'bg-purple-100 text-purple-600',
    designer: 'bg-pink-100 text-pink-600',
    pm: 'bg-amber-100 text-amber-600',
    analyst: 'bg-teal-100 text-teal-600',
    assistant: 'bg-gray-100 text-gray-600',
  };
  const colorClass = roleColors[member.role] || roleColors.assistant;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-hairline p-4 hover:shadow-sm transition-shadow cursor-pointer"
      onClick={() => onViewProfile?.(member.id)}
    >
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold ${colorClass}`}>
          {(member.name || '?')[0]}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-ink truncate">{member.name}</p>
          <p className="text-[11px] text-ink-faint capitalize">{member.role}</p>
        </div>
        <ChevronRight size={14} className="text-ink-faint" />
      </div>
      {member.model && (
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-ink-faint">
          <Cpu size={10} />
          <span className="truncate">{member.model}</span>
        </div>
      )}
    </motion.div>
  );
}

function ProfileModal({ teammateId, onClose }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!teammateId) return;
    setLoading(true);
    api.getOrgTeammateProfile(teammateId)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
  }, [teammateId]);

  if (!teammateId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 size={24} className="animate-spin text-ink-faint" />
          </div>
        ) : profile ? (
          <div className="p-6 space-y-5">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-full bg-indigo-100 flex items-center justify-center text-lg font-bold text-indigo-600">
                  {(profile.identity?.name || '?')[0]}
                </div>
                <div>
                  <h2 className="text-lg font-bold text-ink">{profile.identity?.name}</h2>
                  <p className="text-xs text-ink-faint capitalize">{profile.identity?.role}</p>
                </div>
              </div>
              <button onClick={onClose} className="w-8 h-8 rounded-lg hover:bg-gray-100 flex items-center justify-center text-ink-faint">
                <XCircle size={18} />
              </button>
            </div>

            {/* Model info */}
            {profile.identity?.model && (
              <div className="text-xs text-ink-faint flex items-center gap-2">
                <Cpu size={12} />
                {profile.identity?.provider && <span>{profile.identity.provider}/</span>}
                <span>{profile.identity.model}</span>
              </div>
            )}

            {/* System prompt */}
            {profile.identity?.system_prompt && (
              <div>
                <p className="text-xs font-semibold text-ink mb-1">System Prompt</p>
                <p className="text-xs text-ink-faint bg-gray-50 rounded-lg p-3 leading-relaxed">{profile.identity.system_prompt}</p>
              </div>
            )}

            {/* Performance */}
            <div>
              <p className="text-xs font-semibold text-ink mb-2 flex items-center gap-1.5">
                <Activity size={12} /> 执行表现
              </p>
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-gray-50 rounded-lg p-2.5 text-center">
                  <div className="text-sm font-bold text-ink">{profile.performance?.total_actions ?? 0}</div>
                  <div className="text-[9px] text-ink-faint">总操作</div>
                </div>
                <div className="bg-green-50 rounded-lg p-2.5 text-center">
                  <div className="text-sm font-bold text-green-700">{profile.performance?.completed ?? 0}</div>
                  <div className="text-[9px] text-green-600">成功</div>
                </div>
                <div className="bg-red-50 rounded-lg p-2.5 text-center">
                  <div className="text-sm font-bold text-red-600">{profile.performance?.failed ?? 0}</div>
                  <div className="text-[9px] text-red-500">失败</div>
                </div>
              </div>
              {profile.performance?.success_rate != null && (
                <p className="text-xs text-ink-faint mt-1.5 text-center">
                  成功率 <span className="font-semibold text-green-600">{(profile.performance.success_rate * 100).toFixed(1)}%</span>
                </p>
              )}
            </div>

            {/* Capabilities */}
            {profile.capabilities?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-ink mb-2">能力</p>
                <div className="flex flex-wrap gap-1.5">
                  {profile.capabilities.map((cap, i) => (
                    <span key={i} className="text-[10px] bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full">{cap}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Skills */}
            {profile.skills?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-ink mb-2">技能</p>
                <div className="flex flex-wrap gap-1.5">
                  {profile.skills.map((s, i) => (
                    <span key={i} className="text-[10px] bg-teal-50 text-teal-600 px-2 py-0.5 rounded-full">{typeof s === 'string' ? s.slice(0, 40) : s?.content?.slice(0, 40)}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Experience */}
            {profile.experience?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-ink mb-2">相关经验</p>
                <div className="space-y-1.5">
                  {profile.experience.map((ex, i) => (
                    <div key={i} className="text-[10px] text-ink-faint bg-gray-50 rounded-lg p-2.5 leading-relaxed">
                      {ex.content}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="p-12 text-center text-sm text-ink-faint">加载失败</div>
        )}
      </div>
    </div>
  );
}

function RunCard({ run }) {
  const statusColors = {
    active: 'text-green-600 bg-green-50',
    running: 'text-blue-600 bg-blue-50',
    completed: 'text-gray-500 bg-gray-100',
    failed: 'text-red-600 bg-red-50',
    paused: 'text-amber-600 bg-amber-50',
    cancelled: 'text-gray-400 bg-gray-100',
  };
  const colorClass = statusColors[run.status] || statusColors.active;

  return (
    <div className="bg-white rounded-xl border border-hairline p-3 flex items-center gap-3">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${colorClass}`}>
        {run.status === 'active' || run.status === 'running' ? <Play size={14} /> :
         run.status === 'paused' ? <Pause size={14} /> :
         run.status === 'completed' ? <CheckCircle2 size={14} /> :
         <XCircle size={14} />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-ink truncate">{run.title || run.id.slice(0, 12)}</p>
        <p className="text-[10px] text-ink-faint">{run.run_type} · {run.id.slice(0, 8)}</p>
      </div>
      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium capitalize ${colorClass}`}>{run.status}</span>
    </div>
  );
}

export default function OrganizationDashboard({ onBack, onNavigate }) {
  const [summary, setSummary] = useState(null);
  const [activeRuns, setActiveRuns] = useState([]);
  const [completedTasks, setCompletedTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [profileId, setProfileId] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const s = await api.getOrganizationSummary();
        setSummary(s);

        // Also fetch recent runs
        try {
          const runs = await api.listOrganizationRuns(20);
          setActiveRuns((runs || []).filter(r => ['active', 'running', 'paused'].includes(r.status)).slice(0, 6));
          setCompletedTasks((runs || []).filter(r => r.status === 'completed').slice(0, 5));
        } catch (_) {
          // runs listing is optional
        }
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

  const s = summary || {};
  const activeRunsData = s.active_runs || {};
  const completedRunsData = s.completed_runs || {};
  const members = s.members || [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-6xl mx-auto p-6 space-y-6">

        {/* ── Header ── */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-100 flex items-center justify-center">
            <Users size={20} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-ink">AI 团队</h1>
            <p className="text-xs text-ink-faint">组织概览 · 成员画像 · 运行状态 · 团队成长</p>
          </div>
        </div>

        {/* ── Stat Cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard icon={Users} label="成员" value={s.member_count ?? 0} color="bg-indigo-100" />
          <StatCard icon={Activity} label="活跃运行" value={activeRunsData.count ?? 0} color="bg-blue-100" />
          <StatCard icon={CheckCircle2} label="已完成" value={completedRunsData.count ?? 0} color="bg-green-100" sub={`共 ${completedRunsData.total ?? 0} 次`} />
          <StatCard icon={TrendingUp} label="成功率" value={s.success_rate != null ? `${(s.success_rate * 100).toFixed(1)}%` : '-'} color="bg-emerald-100" />
        </div>

        {/* ── Secondary stats ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <StatCard icon={Brain} label="累积经验" value={`${s.learned_experience?.knowledge_items ?? 0} 条`} color="bg-purple-100" sub="知识记忆条目" />
          <StatCard icon={Award} label="能力覆盖" value={`${s.capabilities?.length ?? 0} 项`} color="bg-amber-100" sub={s.capabilities?.slice(0, 5).join(', ')} />
        </div>

        {/* ── Two-column content ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left: Members */}
          <div>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <UserCheck size={15} className="text-indigo-500" /> AI 成员 <span className="text-xs text-ink-faint font-normal">({members.length})</span>
            </h2>
            <div className="space-y-2">
              {members.length === 0 ? (
                <p className="text-xs text-ink-faint text-center py-8">还没有 AI 队友</p>
              ) : (
                members.map(m => (
                  <MemberCard key={m.id} member={m} onViewProfile={setProfileId} />
                ))
              )}
            </div>
          </div>

          {/* Right: Runs + Tasks */}
          <div className="space-y-6">
            {/* Active Runs */}
            <div>
              <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
                <Activity size={15} className="text-blue-500" /> 当前运行
              </h2>
              <div className="space-y-2">
                {activeRuns.length === 0 ? (
                  <p className="text-xs text-ink-faint text-center py-6">暂无活跃运行</p>
                ) : (
                  activeRuns.map(r => <RunCard key={r.id} run={r} />)
                )}
              </div>
            </div>

            {/* Completed Tasks */}
            <div>
              <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
                <CheckCircle2 size={15} className="text-green-500" /> 历史任务
              </h2>
              <div className="space-y-2">
                {completedTasks.length === 0 ? (
                  <p className="text-xs text-ink-faint text-center py-6">暂无历史任务</p>
                ) : (
                  completedTasks.slice(0, 4).map(r => <RunCard key={r.id} run={r} />)
                )}
                {(completedRunsData.count || 0) > 4 && (
                  <button
                    className="w-full text-xs text-indigo-600 hover:text-indigo-700 py-2 flex items-center justify-center gap-1"
                    onClick={() => onNavigate?.('org-run')}
                  >
                    查看全部 <ChevronRight size={12} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Team Growth Note ── */}
        <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-4 border border-indigo-100">
          <p className="text-xs text-indigo-700 leading-relaxed">
            🤖 这是一个 AI 团队 — {s.member_count ?? 0} 名成员，{s.capabilities?.length ?? 0} 项能力覆盖，
            已完成 {completedRunsData.count ?? 0} 次运行，成功率 {(s.success_rate != null ? (s.success_rate * 100).toFixed(1) : '0')}%。
            成员在持续学习，团队在持续成长。
          </p>
        </div>

      </div>

      {/* Profile Modal */}
      <ProfileModal teammateId={profileId} onClose={() => setProfileId(null)} />
    </div>
  );
}
