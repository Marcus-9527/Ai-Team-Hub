import { motion } from 'framer-motion';
import { Bot, Users, Hash, Sparkles } from 'lucide-react';
import { useTranslation } from '../../i18n';

export default function WelcomeView({ onCreateChannel }) {
  const t = useTranslation();

  return (
    <div className="flex-1 flex items-center justify-center bg-canvas">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="text-center max-w-md px-8"
      >
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: 0.1, duration: 0.5 }}
          className="w-20 h-20 mx-auto mb-8 rounded-2xl bg-primary flex items-center justify-center shadow-glow-aubergine"
        >
          <Bot size={36} className="text-white" />
        </motion.div>

        <h1 className="text-[28px] font-extrabold text-ink leading-tight tracking-[-0.02em] mb-3">
          {t('welcome.title')}
        </h1>
        <p className="text-ink-mute text-[15px] leading-relaxed mb-10">
          {t('welcome.subtitle')}
        </p>

        <div className="grid grid-cols-3 gap-3 mb-8">
          <QuickCard icon={<Hash size={20} />} title={t('welcome.channels')} desc={t('welcome.channels_desc')} delay={0.2} />
          <QuickCard icon={<Users size={20} />} title={t('welcome.teammates')} desc={t('welcome.teammates_desc')} delay={0.3} />
          <QuickCard icon={<Sparkles size={20} />} title={t('welcome.collaborate')} desc={t('welcome.collaborate_desc')} delay={0.4} />
        </div>

        <motion.button
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          onClick={onCreateChannel}
          className="px-8 py-3 bg-primary text-white font-semibold text-sm rounded-pill
                     shadow-md hover:bg-primary-press hover:shadow-lg
                     active:scale-95 transition-all duration-150"
        >
          {t('welcome.create_channel')}
        </motion.button>
      </motion.div>
    </div>
  );
}

function QuickCard({ icon, title, desc, delay }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="p-4 rounded-xl bg-surface border border-hairline hover:border-primary/10
                 hover:shadow-card transition-all duration-200 cursor-default"
    >
      <div className="w-10 h-10 mx-auto mb-2 rounded-lg bg-canvas-lavender flex items-center justify-center text-primary">
        {icon}
      </div>
      <p className="text-xs font-semibold text-ink">{title}</p>
      <p className="text-[11px] text-ink-faint mt-0.5">{desc}</p>
    </motion.div>
  );
}
