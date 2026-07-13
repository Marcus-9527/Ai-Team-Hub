import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FolderKanban, FileText, GitCommit, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronRight, Code, Terminal, ExternalLink } from 'lucide-react';
import * as api from '../../services/api';

const BASE = import.meta.env.VITE_API_BASE || '';

const STATUS_COLORS = {
  COMPLETED: 'text-green-600 bg-green-50 border-green-200',
  FAILED: 'text-red-500 bg-red-50 border-red-200',
  RUNNING: 'text-blue-600 bg-blue-50 border-blue-200',
  EXECUTING: 'text-blue-600 bg-blue-50 border-blue-200',
  PLANNING: 'text-yellow-600 bg-yellow-50 border-yellow-200',
  CREATED: 'text-gray-500 bg-gray-50 border-gray-200',
  PENDING: 'text-yellow-600 bg-yellow-50 border-yellow-200',
};

export default function WorkspaceExplorer() {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});
  const [artifactsMap, setArtifactsMap] = useState({});

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      // Fetch recent tasks
      const resp = await fetch(`${BASE}/api/tasks?limit=20`);
      const data = await resp.json();
      setTasks(data.tasks || data || []);

      // Pre-load artifacts for each task
      const list = data.tasks || data || [];
      const map = {};
      await Promise.all(list.slice(0, 10).map(async (t) => {
        try {
          const a = await api.listArtifacts(t.id || t.task_id, '', 10);
          map[t.id] = a.artifacts || [];
        } catch { map[t.id] = []; }
      }));
      setArtifactsMap(map);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const toggleTask = (taskId) => {
    setExpanded(prev => ({ ...prev, [taskId]: !prev[taskId] }));
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-9 h-9 rounded-xl bg-canvas-lavender flex items-center justify-center">
            <FolderKanban size={18} className="text-primary" />
          </div>
          <div>
            <h1 className="font-bold text-lg text-ink">Workspace Explorer</h1>
            <p className="text-xs text-ink-faint">任务产出、文件变更与交付物</p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={24} className="animate-spin text-ink-faint" /></div>
        ) : tasks.length === 0 ? (
          <div className="bg-white rounded-xl border border-hairline p-8 text-center">
            <FolderKanban size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">暂无任务</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task, i) => {
              const taskId = task.id || task.task_id;
              const isOpen = expanded[taskId];
              const artys = artifactsMap[taskId] || [];
              const files = task.files_changed || [];
              const commands = task.commands_run || [];

              return (
                <motion.div
                  key={taskId}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 0, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="bg-white rounded-xl border border-hairline overflow-hidden"
                >
                  {/* Task header */}
                  <button
                    onClick={() => toggleTask(taskId)}
                    className="w-full flex items-center gap-3 p-4 hover:bg-gray-50/50 transition-all text-left"
                  >
                    <div className="flex-shrink-0">
                      {isOpen ? <ChevronDown size={14} className="text-ink-faint" /> : <ChevronRight size={14} className="text-ink-faint" />}
                    </div>
                    <span className={`px-2 py-0.5 rounded-full text-[9px] font-medium border ${STATUS_COLORS[task.status] || 'text-gray-500 bg-gray-50 border-gray-200'}`}>
                      {task.status || '-'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-semibold text-ink">{task.title || taskId?.slice(0, 20) || 'Untitled'}</span>
                      {task.description && <p className="text-[10px] text-ink-faint truncate mt-0.5">{task.description}</p>}
                    </div>
                    {task.git_commit && (
                      <span className="text-[9px] font-mono text-ink-faint bg-gray-100 px-1.5 py-0.5 rounded flex-shrink-0">
                        {task.git_commit.slice(0, 8)}
                      </span>
                    )}
                  </button>

                  {/* Expanded details */}
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      className="border-t border-hairline bg-gray-50/30"
                    >
                      <div className="p-4 space-y-3">
                        {/* Files Changed */}
                        {files.length > 0 && (
                          <Section title="文件变更" icon={FileText}>
                            <div className="space-y-1">
                              {files.map((f, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs text-ink-mute">
                                  <Code size={10} className="flex-shrink-0" />
                                  <span className="font-mono">{f}</span>
                                </div>
                              ))}
                            </div>
                          </Section>
                        )}

                        {/* Git Commit */}
                        {task.git_commit && (
                          <Section title="Git Commit" icon={GitCommit}>
                            <span className="text-xs font-mono text-ink-mute">{task.git_commit}</span>
                          </Section>
                        )}

                        {/* Commands Run */}
                        {commands.length > 0 && (
                          <Section title="执行命令" icon={Terminal}>
                            <div className="space-y-1">
                              {commands.map((c, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs text-ink-mute">
                                  <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">$ {c}</span>
                                </div>
                              ))}
                            </div>
                          </Section>
                        )}

                        {/* Test Result */}
                        {task.test_result && (
                          <Section title="测试结果" icon={CheckCircle2}>
                            <pre className="text-[10px] text-ink-mute bg-gray-100 p-2 rounded-lg font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                              {task.test_result}
                            </pre>
                          </Section>
                        )}

                        {/* Review Comments */}
                        {task.review_comments && (
                          <Section title="Review 意见" icon={ExternalLink}>
                            <p className="text-xs text-ink-mute">{task.review_comments}</p>
                          </Section>
                        )}

                        {/* Artifacts */}
                        {artys.length > 0 && (
                          <Section title={`交付物 (${artys.length})`} icon={ExternalLink}>
                            <div className="space-y-1">
                              {artys.map((a, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs text-ink-mute">
                                  <span className="font-mono">{a.filename || a.name || a.id?.slice(0, 16)}</span>
                                  {a.type && <span className="text-[9px] px-1 py-0.5 rounded bg-gray-100">{(a.type)}</span>}
                                </div>
                              ))}
                            </div>
                          </Section>
                        )}

                        {/* Empty state */}
                        {files.length === 0 && !task.git_commit && commands.length === 0 && !task.test_result && artys.length === 0 && (
                          <p className="text-xs text-ink-faint text-center py-4">该任务还没有产出数据</p>
                        )}
                      </div>
                    </motion.div>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={12} className="text-ink-faint" />
        <span className="text-[10px] font-semibold text-ink-faint uppercase tracking-wider">{title}</span>
      </div>
      {children}
    </div>
  );
}
