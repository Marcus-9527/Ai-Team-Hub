import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Inbox, Hash, Loader2, MessageSquare } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';

/**
 * Inbox — aggregates recent messages across all channels into one feed,
 * so "收件箱" is a real view (not a fallback to Home). Click a row to jump
 * into that channel's chat.
 */
export default function InboxPage({ onNavigate, setChannelId }) {
  const t = useTranslation();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const channels = await api.listChannels();
      const perChannel = await Promise.all(
        channels.map(async (ch) => {
          try {
            const msgs = await api.listMessages(ch.id);
            const last = msgs[msgs.length - 1];
            return {
              channel: ch,
              count: msgs.length,
              last,
              preview: last ? last.content : '',
              at: last ? last.created_at : ch.created_at,
            };
          } catch {
            return { channel: ch, count: 0, last: null, preview: '', at: ch.created_at };
          }
        })
      );
      perChannel.sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0));
      setItems(perChannel);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const open = (ch) => {
    setChannelId?.(ch.id);
    onNavigate?.('chat');
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-ink">{t('sidebar.inbox')}</h1>
          <span className="text-xs text-ink-faint">{items.length} 个频道</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={24} className="animate-spin text-ink-faint" />
          </div>
        ) : items.length === 0 ? (
          <div className="bg-white rounded-xl border border-hairline p-8 text-center">
            <Inbox size={40} className="mx-auto mb-3 text-ink-faint/30" />
            <p className="text-sm text-ink-faint">还没有任何消息</p>
          </div>
        ) : (
          <div className="space-y-2">
            {items.map(({ channel, count, preview, at }) => (
              <motion.button
                key={channel.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                onClick={() => open(channel)}
                className="w-full flex items-center gap-3 bg-white rounded-xl border border-hairline p-4 text-left hover:border-primary/20 hover:shadow-sm transition-all"
              >
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
                  <Hash size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-ink truncate">{channel.name}</p>
                    <span className="text-[10px] text-ink-faint bg-gray-100 rounded-full px-2 py-0.5">{count}</span>
                  </div>
                  <p className="text-[11px] text-ink-faint truncate mt-0.5">
                    {preview || '暂无消息'}
                  </p>
                </div>
                {at && (
                  <span className="text-[10px] text-ink-faint whitespace-nowrap">
                    {new Date(at).toLocaleDateString('zh-CN')}
                  </span>
                )}
              </motion.button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
