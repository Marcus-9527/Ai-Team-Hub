import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Sparkles, Send } from 'lucide-react';
import { useTranslation } from '../../i18n';
import * as api from '../../services/api';

const STARTERS = [
  { icon: '🚀', key: 'newtopic.starter1', hint: 'newtopic.starter1_hint' },
  { icon: '🔍', key: 'newtopic.starter2', hint: 'newtopic.starter2_hint' },
  { icon: '💡', key: 'newtopic.starter3', hint: 'newtopic.starter3_hint' },
  { icon: '📊', key: 'newtopic.starter4', hint: 'newtopic.starter4_hint' },
];

export default function NewTopicPage({ setChannelId, triggerRefresh, refreshKey }) {
  const t = useTranslation();
  const [input, setInput] = useState('');
  const [channels, setChannels] = useState([]);

  useEffect(() => {
    api.listChannels().then(setChannels).catch(() => {});
  }, []);

  const handleSubmit = async (text) => {
    const content = text?.trim() || input.trim();
    if (!content) return;

    try {
      // Find or create a channel for this topic
      let ch = channels.find(c => c.name === content.slice(0, 20));
      if (!ch) {
        ch = await api.createChannel({
          name: content.slice(0, 20) || 'New Topic',
          description: content.slice(0, 100),
        });
      }
      setChannelId(ch.id);
      triggerRefresh();
    } catch (e) {
      console.error('Create topic failed:', e);
    }
  };

  const handleStarterClick = (key) => {
    handleSubmit(t(key));
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-canvas overflow-hidden">
      {/* Orange accent bar */}
      <div className="h-1 bg-gradient-to-r from-[#F87500]/80 via-[#F87500]/40 to-transparent flex-shrink-0" />

      <div className="flex-1 flex flex-col items-center justify-center px-6 overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16,1,0.3,1] }}
          className="w-full max-w-2xl"
        >
          {/* Logo area */}
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-[#F87500]/10 flex items-center justify-center">
              <Sparkles size={20} className="text-[#F87500]" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-ink tracking-tight">{t('newtopic.title')}</h1>
              <p className="text-sm text-ink-mute">{t('newtopic.subtitle')}</p>
            </div>
          </div>

          {/* Input */}
          <div className="relative mb-6">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
              placeholder={t('newtopic.placeholder')}
              rows={3}
              className="w-full px-5 py-4 pr-14 rounded-2xl bg-surface border border-hairline text-sm text-ink placeholder-ink-faint/50 resize-none focus:outline-none focus:border-[#F87500]/30 focus:ring-2 focus:ring-[#F87500]/10 transition-all"
              autoFocus
            />
            <motion.button
              whileTap={{ scale: 0.9 }}
              onClick={() => handleSubmit()}
              disabled={!input.trim()}
              className="absolute right-3 bottom-3 w-9 h-9 rounded-xl bg-[#F87500] text-white flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all hover:bg-[#E06A00] shadow-sm"
            >
              <Send size={15} />
            </motion.button>
          </div>

          {/* Starters */}
          <div className="grid grid-cols-2 gap-2">
            {STARTERS.map((s, i) => (
              <motion.button
                key={s.key}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 + i * 0.05, duration: 0.3 }}
                whileHover={{ scale: 1.02, y: -1 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => handleStarterClick(s.key)}
                className="flex items-start gap-3 p-3.5 rounded-xl bg-surface border border-hairline hover:border-[#F87500]/20 hover:shadow-sm text-left transition-all group"
              >
                <span className="text-lg flex-shrink-0 leading-none mt-0.5">{s.icon}</span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink group-hover:text-[#F87500] transition-colors">{t(s.key)}</p>
                  <p className="text-[11px] text-ink-faint mt-0.5">{t(s.hint)}</p>
                </div>
              </motion.button>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
