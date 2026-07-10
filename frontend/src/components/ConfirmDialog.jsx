import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, X } from 'lucide-react';

/**
 * 确认弹窗 — 水平居中，覆盖原生 confirm()
 */
export default function ConfirmDialog({ state }) {
  const [dialog, setDialog] = state;

  const handleConfirm = async () => {
    if (dialog?.onConfirm) {
      await dialog.onConfirm();
    }
    setDialog(null);
  };

  return (
    <AnimatePresence>
      {dialog && (
        <motion.div
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setDialog(null)}
          />

          {/* Dialog */}
          <motion.div
            className="relative w-full max-w-sm mx-4 bg-surface border border-hairline rounded-2xl shadow-card-lg p-6"
            initial={{ scale: 0.92, opacity: 0, y: 8 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.92, opacity: 0, y: 8 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300, mass: 0.8 }}
          >
            {/* Close button */}
            <button
              onClick={() => setDialog(null)}
              className="absolute top-3 right-3 p-1 rounded-lg text-ink-faint hover:text-ink-mute hover:bg-surface-hover transition-all"
            >
              <X size={16} />
            </button>

            {/* Icon */}
            <div className="w-10 h-10 rounded-full bg-semantic-error/10 flex items-center justify-center mb-4">
              <AlertTriangle size={20} className="text-semantic-error" />
            </div>

            {/* Title */}
            <h3 className="text-ink font-bold text-[15px] mb-2">
              {dialog?.title || '确认'}
            </h3>

            {/* Message */}
            <p className="text-sm text-ink-mute leading-relaxed mb-6">
              {dialog?.message || ''}
            </p>

            {/* Buttons */}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDialog(null)}
                className="px-4 py-2 rounded-pill text-sm font-semibold text-ink-mute hover:text-ink bg-surface-hover hover:bg-surface-active transition-all"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                className="px-4 py-2 rounded-pill text-sm font-semibold text-white bg-primary hover:bg-primary-press shadow-md hover:shadow-lg transition-all"
              >
                {dialog?.confirmText || '确认删除'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
