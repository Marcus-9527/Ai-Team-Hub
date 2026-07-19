import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FileText, Download, Clock, Loader2, FileCode, FileImage, File } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';

const FILE_ICONS = {
  'code': FileCode,
  'image': FileImage,
  'text': FileText,
};

export default function ResultsPage({ lang }) {
  const t = useTranslation();
  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.listArtifacts();
        setArtifacts(Array.isArray(data) ? data : data?.items || []);
      } catch (e) { console.error(e); }
      setLoading(false);
    })();
  }, []);

  // Fallback: try files endpoint
  useEffect(() => {
    if (!loading && artifacts.length === 0) {
      (async () => {
        try {
          const BASE = import.meta.env.VITE_API_BASE || '';
          const res = await fetch(`${BASE}/v1/files`);
          if (res.ok) {
            const data = await res.json();
            setArtifacts(Array.isArray(data) ? data : []);
          }
        } catch (e) { /* ignore */ }
      })();
    }
  }, [loading]);

  const formatDate = (d) => {
    if (!d) return '';
    try { return new Date(d).toLocaleString('zh-CN'); } catch { return ''; }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        <h1 className="text-xl font-bold text-ink">结果与文件</h1>
        <p className="text-xs text-ink-faint -mt-3">任务产生的文件和报告</p>

        {loading ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={24} className="animate-spin text-ink-faint" /></div>
        ) : artifacts.length === 0 ? (
          <div className="bg-white rounded-xl border border-hairline p-8 text-center">
            <FileText size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">还没有结果</p>
            <p className="text-xs text-ink-faint mt-1">完成任务后，结果会出现在这里</p>
          </div>
        ) : (
          <div className="grid gap-2">
            {artifacts.map((a, i) => {
              const Icon = FILE_ICONS[a.type] || File;
              return (
                <motion.div
                  key={a.id || i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="flex items-center gap-3 bg-white rounded-xl border border-hairline p-3 hover:shadow-sm transition-all group"
                >
                  <div className="w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center text-gray-500">
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-ink truncate">{a.filename || a.name || `结果 #${i + 1}`}</p>
                    <div className="flex items-center gap-2 text-[10px] text-ink-faint mt-0.5">
                      <span>{a.type || 'file'}</span>
                      {a.created_at && (
                        <>
                          <span>·</span>
                          <Clock size={10} className="inline" />
                          <span>{formatDate(a.created_at)}</span>
                        </>
                      )}
                    </div>
                  </div>
                  {a.download_url || a.content_url ? (
                    <a
                      href={a.download_url || a.content_url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-2 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-gray-100 transition-all"
                    >
                      <Download size={14} className="text-ink-faint" />
                    </a>
                  ) : null}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
