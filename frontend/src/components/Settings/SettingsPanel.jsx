import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Key, Bot, Trash2, Eye, EyeOff,
  Plus, Check, Zap, Globe,
} from 'lucide-react';
import * as api from '../../services/api';
import { CHINESE_PROVIDERS, OVERSEAS_PROVIDERS } from '../../services/providers';
import { useTranslation, SUPPORTED_LANGUAGES } from '../../i18n';

export default function SettingsPanel({ onClose, triggerRefresh, lang, changeLang }) {
  const t = useTranslation();
  const [tab, setTab] = useState('apikeys');
  const [apiKeys, setApiKeys] = useState([]);
  const [teammates, setTeammates] = useState([]);
  const [showNewKey, setShowNewKey] = useState(false);
  const [newKeyError, setNewKeyError] = useState('');
  const [newKeyProvider, setNewKeyProvider] = useState('openai');
  const [newKeyLabel, setNewKeyLabel] = useState('');
  const [newKeyValue, setNewKeyValue] = useState('');
  const [newKeyUrl, setNewKeyUrl] = useState('');
  const [showKey, setShowKey] = useState({});

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [keys, tms] = await Promise.all([api.listAPIKeys(), api.listTeammates()]);
      setApiKeys(keys);
      setTeammates(tms);
    } catch (e) { console.error(e); }
  };

  const handleAddKey = async (e) => {
    e.preventDefault();
    if (!newKeyLabel.trim() || !newKeyValue.trim()) return;
    try {
      await api.createAPIKey({ provider: newKeyProvider, label: newKeyLabel, api_key: newKeyValue, base_url: newKeyUrl || null });
      setNewKeyProvider('openai'); setNewKeyLabel(''); setNewKeyValue(''); setNewKeyUrl('');
      setShowNewKey(false); setNewKeyError('');
      loadData(); triggerRefresh();
    } catch (err) { setNewKeyError(err.message || 'Failed to save API key'); }
  };

  const handleDeleteKey = async (id) => {
    if (!confirm(t('settings.key_delete_confirm'))) return;
    await api.deleteAPIKey(id); loadData(); triggerRefresh();
  };

  const handleDeleteTeammate = async (id) => {
    if (!confirm('Delete this teammate?')) return;
    await api.deleteTeammate(id); loadData(); triggerRefresh();
  };

  const handleUpdateTeammate = async (id, updates) => {
    await api.updateTeammate(id, updates); loadData(); triggerRefresh();
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 overflow-y-auto bg-canvas p-8">
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
            { id: 'teammates', label: t('settings.teammates'), icon: Bot },
            { id: 'language', label: t('settings.language'), icon: Globe },
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
              <p className="text-sm text-ink-mute">Add your own API keys to power AI teammates. Keys are stored locally.</p>
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
                          <optgroup label="🇨🇳 中国大模型">
                            {CHINESE_PROVIDERS.map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                          </optgroup>
                          <optgroup label="🌍 海外模型">
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
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.key_base_url')}</label>
                      <input value={newKeyUrl} onChange={e => setNewKeyUrl(e.target.value)} placeholder="https://api.openai.com" className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10" />
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
                    <button onClick={() => handleDeleteKey(k.id)} className="p-2 rounded-lg hover:bg-red-50 text-ink-faint hover:text-red-500 transition-colors"><Trash2 size={16} /></button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Teammates Tab ── */}
        {tab === 'teammates' && (
          <div className="space-y-4">
            {teammates.length === 0 && (
              <div className="py-12 text-center">
                <Bot size={40} className="mx-auto text-ink-faint/30 mb-3" />
                <p className="text-ink-faint text-sm">{t('settings.no_teammates')}</p>
                <p className="text-xs text-ink-faint/60 mt-1">Create one from the sidebar</p>
              </div>
            )}
            {teammates.map(t => (
              <TeammateEditor key={t.id} teammate={t} apiKeys={apiKeys} onUpdate={handleUpdateTeammate} onDelete={handleDeleteTeammate} />
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/* ─── Teammate Editor Card ─── */
function TeammateEditor({ teammate, apiKeys, onUpdate, onDelete }) {
  const t = useTranslation();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(teammate.name);
  const [emoji, setEmoji] = useState(teammate.avatar_emoji);
  const [provider, setProvider] = useState(teammate.model_provider);
  const [model, setModel] = useState(teammate.model_name);
  const [prompt, setPrompt] = useState(teammate.system_prompt);
  const [keyRef, setKeyRef] = useState(teammate.api_key_ref || '');

  const handleSave = () => {
    onUpdate(teammate.id, { name, avatar_emoji: emoji, model_provider: provider, model_name: model, system_prompt: prompt, api_key_ref: keyRef || null });
    setEditing(false);
  };

  return (
    <div className="p-5 rounded-xl bg-surface border border-hairline hover:border-primary/10 transition-all group">
      {!editing ? (
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-canvas-lavender flex items-center justify-center text-2xl flex-shrink-0">{teammate.avatar_emoji}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="font-bold text-ink">{teammate.name}</h3>
              <span className="px-2 py-0.5 bg-canvas-lavender text-primary text-[10px] font-semibold rounded-pill">{teammate.model_provider} / {teammate.model_name}</span>
            </div>
            <p className="text-sm text-ink-mute line-clamp-2 font-mono text-xs bg-canvas-cream rounded-lg p-3">{teammate.system_prompt}</p>
            <p className="text-[11px] text-ink-faint mt-2">API Key: {apiKeys.find(k => k.id === teammate.api_key_ref)?.label || 'None'}</p>
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={() => setEditing(true)} className="px-3 py-1.5 text-xs font-semibold text-primary hover:bg-canvas-lavender rounded-pill transition-colors">{t('settings.teammate_edit')}</button>
            <button onClick={() => onDelete(teammate.id)} className="p-1.5 rounded-lg hover:bg-red-50 text-ink-faint hover:text-red-500 transition-colors"><Trash2 size={14} /></button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_name')}</label>
              <input value={name} onChange={e => setName(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_emoji')}</label>
              <input value={emoji} onChange={e => setEmoji(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_provider')}</label>
              <select value={provider} onChange={e => setProvider(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10">
                <optgroup label="🇨🇳 中国大模型">
                  {CHINESE_PROVIDERS.map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                </optgroup>
                <optgroup label="🌍 海外模型">
                  {OVERSEAS_PROVIDERS.map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                </optgroup>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_model')}</label>
              <input value={model} onChange={e => setModel(e.target.value)} placeholder="gpt-4o" className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_prompt')}</label>
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={5} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/10 resize-none" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-ink-mute mb-1.5">{t('settings.teammate_api_key')}</label>
            <select value={keyRef} onChange={e => setKeyRef(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10">
              <option value="">— Select —</option>
              {apiKeys.map(k => (<option key={k.id} value={k.id}>{k.label} ({k.provider})</option>))}
            </select>
          </div>
          <div className="flex gap-2 pt-1">
            <button onClick={handleSave} className="flex items-center gap-1.5 px-5 py-2 bg-accent-teal text-white text-sm font-semibold rounded-pill hover:brightness-110 transition-all"><Check size={16} /> {t('settings.teammate_save')}</button>
            <button onClick={() => setEditing(false)} className="px-5 py-2 text-sm text-ink-mute hover:text-ink transition-colors">{t('settings.cancel')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
