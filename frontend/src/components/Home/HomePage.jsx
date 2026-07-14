import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  ListTodo, Users, MessageSquare, Plus, Loader2,
  ArrowRight, CheckCircle2, PlayCircle, FolderKanban,
} from 'lucide-react';
import * as api from '../../services/api';
import * as taskApi from '../../services/api/task';
import { useTranslation } from '../../i18n';

export default function HomePage({ onNavigate, triggerRefresh, refreshKey, lang }) {
  const t = useTranslation();
  const [tasks, setTasks] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showQuickTask, setShowQuickTask] = useState(false);
  const [quickTitle, setQuickTitle] = useState('');

  useEffect(() => { load(); }, [refreshKey]);

  const load = async () => {
    setLoading(true);
    try {
      const [ts, tm, ch] = await Promise.all([
        taskApi.listTasks().catch(() => []),
        api.listTeammates().catch(() => []),
        api.listChannels().catch(() => []),
      ]);
      setTasks(Array.isArray(ts) ? ts : []);
      setTeammates(tm);
      setChannels(ch);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const recentTasks = tasks.slice(0, 5);
  const recentProjects = channels.slice(0, 5);
  const ongoingTasks = tasks.filter(t => t.status === 'EXECUTING' || t.status === 'PLANNING').length;
  const completedTasks = tasks.filter(t => t.status === 'COMPLETED').length;

  const createQuickTask = async () => {
    if (!quickTitle.trim()) return;
    try {
      const task = await taskApi.createTask({ title: quickTitle.trim(), description: '', priority: 2 });
      setQuickTitle('');
      setShowQuickTask(false);
      onNavigate('tasks');
    } catch (e) { alert('创建失败: ' + e.message); }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">

        {/* Greeting + Stats */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-ink">概览</h1>
          <div className="flex gap-2 text-xs text-ink-faint">
            <span>{teammates.length} 个队友</span>
            <span>·</span>
            <span>{channels.length} 个频道</span>
          </div>
        </div>

        {/* Quick stat cards */}
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: '运行中', value: ongoingTasks, icon: PlayCircle, color: 'bg-blue-100 text-blue-600' },
            { label: '已完成', value: completedTasks, icon: CheckCircle2, color: 'bg-green-100 text-green-600' },
            { label: '总计', value: tasks.length, icon: ListTodo, color: 'bg-indigo-100 text-indigo-600' },
          ].map(({ label, value, icon: Icon, color }) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-white rounded-xl border border-hairline p-4"
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center mb-2 ${color}`}>
                <Icon size={15} />
              </div>
              <div className="text-lg font-bold text-ink">{value}</div>
              <div className="text-[11px] text-ink-faint">{label}</div>
            </motion.div>
          ))}
        </div>

        {/* Quick actions */}
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => onNavigate('chat')}
            className="flex items-center gap-3 p-4 bg-white rounded-xl border border-hairline hover:border-primary/20 hover:shadow-sm transition-all text-left"
          >
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
              <MessageSquare size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink">开始对话</p>
              <p className="text-[11px] text-ink-faint">和 AI 团队交流</p>
            </div>
            <ArrowRight size={16} className="text-ink-faint" />
          </button>

          <button
            onClick={() => setShowQuickTask(true)}
            className="flex items-center gap-3 p-4 bg-white rounded-xl border border-hairline hover:border-primary/20 hover:shadow-sm transition-all text-left"
          >
            <div className="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center text-amber-600">
              <Plus size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink">快速创建任务</p>
              <p className="text-[11px] text-ink-faint">一句话描述</p>
            </div>
            <ArrowRight size={16} className="text-ink-faint" />
          </button>
        </div>

        {/* Recent projects */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink">最近项目</h2>
            <button onClick={() => onNavigate('projects')} className="text-xs text-primary hover:underline">
              查看全部
            </button>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-6"><Loader2 size={18} className="animate-spin text-ink-faint" /></div>
          ) : recentProjects.length === 0 ? (
            <div className="bg-white rounded-xl border border-hairline p-6 text-center">
              <FolderKanban size={28} className="mx-auto mb-2 text-ink-faint/30" />
              <p className="text-xs text-ink-faint">还没有项目</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {recentProjects.map(ch => (
                <button
                  key={ch.id}
                  onClick={() => onNavigate('chat')}
                  className="flex items-center gap-2 bg-white rounded-xl border border-hairline p-3 text-left hover:shadow-sm transition-all"
                >
                  <span className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
                    <FolderKanban size={15} />
                  </span>
                  <span className="text-sm text-ink truncate flex-1">{ch.name}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Recent tasks */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink">最近任务</h2>
            <button onClick={() => onNavigate('tasks')} className="text-xs text-primary hover:underline">
              查看全部
            </button>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-8"><Loader2 size={20} className="animate-spin text-ink-faint" /></div>
          ) : recentTasks.length === 0 ? (
            <div className="bg-white rounded-xl border border-hairline p-6 text-center">
              <ListTodo size={32} className="mx-auto mb-2 text-ink-faint/30" />
              <p className="text-xs text-ink-faint">还没有任务</p>
            </div>
          ) : (
            <div className="space-y-2">
              {recentTasks.map(task => (
                <div
                  key={task.id}
                  onClick={() => onNavigate('tasks')}
                  className="flex items-center gap-3 bg-white rounded-xl border border-hairline p-3 cursor-pointer hover:shadow-sm transition-all"
                >
                  <div className={`w-2 h-2 rounded-full ${
                    task.status === 'COMPLETED' ? 'bg-green-400' :
                    task.status === 'FAILED' ? 'bg-red-400' :
                    task.status === 'EXECUTING' ? 'bg-blue-400' : 'bg-gray-300'
                  }`} />
                  <span className="text-sm text-ink truncate flex-1">{task.title}</span>
                  <span className="text-[10px] text-ink-faint whitespace-nowrap">
                    {task.status === 'COMPLETED' ? '已完成' :
                     task.status === 'EXECUTING' ? '执行中' :
                     task.status === 'FAILED' ? '失败' : '待处理'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Team status */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink">AI 团队</h2>
            <button onClick={() => onNavigate('team')} className="text-xs text-primary hover:underline">
              查看全部
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {teammates.length === 0 ? (
              <p className="text-xs text-ink-faint">还没有队友</p>
            ) : (
              teammates.map(tm => (
                <div key={tm.id} className="flex items-center gap-2 px-3 py-1.5 bg-white rounded-full border border-hairline text-xs">
                  <span>{tm.avatar_emoji || '🤖'}</span>
                  <span className="font-medium text-ink">{tm.name}</span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* Quick task modal */}
      {showQuickTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={() => setShowQuickTask(false)}>
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[380px] max-w-[90vw] p-5"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-base font-bold text-ink mb-1">快速创建任务</h3>
            <input
              value={quickTitle}
              onChange={e => setQuickTitle(e.target.value)}
              placeholder={t('task.title_ph')}
              className="w-full px-3 py-2 mt-3 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              autoFocus
              onKeyDown={e => e.key === 'Enter' && createQuickTask()}
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowQuickTask(false)} className="px-4 py-2 rounded-xl text-xs font-semibold text-ink-mute hover:bg-gray-100">
                取消
              </button>
              <button
                onClick={createQuickTask}
                disabled={!quickTitle.trim()}
                className="px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold disabled:opacity-50"
              >
                创建
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
