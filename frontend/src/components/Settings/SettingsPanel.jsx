import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Key, Trash2, Users,
  Plus, Check, Globe,
} from 'lucide-react';
import * as api from '../../services/api';
import { CHINESE_PROVIDERS, OVERSEAS_PROVIDERS } from '../../services/providers';
import { useTranslation, SUPPORTED_LANGUAGES } from '../../i18n';
import ConfirmDialog from '../ConfirmDialog';

const USER_MODES = [
  { id: 'user',      label: '普通用户',   desc: '默认模式，隐藏开发者功能' },
  { id: 'expert',    label: '专家模式',   desc: '进阶操作选项' },
  { id: 'developer', label: 'Developer Mode', desc: '显示技术统计与 Runtime 页面' },
];

export default function SettingsPanel({ onClose, triggerRefresh, lang, changeLang, userMode = 'user', setUserMode }) {
  const t = useTranslation();
  const [tab, setTab] = useState('apikeys');
  const [apiKeys, setApiKeys] = useState([]);
  const [showNewKey, setShowNewKey] = useState(false);
  const [newKeyError, setNewKeyError] = useState('');
  const [newKeyProvider, setNewKeyProvider] = useState('openrouter');
  const [newKeyLabel, setNewKeyLabel] = useState('');
  const [newKeyValue, setNewKeyValue] = useState('');
  const [showKey, setShowKey] = useState({});
  const [confirm, setConfirm] = useState(null);

  // 专家模式偏好（存本地，不触碰后端）
  const [execPref, setExecPref] = useState(() => localStorage.getItem('aihub_exec_pref') || 'parallel');
  const persist = (k, v) => localStorage.setItem(k, v);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const keys = await api.listAPIKeys();
      setApiKeys(keys);
    } catch (e) { console.error(e); }
  };

  const handleAddKey = async (e) => {
    e.preventDefault();
    if (!newKeyLabel.trim() || !newKeyValue.trim()) return;
    try {
      await api.createAPIKey({ provider: newKeyProvider, label: newKeyLabel, api_key: newKeyValue });
      setNewKeyProvider('openrouter'); setNewKeyLabel(''); setNewKeyValue('');
      setShowNewKey(false); setNewKeyError('');
      loadData(); triggerRefresh();
    } catch (err) { setNewKeyError(err.message || 'Failed to save API key'); }
  };

  const handleDeleteKey = async (id, label) => {
    setConfirm({
      title: t('settings.key_delete_title'),
      message: t('settings.key_delete_confirm', label),
      confirmText: t('settings.key_delete_btn'),
      onConfirm: async () => {
        await api.deleteAPIKey(id);
        loadData();
        triggerRefresh();
      },
    });
  };

  return (
    <>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 overflow-y-auto bg-canvas text-ink p-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">{t('settings.title')}</h1>
          <button onClick={onClose} className="w-9 h-9 rounded-xl hover:bg-surface-hover flex items-center justify-center transition-colors">
            <X size={20} className="text-ink-mute" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-8">
          {[
            { id: 'apikeys', label: t('settings.api_keys'), icon: Key },
            { id: 'language', label: t('settings.language'), icon: Globe },
            { id: 'mode', label: t('settings.mode'), icon: Users },
          ].map(tabItem => (
            <button
              key={tabItem.id}
              onClick={() => setTab(tabItem.id)}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-pill text-sm font-semibold transition-all ${
                tab === tabItem.id
                  ? 'bg-primary text-white shadow-md'
                  : 'text-ink-mute hover:bg-surface-hover hover:text-ink'
              }`}
            >
              <tabItem.icon size={16} />
              {tabItem.label}
            </button>
          ))}
        </div>

        {/* ── Language Tab ── */}
        {tab === 'language' && (
          <div className="space-y-4">
            <p className="text-sm text-ink-mute mb-4">{t('settings.language_desc')}</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {SUPPORTED_LANGUAGES.map(l => (
                <button
                  key={l.id}
                  onClick={() => changeLang(l.id)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-medium transition-all ${
                    lang === l.id
                      ? 'border-primary/30 bg-canvas-lavender text-primary shadow-sm'
                      : 'border-hairline hover:border-primary/10 text-ink hover:bg-surface-hover'
                  }`}
                >
                  <span className="text-xl">{l.flag}</span>
                  <span>{l.name}</span>
                  {lang === l.id && <Check size={14} className="ml-auto text-primary" />}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── API Keys Tab ── */}
        {tab === 'apikeys' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-ink-mute">{t('settings.add_key_desc')}</p>
              <button onClick={() => setShowNewKey(!showNewKey)} className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-pill hover:bg-primary-press transition-all shadow-md hover:shadow-lg">
                <Plus size={16} /> {t('settings.add_key')}
              </button>
            </div>

            <AnimatePresence mode="wait">
              {showNewKey && (
                <motion.form key="new-key-form" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }} onSubmit={handleAddKey}>
                  <div className="p-5 rounded-xl bg-surface border border-hairline space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.key_provider')}</label>
                        <select value={newKeyProvider} onChange={e => setNewKeyProvider(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10">
                          <optgroup label={t('teammate.providers_cn')}>
                            {CHINESE_PROVIDERS.map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                          </optgroup>
                          <optgroup label={t('teammate.providers_overseas')}>
                            {OVERSEAS_PROVIDERS.map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                          </optgroup>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.key_label')}</label>
                        <input value={newKeyLabel} onChange={e => setNewKeyLabel(e.target.value)} placeholder={t('settings.key_label_placeholder')} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.key_value')}</label>
                      <input value={newKeyValue} onChange={e => setNewKeyValue(e.target.value)} type="password" placeholder="sk-..." className="w-full px-3 py-2 rounded-lg border border-hairline text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/10" />
                      <p className="text-[10px] text-ink-faint mt-1">{t('settings.base_url_hint')}</p>
                    </div>
                    {newKeyError && (<p className="text-xs text-semantic-error bg-red-50 rounded-lg px-3 py-2">{newKeyError}</p>)}
                    <div className="flex gap-2 pt-1">
                      <button type="submit" className="px-5 py-2 bg-accent-teal text-white text-sm font-semibold rounded-pill hover:brightness-110 transition-all">{t('settings.save_key')}</button>
                      <button type="button" onClick={() => setShowNewKey(false)} className="px-5 py-2 text-sm text-ink-mute hover:text-ink transition-colors">{t('settings.cancel')}</button>
                    </div>
                  </div>
                </motion.form>
              )}
            </AnimatePresence>

            {apiKeys.length === 0 && !showNewKey && (
              <div className="py-12 text-center">
                <Key size={40} className="mx-auto text-ink-faint/30 mb-3" />
                <p className="text-ink-faint text-sm">{t('settings.no_keys')}</p>
              </div>
            )}
            {apiKeys.map(k => (
              <div key={k.id} className="p-4 rounded-xl bg-surface border border-hairline hover:border-primary/10 transition-all group">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-canvas-lavender flex items-center justify-center"><Key size={18} className="text-primary" /></div>
                    <div>
                      <p className="font-semibold text-sm text-ink">{k.label}</p>
                      <p className="text-xs text-ink-faint">{k.provider} · <code className="font-mono">{k.api_key}</code></p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => handleDeleteKey(k.id, k.label)} className="p-2 rounded-lg hover:bg-red-50 text-ink-faint hover:text-red-500 transition-colors"><Trash2 size={16} /></button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── User Mode Tab ── */}
        {tab === 'mode' && (
          <div className="space-y-3">
            <p className="text-sm text-ink-mute mb-4">{t('settings.mode_desc')}</p>
            {USER_MODES.map(m => (
              <button
                key={m.id}
                onClick={() => setUserMode(m.id)}
                className={`w-full flex items-center gap-3 p-4 rounded-xl border text-left transition-all ${
                  userMode === m.id
                    ? 'border-primary/30 bg-canvas-lavender shadow-sm'
                    : 'border-hairline hover:border-primary/10 hover:bg-surface-hover'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-ink">{m.label}</p>
                  <p className="text-[11px] text-ink-faint mt-0.5">{m.desc}</p>
                </div>
                {userMode === m.id && <Check size={16} className="text-primary flex-shrink-0" />}
              </button>
            ))}

            {/* 专家/开发者模式：额外控制入口；普通模式保持简洁，不显示 */}
            {userMode !== 'user' && (
              <div className="pt-4 mt-2 border-t border-hairline space-y-4">
                <h4 className="text-xs font-bold text-ink uppercase tracking-wider flex items-center gap-2">
                  {t('settings.expert_controls')}
                </h4>

                {/* 任务执行偏好 */}
                <div>
                  <label className="block text-xs font-semibold text-ink-mute mb-1">{t('settings.exec_pref')}</label>
                  <p className="text-[11px] text-ink-faint mb-2">{t('settings.exec_pref_desc')}</p>
                  <div className="flex gap-2">
                    {[
                      { id: 'parallel', label: t('settings.exec_pref_parallel') },
                      { id: 'serial', label: t('settings.exec_pref_serial') },
                    ].map(opt => (
                      <button
                        key={opt.id}
                        onClick={() => { setExecPref(opt.id); persist('aihub_exec_pref', opt.id); }}
                        className={`flex-1 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                          execPref === opt.id
                            ? 'border-primary/30 bg-canvas-lavender text-primary'
                            : 'border-hairline text-ink-mute hover:bg-surface-hover'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
      <ConfirmDialog state={[confirm, setConfirm]} />
    </>
  );
}

