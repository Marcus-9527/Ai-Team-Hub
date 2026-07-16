import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Users, X, Check } from 'lucide-react';
import * as api from '../../services/api';

export default function ManageTeammatesModal({ channelId, channel, onClose, onSaved }) {
  const [allTeammates, setAllTeammates] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.listTeammates()
      .then(tms => {
        setAllTeammates(tms);
        setSelected(new Set(channel?.teammate_ids || []));
      })
      .catch(() => {});
  }, [channelId, channel]);

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    const current = new Set(channel?.teammate_ids || []);
    try {
      const toAdd = [...selected].filter(id => !current.has(id));
      const toRemove = [...current].filter(id => !selected.has(id));
      await Promise.all([
        ...toAdd.map(id => api.addTeammateToChannel(channelId, id)),
        ...toRemove.map(id => api.removeTeammateFromChannel(channelId, id)),
      ]);
      onSaved?.();
      onClose();
    } catch (e) {
      console.error('Failed to manage teammates:', e);
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-2xl shadow-card-lg border border-[#e2ddd7] w-[380px] max-w-[90vw] flex flex-col max-h-[80vh]"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#e2ddd7]">
          <Users size={16} className="text-[#4a154b]" />
          <h3 className="text-sm font-bold text-[#1d1d1d]">管理队友 — {channel?.name}</h3>
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-gray-100 text-[#9ca3af]"><X size={14} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1">
          {allTeammates.length === 0 && (
            <p className="text-xs text-[#9ca3af] text-center py-8">暂无队友，请在侧边栏创建</p>
          )}
          {allTeammates.map(tm => (
            <button
              key={tm.id}
              onClick={() => toggle(tm.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left transition-all ${
                selected.has(tm.id)
                  ? 'bg-[#4a154b]/5 border border-[#4a154b]/20'
                  : 'hover:bg-gray-50 border border-transparent'
              }`}
            >
              <span className="text-base flex-shrink-0">{tm.avatar_emoji || '🤖'}</span>
              <span className="flex-1 font-medium text-[#1d1d1d] truncate">{tm.name}</span>
              {selected.has(tm.id) && <Check size={14} className="text-[#4a154b] flex-shrink-0" />}
            </button>
          ))}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[#e2ddd7]">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold text-[#5c5c5c] hover:bg-gray-100">取消</button>
          <button onClick={handleSave} disabled={saving}
            className="px-4 py-2 rounded-xl bg-[#4a154b] text-white text-xs font-semibold disabled:opacity-50"
          >{saving ? '保存中...' : '保存'}</button>
        </div>
      </motion.div>
    </div>
  );
}
