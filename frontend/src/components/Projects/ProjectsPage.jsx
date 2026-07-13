import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FolderKanban, Hash, Plus, Loader2 } from 'lucide-react';
import * as api from '../../services/api';
import * as taskApi from '../../services/api/task';
import { useTranslation } from '../../i18n';

export default function ProjectsPage({ lang }) {
  const t = useTranslation();
  const [channels, setChannels] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [ch, ts] = await Promise.all([
          api.listChannels(),
          taskApi.listTasks().catch(() => []),
        ]);
        setChannels(ch);
        setTasks(Array.isArray(ts) ? ts : []);
      } catch (e) { console.error(e); }
      setLoading(false);
    })();
  }, []);

  // Group tasks by... nothing fancy, just show channels as projects
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        <h1 className="text-xl font-bold text-ink">项目</h1>
        <p className="text-xs text-ink-faint -mt-3">对话频道和任务按项目组织</p>

        {loading ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={24} className="animate-spin text-ink-faint" /></div>
        ) : channels.length === 0 ? (
          <div className="bg-white rounded-xl border border-hairline p-8 text-center">
            <FolderKanban size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">还没有项目，开始对话时自动创建</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {channels.map(ch => {
              const channelTaskCount = tasks.filter(t => t.channel_id === ch.id).length;
              return (
                <motion.div
                  key={ch.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-xl border border-hairline p-4 hover:shadow-sm transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                      <Hash size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-sm text-ink">{ch.name}</h3>
                      {ch.description && (
                        <p className="text-[11px] text-ink-faint truncate">{ch.description}</p>
                      )}
                    </div>
                    <div className="text-right">
                      <div className="text-xs font-semibold text-ink">{channelTaskCount}</div>
                      <div className="text-[10px] text-ink-faint">任务</div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
