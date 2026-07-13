import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Users, Trash2, Loader2, TrendingUp, Bot, Pencil, Plus, Sparkles, Eye } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import ConfirmDialog from '../ConfirmDialog';
import CreateTeammateModal from '../Teammate/CreateTeammateModal';
import TeammateProfileModal from '../Profile/TeammateProfileModal';

export default function TeamPage({ lang }) {
  const t = useTranslation();
  const [teammates, setTeammates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);
  const [profileTarget, setProfileTarget] = useState(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try { setTeammates(await api.listTeammates()); }
    catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleDelete = (tm) => {
    setConfirm({
      title: '移除队友',
      message: `确定要从工作区移除「${tm.name}」吗？`,
      confirmText: '移除',
      onConfirm: async () => {
        const channels = await api.listChannels();
        for (const ch of channels) {
          if ((ch.teammate_ids || []).includes(tm.id)) {
            await api.removeTeammateFromChannel(ch.id, tm.id);
          }
        }
        await api.deleteTeammate(tm.id);
        await new Promise(r => setTimeout(r, 300));
        load();
      },
    });
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-ink">{t('nav.teammates')}</h1>
              <button
                onClick={() => { setEditing(null); setShowCreate(true); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary text-white text-xs font-semibold hover:opacity-90 transition-all"
              >
                <Plus size={14} />
                {t('teammate.create')}
              </button>
            </div>
            <p className="text-xs text-ink-faint mt-0.5">{t('team.count', teammates.length)}</p>
          </div>
        </div>

        {/* Phase 21: Team Template — One-click AI Team */}
        <QuickTeamTemplate onCreated={load} />

        {loading ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={24} className="animate-spin text-ink-faint" /></div>
        ) : teammates.length === 0 ? (
          <div className="bg-white rounded-xl border border-hairline p-8 text-center">
            <Users size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">{t('team.empty')}</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {teammates.map((tm, i) => (
              <motion.div
                key={tm.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="group bg-white rounded-xl border border-hairline p-4 hover:shadow-sm transition-all"
              >
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl bg-canvas-lavender flex items-center justify-center text-lg flex-shrink-0">
                    {tm.avatar_emoji || '🤖'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-sm text-ink">{tm.name}</h3>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-100 text-indigo-600">
                        {tm.role || t('teammate.fallback_role')}
                      </span>
                    </div>
                    <p className="text-[11px] text-ink-faint mt-1 line-clamp-2">{tm.system_prompt || ''}</p>
                    <div className="flex items-center gap-3 mt-2 text-[10px] text-ink-faint">
                      <span>{tm.model_provider}/{tm.model_name}</span>
                      {tm.created_at && (
                        <span>加入于 {new Date(tm.created_at).toLocaleDateString('zh-CN')}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1 flex-shrink-0">
                    <button
                      onClick={() => setProfileTarget(tm)}
                      className="p-1.5 rounded-lg opacity-0 group-hover:opacity-60 hover:opacity-100 hover:bg-surface-hover transition-all"
                      title="查看详情"
                    >
                      <Eye size={14} className="text-ink-faint hover:text-primary" />
                    </button>
                    <button
                      onClick={() => { setEditing(tm); setShowCreate(true); }}
                      className="p-1.5 rounded-lg opacity-0 group-hover:opacity-60 hover:opacity-100 hover:bg-surface-hover transition-all"
                    >
                      <Pencil size={14} className="text-ink-faint hover:text-primary" />
                    </button>
                    <button
                      onClick={() => handleDelete(tm)}
                      className="p-1.5 rounded-lg opacity-0 group-hover:opacity-60 hover:opacity-100 hover:bg-red-50 transition-all"
                    >
                      <Trash2 size={14} className="text-ink-faint hover:text-semantic-error" />
                    </button>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog state={[confirm, setConfirm]} />
      {showCreate && (
        <CreateTeammateModal
          teammate={editing}
          onClose={() => { setShowCreate(false); setEditing(null); }}
          onCreated={() => { setShowCreate(false); setEditing(null); load(); }}
        />
      )}
      {profileTarget && (
        <TeammateProfileModal
          teammate={profileTarget}
          onClose={() => setProfileTarget(null)}
        />
      )}
    </div>
  );
}

/* ── Quick Team Template Card ── */
function QuickTeamTemplate({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState('default');

  const handleCreate = async () => {
    setCreating(true);
    try {
      await api.createTeamFromTemplate({ template });
      alert('AI 团队创建成功！去频道里试试吧 🎉');
      if (onCreated) onCreated();
      setOpen(false);
    } catch (e) {
      alert('创建失败: ' + e.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mb-4 bg-gradient-to-r from-indigo-50/80 to-purple-50/80 rounded-xl border border-indigo-100 p-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-indigo-100 flex items-center justify-center flex-shrink-0">
          <Sparkles size={16} className="text-indigo-600" />
        </div>
        <div className="flex-1">
          <h3 className="font-semibold text-sm text-ink">一键创建 AI 团队</h3>
          <p className="text-xs text-ink-mute mt-0.5">自动创建频道 + 预配置队友角色</p>
          <div className="flex gap-2 mt-2.5">
            <button
              onClick={() => setOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 transition-all"
            >
              <Sparkles size={13} />
              快速创建
            </button>
          </div>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setOpen(false)}>
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[380px] max-w-[90vw] p-6"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-base font-bold text-ink mb-1">创建 AI 团队</h3>
            <p className="text-xs text-ink-mute mb-4">选择一个模板，快速创建频道和队友</p>

            <div className="space-y-2 mb-4">
              {[
                { id: 'default', label: '标准团队', desc: '工程师 + 产品经理 + 设计师' },
                { id: 'devops', label: 'DevOps 团队', desc: '运维工程师 + 安全审查员' },
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() => setTemplate(t.id)}
                  className={`w-full text-left p-3 rounded-xl border text-sm transition-all ${
                    template === t.id
                      ? 'border-indigo-300 bg-indigo-50/60'
                      : 'border-hairline hover:border-indigo-200 hover:bg-gray-50'
                  }`}
                >
                  <div className="font-semibold text-ink">{t.label}</div>
                  <div className="text-[11px] text-ink-faint mt-0.5">{t.desc}</div>
                </button>
              ))}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setOpen(false)}
                className="flex-1 px-4 py-2 rounded-xl border border-hairline text-xs font-semibold text-ink-mute hover:bg-gray-50 transition-all"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex-1 px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-all"
              >
                {creating ? <Loader2 size={13} className="animate-spin inline mr-1" /> : <Sparkles size={13} className="inline mr-1" />}
                创建团队
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
