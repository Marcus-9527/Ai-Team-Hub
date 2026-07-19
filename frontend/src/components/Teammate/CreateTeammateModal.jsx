import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Plus, ChevronDown, Loader2, Check } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import { clearModelCache } from '../../services/providers';
import ModelSelector from './ModelSelector';
import { toast } from '../../services/toast';

const ROLE_TEMPLATES = [
  { id: '', label: 'teammate.chat_role_template_ph', prompt: '' },
];

const CATEGORIES = [
  { id: 'all', label: '全部' },
  { id: 'engineering', label: '工程技术' },
  { id: 'business', label: '商业管理' },
];

export default function CreateTeammateModal({ teammate, onClose, onCreated }) {
  const t = useTranslation();
  const isEdit = !!teammate;
  const [mode, setMode] = useState('manual'); // 'manual' | 'template'
  const [role, setRole] = useState(teammate?.role || '');
  const [provider, setProvider] = useState(teammate?.model_provider || 'openrouter');
  const [model, setModel] = useState(teammate?.model_name || '');
  const [apiKeys, setApiKeys] = useState([]);
  const [apiKey, setApiKey] = useState(teammate?.api_key_ref || '');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(teammate?.system_prompt || '');
  const [tools, setTools] = useState((teammate?.skills || []).join('、'));
  const [memory, setMemory] = useState((teammate?.capabilities || []).includes('memory'));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Template mode state
  const [templates, setTemplates] = useState([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [category, setCategory] = useState('all');
  const [creatingTpl, setCreatingTpl] = useState(null);
  const [roleTemplates, setRoleTemplates] = useState(ROLE_TEMPLATES);

  useEffect(() => {
    api.listTemplates().then(setRoleTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    api.listAPIKeys().then(setApiKeys).catch(() => {});
  }, []);

  useEffect(() => {
    if (mode === 'template') {
      setLoadingTemplates(true);
      api.listTemplates()
        .then(setTemplates)
        .catch(() => setError('加载模板失败'))
        .finally(() => setLoadingTemplates(false));
    }
  }, [mode]);

  const filteredTemplates = templates.filter((tpl) => {
    if (category !== 'all' && tpl.category !== category) return false;
    return true;
  });

  const handleCreateFromTemplate = async (tpl) => {
    setCreatingTpl(tpl.id);
    try {
      await api.createFromTemplate({ template_id: tpl.id, name: tpl.name });
      onCreated();
      onClose();
    } catch (e) {
      toast('创建失败: ' + (e.message || ''));
    }
    setCreatingTpl(null);
  };

  const handleCreate = async () => {
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const caps = [];
      if (memory) caps.push('memory');
      const roleText = role.trim() || 'AI 助手';
      const skillList = tools.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      const autoPrompt = `你是${roleText}，擅长：通用任务。`;
      const payload = {
        role: roleText,
        capabilities: caps,
        model_provider: provider,
        model_name: model,
        system_prompt: systemPrompt.trim() || autoPrompt,
        skills: skillList,
      };
      if (apiKey) payload.api_key_ref = apiKey;
      if (isEdit) await api.updateTeammate(teammate.id, payload);
      else await api.createTeammate(payload);
      onCreated();
      onClose();
    } catch (e) {
      setError(e.message || t('teammate.create_failed'));
      setSaving(false);
    }
  };

  const fieldLabel = (txt) => (
    <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-1.5">{txt}</label>
  );
  const inputCls = 'w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary';

  const tabBtn = (id, label) => (
    <button
      key={id}
      onClick={() => setMode(id)}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
        mode === id
          ? 'bg-primary text-white'
          : 'bg-surface-hover text-ink-mute hover:bg-surface-active'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[440px] max-w-[92vw] p-5 max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-ink">{isEdit ? t('teammate.edit') : '创建 AI 员工'}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-hover text-ink-faint transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Mode tabs — hide in edit mode */}
        {!isEdit && (
          <div className="flex gap-1.5 mb-4 pb-4 border-b border-hairline">
            {tabBtn('manual', '手动创建')}
          </div>
        )}

        {/* ── Manual mode (also always for edit) ── */}
          <div>
            {fieldLabel(t('teammate.chat_role'))}
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder={t('teammate.chat_role_ph')}
              className={inputCls + ' mb-3'}
              autoFocus={mode === 'manual'}
            />

            {fieldLabel(t('teammate.chat_model'))}
            <ModelSelector
              provider={provider}
              model={model}
              onProviderChange={(p) => { setProvider(p); setModel(''); }}
              onModelChange={setModel}
              apiKeys={apiKeys}
              selectedKey={apiKey}
              onKeyChange={(k) => { setApiKey(k); clearModelCache(); }}
              expert={showAdvanced}
            />

            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-canvas hover:bg-surface-hover text-xs font-semibold text-ink-mute transition-all mb-2 mt-2"
            >
              <span>{t('teammate.chat_advanced')}</span>
              <ChevronDown size={14} className={`text-ink-faint transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
            </button>

            {showAdvanced && (
              <div className="space-y-3 mb-3">
                {fieldLabel(t('teammate.chat_role_template'))}
                <select
                  value={''}
                  onChange={(e) => {
                    const tpl = roleTemplates.find((x) => x.id === e.target.value);
                    if (!tpl) return;
                    if (tpl.system_prompt) setSystemPrompt(tpl.system_prompt);
                    if (tpl.identity) setRole(tpl.identity);
                    if (tpl.skills?.length) setTools(tpl.skills.join('、'));
                    if (tpl.model_provider) setProvider(tpl.model_provider);
                    if (tpl.model_name) setModel(tpl.model_name);
                  }}
                  className={inputCls + ' mb-1'}
                >
                  {roleTemplates.map((tpl) => (
                    <option key={tpl.id} value={tpl.id}>{tpl.name || tpl.label}</option>
                  ))}
                </select>

                {fieldLabel(t('teammate.chat_system_prompt'))}
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder={t('teammate.chat_system_prompt_ph')}
                  rows={4}
                  className={inputCls + ' mb-1 resize-none'}
                />

                {fieldLabel(t('teammate.chat_tools'))}
                <input
                  value={tools}
                  onChange={(e) => setTools(e.target.value)}
                  placeholder={t('teammate.chat_tools_ph')}
                  className={inputCls + ' mb-1'}
                />

                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input type="checkbox" checked={memory} onChange={(e) => setMemory(e.target.checked)} className="mt-0.5 accent-primary" />
                  <span>
                    <span className="block text-xs font-medium text-ink">{t('teammate.chat_memory')}</span>
                    <span className="block text-[10px] text-ink-faint">{t('teammate.chat_memory_hint')}</span>
                  </span>
                </label>
              </div>
            )}

            {error && (
              <p className="text-xs text-semantic-error bg-red-50 rounded-lg px-3 py-2 mb-2">{error}</p>
            )}

            <div className="flex justify-end gap-2 mt-3">
              <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold text-ink-mute hover:bg-gray-100">
                {t('channel.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={saving}
                className="px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold disabled:opacity-50 transition-all"
              >
                {saving ? t('teammate.chat_creating') : (isEdit ? t('teammate.edit') : t('teammate.chat_create'))}
              </button>
            </div>
          </div>
      </motion.div>
    </div>
  );
}
