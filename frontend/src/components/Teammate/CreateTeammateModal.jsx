import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Plus, ChevronDown } from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';
import { clearModelCache } from '../../services/providers';
import ModelSelector from './ModelSelector';

const ROLE_TEMPLATES = [
  { id: '', label: 'teammate.chat_role_template_ph', prompt: '' },
  {
    id: 'engineer', label: '软件工程师',
    prompt: '你是一个有 15 年经验的高级软件工程师。直接给答案，不铺垫，代码能短就短，可以开玩笑吐槽烂代码。回复控制在 50-150 字。',
  },
  {
    id: 'pm', label: '产品经理',
    prompt: '你是一个经验丰富的产品经理。直接说重点，用口语不用书面语，可以有自己的观点。回复控制在 50-150 字。',
  },
  {
    id: 'designer', label: 'UI/UX 设计师',
    prompt: '你是一个 UI/UX 设计师。直接说问题，给具体建议，可以吐槽丑的设计。回复控制在 50-150 字。',
  },
  {
    id: 'analyst', label: '数据分析师',
    prompt: '你是一个数据分析师。直接说结论，用具体数字，可以质疑数据质量。回复控制在 50-150 字。',
  },
];

/**
 * 极简创建队友 Modal —— Chat / Team 页通用。
 * 基础：名称 / 角色 / 能力标签 / 模型（自动推荐 or 手动选择）。
 * 高级（默认隐藏）：System Prompt / 角色模板 / 工具权限 / 记忆设置。
 */
export default function CreateTeammateModal({ teammate, onClose, onCreated }) {
  const t = useTranslation();
  const isEdit = !!teammate;
  const [name, setName] = useState(teammate?.name || '');
  const [role, setRole] = useState(teammate?.role || '');
  const [capabilities, setCapabilities] = useState(
    (teammate?.capabilities || []).filter((c) => c !== 'memory').join('、')
  );
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

  useEffect(() => {
    api.listAPIKeys().then(setApiKeys).catch(() => {});
  }, []);

  const handleCreate = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError('');
    try {
      const caps = capabilities.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      if (memory) caps.push('memory');
      const roleText = role.trim() || 'AI 助手';
      const skillList = tools.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      const autoPrompt = `你是${roleText}，擅长：${caps.filter((c) => c !== 'memory').join('、') || '通用任务'}。`;
      const payload = {
        name: name.trim(),
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
    } catch (e) {
      setError(e.message || t('teammate.create_failed'));
      setSaving(false);
    }
  };

  const fieldLabel = (txt) => (
    <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-1.5">{txt}</label>
  );
  const inputCls = 'w-full px-3 py-2 rounded-xl border border-hairline text-sm text-ink bg-canvas focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-2xl shadow-card-lg border border-hairline w-[380px] max-w-[92vw] p-5 max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-ink">{isEdit ? t('teammate.edit') : t('teammate.create_in_chat')}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-hover text-ink-faint transition-colors">
            <X size={16} />
          </button>
        </div>

        {fieldLabel(t('teammate.chat_name'))}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('teammate.name_placeholder')}
          className={inputCls + ' mb-3'}
          autoFocus
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
        />

        {fieldLabel(t('teammate.chat_role'))}
        <input
          value={role}
          onChange={(e) => setRole(e.target.value)}
          placeholder={t('teammate.chat_role_ph')}
          className={inputCls + ' mb-3'}
        />

        {fieldLabel(t('teammate.chat_capabilities'))}
        <input
          value={capabilities}
          onChange={(e) => setCapabilities(e.target.value)}
          placeholder={t('teammate.chat_capabilities_ph')}
          className={inputCls + ' mb-3'}
        />

        {/* 模型选择：两步式（AI 服务商 → 模型），自定义组件替代原生 select */}
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

        {/* 高级设置（默认隐藏） */}
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-canvas hover:bg-surface-hover text-xs font-semibold text-ink-mute transition-all mb-2"
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
                const tpl = ROLE_TEMPLATES.find((x) => x.id === e.target.value);
                if (tpl?.prompt) setSystemPrompt(tpl.prompt);
              }}
              className={inputCls + ' mb-1'}
            >
              {ROLE_TEMPLATES.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>{tpl.label}</option>
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

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold text-ink-mute hover:bg-gray-100">
            {t('channel.cancel')}
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !name.trim()}
            className="px-4 py-2 rounded-xl bg-primary text-white text-xs font-semibold disabled:opacity-50 transition-all"
          >
            {saving ? t('teammate.chat_creating') : (isEdit ? t('teammate.edit') : t('teammate.chat_create'))}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
