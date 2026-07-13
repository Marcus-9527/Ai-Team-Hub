import { motion } from 'framer-motion';
import { X } from 'lucide-react';
import TeammateProfile from '../Teammate/TeammateProfile';

export default function TeammateProfileModal({ teammate, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[420px] max-w-[92vw] max-h-[85vh] overflow-y-auto p-0"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-3 border-b border-hairline">
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-hover transition-all">
            <X size={16} className="text-ink-faint" />
          </button>
        </div>
        {teammate && <TeammateProfile teammateId={teammate.id} compact />}
      </motion.div>
    </div>
  );
}
