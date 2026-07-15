import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Search, Code2, Briefcase, Check, Loader2 } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import { toast } from '../../services/toast';
import ConfirmDialog from '../ConfirmDialog';

const CATEGORIES = [
  { id: 'all', icon: null },
  { id: 'engineering', icon: Code2 },
  { id: 'business', icon: Briefcase },
];

const CATEGORY_EMOJI = { engineering: '⚙️', business: '💼' };

export default function TemplateGallery() {
  const t = useTranslation();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [creating, setCreating] = useState(new Set());
  const [created, setCreated] = useState(new Set());
  const [confirm, setConfirm] = useState(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.listTemplates();
      setTemplates(data);
    } catch (e) {
      // toast already handles error
    }
    setLoading(false);
  };

  const filtered = templates.filter((tpl) => {
    if (category !== 'all' && tpl.category !== category) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      tpl.name.toLowerCase().includes(q) ||
      tpl.description.toLowerCase().includes(q) ||
      (tpl.skills || []).some((s) => s.toLowerCase().includes(q))
    );
  });

  const handleCreate = (tpl) => {
    setConfirm({
      title: t('template.confirm_title'),
      message: t('template.confirm_msg', tpl.name),
      confirmText: t('template.create_btn'),
      onConfirm: async () => {
        setConfirm(null);
        setCreating((s) => new Set(s).add(tpl.id));
        try {
          await api.createFromTemplate({ template_id: tpl.id, name: tpl.name });
          setCreated((s) => new Set(s).add(tpl.id));
          toast(t('template.create_success', tpl.name), 'success');
        } catch (e) {
          // toast already handles error
        }
        setCreating((s) => { const n = new Set(s); n.delete(tpl.id); return n; });
      },
    });
  };

  const inputCls =
    'w-full pl-9 pr-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary';

  return (
    <div className="flex-1 overflow-y-auto bg-canvas">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <motion.div initial={{ y: -8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="mb-8">
          <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">{t('template.title')}</h1>
          <p className="text-sm text-ink-mute mt-1">{t('template.subtitle')}</p>
        </motion.div>

        {/* Search + Category tabs */}
        <div className="flex items-center gap-4 mb-6 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('template.search')}
              className={inputCls}
            />
          </div>
          <div className="flex gap-1.5">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setCategory(cat.id)}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-pill text-xs font-semibold transition-all ${
                  category === cat.id
                    ? 'bg-primary text-white shadow-sm'
                    : 'bg-surface-hover text-ink-mute hover:bg-surface-active hover:text-ink'
                }`}
              >
                {cat.id !== 'all' && <span>{CATEGORY_EMOJI[cat.id]}</span>}
                {cat.id === 'all' ? t('template.all') : t('template.' + cat.id)}
              </button>
            ))}
          </div>
        </div>

        {/* Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-ink-faint" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20 text-ink-faint text-sm">{t('template.no_results')}</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((tpl, i) => (
              <motion.div
                key={tpl.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
                className="rounded-2xl border border-hairline bg-white p-5 hover:shadow-md transition-shadow group"
              >
                <div className="flex items-start gap-3 mb-3">
                  <span className="text-2xl">{tpl.avatar_emoji || '🤖'}</span>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-bold text-ink truncate">{tpl.name}</h3>
                    <p className="text-xs text-ink-mute leading-relaxed mt-0.5 line-clamp-2">{tpl.description}</p>
                  </div>
                </div>

                {tpl.skills?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-4">
                    {tpl.skills.slice(0, 4).map((s) => (
                      <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-canvas text-ink-faint">
                        {s}
                      </span>
                    ))}
                  </div>
                )}

                <button
                  onClick={() => handleCreate(tpl)}
                  disabled={creating.has(tpl.id)}
                  className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition-all ${
                    created.has(tpl.id)
                      ? 'bg-emerald-50 text-emerald-600 border border-emerald-200'
                      : 'bg-primary text-white hover:bg-primary/90 disabled:opacity-50'
                  }`}
                >
                  {creating.has(tpl.id) ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : created.has(tpl.id) ? (
                    <Check size={12} />
                  ) : null}
                  {created.has(tpl.id) ? t('template.created') : t('template.create_btn')}
                </button>
              </motion.div>
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog state={[confirm, setConfirm]} />
    </div>
  );
}
