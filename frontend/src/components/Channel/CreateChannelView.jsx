import { useState } from 'react';
import { motion } from 'framer-motion';
import { Hash, ArrowLeft, Sparkles } from 'lucide-react';
import { useTranslation } from '../../i18n';
import * as api from '../../services/api';

export default function CreateChannelView({ onDone, onCancel }) {
  const t = useTranslation();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError(t('channel.name_required')); return; }
    setSaving(true);
    setError('');
    try {
      const ch = await api.createChannel({ name: name.trim(), description: description.trim() });
      onDone(ch);
    } catch (err) {
      setError(err.message || 'Failed');
      setSaving(false);
    }
  };

  const presets = [
    { name: 'feature-planning', desc: 'Plan and scope new features', emoji: '🚀' },
    { name: 'code-review', desc: 'Code reviews and PR discussions', emoji: '🔍' },
    { name: 'debug-war-room', desc: 'Urgent debugging sessions', emoji: '🛠️' },
    { name: 'design-system', desc: 'UI/UX and design system work', emoji: '🎨' },
    { name: 'architecture', desc: 'System architecture discussions', emoji: '🏗️' },
    { name: 'data-analysis', desc: 'Data exploration and insights', emoji: '📊' },
  ];

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex-1 overflow-y-auto bg-canvas">
      <div className="max-w-xl mx-auto px-8 py-12">
        <motion.div initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.05 }}
          className="flex items-center gap-4 mb-10">
          <button onClick={onCancel} className="w-10 h-10 rounded-xl hover:bg-surface-hover flex items-center justify-center">
            <ArrowLeft size={20} className="text-ink-mute" />
          </button>
          <div>
            <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">{t('channel.create_title')}</h1>
            <p className="text-sm text-ink-mute mt-0.5">{t('channel.create_desc')}</p>
          </div>
        </motion.div>

        <motion.form initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.1 }}
          onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="flex items-center gap-2 text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">
              <Hash size={13} /> {t('channel.name')}
            </label>
            <input value={name} onChange={e => { setName(e.target.value); setError(''); }}
              placeholder={t('channel.name_placeholder')}
              className="w-full px-4 py-3.5 rounded-xl bg-surface border border-hairline text-lg font-semibold focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary/30 transition-all placeholder:text-ink-faint/50" autoFocus />
          </div>
          <div>
            <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">{t('channel.description')}</label>
            <input value={description} onChange={e => setDescription(e.target.value)}
              placeholder={t('channel.description_placeholder')}
              className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10 transition-all placeholder:text-ink-faint/50" />
          </div>
          {error && <motion.p initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="text-xs text-semantic-error bg-red-50 rounded-xl px-4 py-2.5">{error}</motion.p>}
          <div className="flex gap-3 pt-2">
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} type="submit" disabled={saving}
              className="flex-1 px-8 py-3.5 bg-primary text-white font-semibold text-sm rounded-pill shadow-md hover:shadow-lg disabled:opacity-50 transition-all flex items-center justify-center gap-2">
              {saving ? <><motion.div animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}><Sparkles size={16} /></motion.div>{t('channel.creating')}</> : <><Hash size={16} /> {t('channel.create_btn')}</>}
            </motion.button>
            <button type="button" onClick={onCancel} className="px-6 py-3.5 text-sm font-semibold text-ink-mute hover:text-ink">{t('channel.cancel')}</button>
          </div>
        </motion.form>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }} className="mt-12">
          <p className="text-xs font-semibold text-ink-faint uppercase tracking-wide mb-3">{t('channel.quick_presets')}</p>
          <div className="grid grid-cols-2 gap-2">
            {presets.map(p => (
              <motion.button key={p.name} whileHover={{ scale: 1.02, y: -1 }} whileTap={{ scale: 0.97 }} type="button"
                onClick={() => { setName(p.name); setDescription(p.desc); }}
                className="flex items-center gap-3 p-3 rounded-xl bg-surface border border-hairline hover:border-primary/20 hover:shadow-sm text-left transition-all group">
                <span className="text-lg">{p.emoji}</span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink font-mono text-xs truncate">#{p.name}</p>
                  <p className="text-[11px] text-ink-mute truncate">{p.desc}</p>
                </div>
              </motion.button>
            ))}
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
}
