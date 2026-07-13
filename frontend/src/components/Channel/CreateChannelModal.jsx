import { useState } from 'react';
import { motion } from 'framer-motion';
import { useTranslation } from '../../i18n';
import * as api from '../../services/api';

export default function CreateChannelModal({ onClose, onCreate }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const t = useTranslation();

  const handleCreate = async () => {
    if (!name.trim() || creating) return;
    setCreating(true);
    try {
      const ch = await api.createChannel({ name: name.trim(), description: desc.trim() });
      onCreate(ch.id);
    } catch (e) {
      alert('Failed to create channel: ' + e.message);
    }
    setCreating(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-2xl shadow-card-lg border border-[#e2ddd7] w-[340px] max-w-[90vw] p-5"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-base font-bold text-[#1d1d1d] mb-1">{t('channel.create_title')}</h3>
        <p className="text-xs text-[#5c5c5c] mb-4">{t('channel.create_desc')}</p>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={t('channel.name_placeholder')}
          className="w-full px-3 py-2 rounded-xl border border-[#e2ddd7] text-sm text-[#1d1d1d] bg-white focus:outline-none focus:ring-2 focus:ring-[#4a154b]/20 focus:border-[#4a154b] mb-3"
          autoFocus
          onKeyDown={e => e.key === 'Enter' && handleCreate()}
        />
        <input
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder={t('channel.description_placeholder')}
          className="w-full px-3 py-2 rounded-xl border border-[#e2ddd7] text-sm text-[#1d1d1d] bg-white focus:outline-none focus:ring-2 focus:ring-[#4a154b]/20 focus:border-[#4a154b] mb-4"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold text-[#5c5c5c] hover:bg-gray-100">
            {t('channel.cancel')}
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="px-4 py-2 rounded-xl bg-[#4a154b] text-white text-xs font-semibold disabled:opacity-50"
          >
            {creating ? t('channel.creating') : t('channel.create_btn')}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
