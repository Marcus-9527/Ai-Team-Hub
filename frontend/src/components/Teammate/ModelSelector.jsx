import { useState, useEffect, useRef } from 'react';
import { Command } from 'cmdk';
import { ChevronDown, Check, Loader, ChevronLeft } from 'lucide-react';
import {
  CHINESE_PROVIDERS, OVERSEAS_PROVIDERS, getProviderModels,
  getProviderName, clearModelCache,
} from '../../services/providers';
import { decorateModel, groupByTier } from '../../services/modelMeta';
import { useTranslation } from '../../i18n';

/**
 * 基于 cmdk 的模型选择器 —— 替换自研列表组件。
 *
 * props:
 *   provider, model   —— 受控值
 *   onProviderChange(p), onModelChange(m)
 *   apiKeys, selectedKey, onKeyChange
 *   expert            —— 是否展示技术细节（默认 false = 普通用户视图）
 */
export default function ModelSelector({
  provider, model,
  onProviderChange, onModelChange,
  apiKeys = [], selectedKey = '', onKeyChange,
  expert = false,
}) {
  const t = useTranslation();
  const [open, setOpen] = useState(false);       // dropdown 是否展开
  const [step, setStep] = useState('provider');   // 'provider' | 'model'
  const [search, setSearch] = useState('');
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef(null);

  // 切换服务商后加载对应模型
  useEffect(() => {
    let cancelled = false;
    const key = selectedKey;
    setLoading(true);
    setModels([]);
    getProviderModels(provider, key)
      .then((ms) => {
        if (cancelled) return;
        const decorated = ms.map(decorateModel);
        setModels(decorated);
        setLoading(false);
        if (!decorated.some((m) => m.id === model)) {
          const first = decorated.find((m) => !m.id.startsWith('输入'));
          if (first) onModelChange(first.id);
        }
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [provider, selectedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 点击外部关闭
  useEffect(() => {
    const handler = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const openProvider = () => {
    if (open && step === 'provider') { setOpen(false); return; }
    setOpen(true);
    setStep('provider');
    setSearch('');
  };

  const openModel = () => {
    if (open && step === 'model') { setOpen(false); return; }
    setOpen(true);
    setStep('model');
    setSearch('');
  };

  const pickProvider = (p) => {
    onProviderChange(p.id);
    clearModelCache(p.id);
    setStep('model');
    setSearch('');
  };

  const { free: freeModels, paid: paidModels } = groupByTier(models);
  const selectedModel = models.find((m) => m.id === model);

  return (
    <div className="space-y-2" ref={rootRef}>
      {/* 第一步：选择 AI 服务商 */}
      <div className="relative">
        <button
          type="button"
          onClick={openProvider}
          className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm text-left
                     focus:outline-none focus:ring-2 focus:ring-primary/20 flex items-center gap-3 transition-all hover:border-primary/30"
        >
          <span className="flex-1 min-w-0">
            <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
              {t('teammate.chat_provider')}
            </span>
            <span className={provider ? 'text-ink font-semibold truncate block' : 'text-ink-faint'}>
              {provider ? getProviderName(provider) : (t('teammate.select_provider') || '选择 AI 服务商')}
            </span>
          </span>
          <ChevronDown size={14} className={`text-ink-faint transition-transform ${open && step === 'provider' ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {/* 第二步：选择模型 */}
      <div className="relative">
        <button
          type="button"
          disabled={!provider}
          onClick={openModel}
          className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm text-left
                     focus:outline-none focus:ring-2 focus:ring-primary/20 flex items-center gap-3 transition-all
                     hover:border-primary/30 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <span className="flex-1 min-w-0">
            <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
              {t('teammate.chat_model')}
            </span>
            <span className={selectedModel ? 'text-ink font-semibold truncate block' : 'text-ink-faint'}>
              {loading
                ? t('teammate.loading_models')
                : selectedModel
                  ? (expert ? selectedModel.id : selectedModel.name)
                  : (t('teammate.chat_model_pick'))}
            </span>
          </span>
          {selectedModel?.is_free && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 font-semibold shrink-0">FREE</span>
          )}
          <ChevronDown size={14} className={`text-ink-faint transition-transform ${open && step === 'model' ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {/* ── cmdk 下拉面板 ── */}
      {open && (
        <div className="rounded-xl border border-hairline bg-surface overflow-hidden shadow-card-lg">
          <Command
            shouldFilter={true}
            className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px]
                       [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase
                       [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-ink-faint
                       [&_[cmdk-group-heading]]:bg-canvas [&_[cmdk-group-heading]]:border-b
                       [&_[cmdk-group-heading]]:border-hairline"
          >
            <div className="flex items-center border-b border-hairline px-3">
              {step === 'model' && (
                <button
                  onClick={() => { setStep('provider'); setSearch(''); }}
                  className="p-1 mr-1 text-ink-faint hover:text-ink shrink-0"
                >
                  <ChevronLeft size={14} />
                </button>
              )}
              <Command.Input
                autoFocus
                placeholder={
                  step === 'provider'
                    ? (t('teammate.provider_search_placeholder') || '搜索服务商...')
                    : (t('teammate.model_search_placeholder') || '搜索模型...')
                }
                value={search}
                onValueChange={setSearch}
                className="w-full py-3 text-xs bg-transparent outline-none placeholder:text-ink-faint/50"
              />
            </div>

            <Command.List className="max-h-80 overflow-y-auto">
              <Command.Empty className="text-xs text-ink-faint text-center py-6">
                {t('teammate.no_models_found')}
              </Command.Empty>

              {step === 'provider' ? (
                <>
                  {CHINESE_PROVIDERS.length > 0 && (
                    <Command.Group heading={t('teammate.providers_cn')}>
                      {CHINESE_PROVIDERS.map((p) => (
                        <ProviderItem
                          key={p.id} provider={p}
                          active={p.id === provider}
                          onSelect={() => pickProvider(p)}
                          expert={expert}
                        />
                      ))}
                    </Command.Group>
                  )}
                  {OVERSEAS_PROVIDERS.length > 0 && (
                    <Command.Group heading={t('teammate.providers_overseas')}>
                      {OVERSEAS_PROVIDERS.map((p) => (
                        <ProviderItem
                          key={p.id} provider={p}
                          active={p.id === provider}
                          onSelect={() => pickProvider(p)}
                          expert={expert}
                        />
                      ))}
                    </Command.Group>
                  )}
                </>
              ) : loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader size={18} className="animate-spin text-ink-faint" />
                  <span className="ml-2 text-xs text-ink-faint">{t('teammate.loading_models')}</span>
                </div>
              ) : (
                <>
                  {freeModels.length > 0 && (
                    <Command.Group heading={`${t('teammate.chat_model_free')} (${freeModels.length})`}>
                      {freeModels.map((m) => (
                        <ModelItem
                          key={m.id} model={m}
                          active={m.id === model}
                          onSelect={() => { onModelChange(m.id); setOpen(false); }}
                          expert={expert}
                        />
                      ))}
                    </Command.Group>
                  )}
                  {paidModels.length > 0 && (
                    <Command.Group heading={`${t('teammate.chat_model_paid')} (${paidModels.length})`}>
                      {paidModels.map((m) => (
                        <ModelItem
                          key={m.id} model={m}
                          active={m.id === model}
                          onSelect={() => { onModelChange(m.id); setOpen(false); }}
                          expert={expert}
                        />
                      ))}
                    </Command.Group>
                  )}
                </>
              )}
            </Command.List>
          </Command>
        </div>
      )}

      {/* 选中模型简介 */}
      {selectedModel && (
        <div className="rounded-xl bg-canvas px-3 py-2.5 space-y-1">
          {selectedModel.description && (
            <p className="text-[11px] text-ink-mute leading-snug">{selectedModel.description}</p>
          )}
          <p className="text-[10px] text-ink-faint">
            <span className="text-ink-mute font-medium">{t('teammate.model_scenario')}：</span>
            {selectedModel.scenario}
          </p>
          {expert && (
            <p className="text-[10px] text-ink-faint flex flex-wrap gap-x-3">
              {selectedModel.context_length > 0 && (
                <span>{t('teammate.model_ctx')} {(selectedModel.context_length / 1000).toFixed(0)}K</span>
              )}
              <span>{t('teammate.model_speed')} {t('teammate.model_speed_' + selectedModel.speed)}</span>
              <span className="font-mono">{selectedModel.id}</span>
            </p>
          )}
        </div>
      )}

      {/* API 密钥 */}
      {apiKeys.length > 0 && (
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-faint mb-1">
            {t('teammate.chat_api_key')}
          </span>
          <select
            value={selectedKey}
            onChange={(e) => onKeyChange && onKeyChange(e.target.value)}
            className="w-full px-4 py-2.5 rounded-xl bg-surface border border-hairline text-xs text-ink
                       focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary cursor-pointer"
          >
            <option value="">{t('teammate.chat_api_key_ph')}</option>
            {apiKeys.map((k) => (
              <option key={k.id} value={k.id}>{k.label} {expert ? `(${k.provider})` : ''}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}

function ProviderItem({ provider: p, active, onSelect, expert }) {
  return (
    <Command.Item
      value={`${p.id} ${p.name} ${p.desc || ''}`}
      onSelect={onSelect}
      className={`flex items-start gap-3 px-3 py-2 rounded-none cursor-pointer text-sm
        aria-selected:bg-surface-hover data-[selected]:bg-surface-hover
        ${active ? 'bg-canvas-lavender' : ''}`}
    >
      <div className="w-9 h-9 rounded-lg bg-canvas-lavender flex items-center justify-center flex-shrink-0 text-sm font-bold text-primary">
        {p.name.charAt(0)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={`text-sm font-semibold truncate ${active ? 'text-primary' : 'text-ink'}`}>
            {p.name}
          </span>
          {active && <Check size={13} className="text-primary shrink-0" />}
        </div>
        <p className="text-[11px] text-ink-mute truncate">{p.desc}</p>
        {expert && <p className="text-[9px] text-ink-faint font-mono mt-0.5">{p.id}</p>}
      </div>
    </Command.Item>
  );
}

function ModelItem({ model: m, active, onSelect, expert }) {
  return (
    <Command.Item
      value={`${m.id} ${m.name} ${m.description || ''}`}
      onSelect={onSelect}
      className={`flex items-start gap-2 px-3 py-2 rounded-none cursor-pointer
        aria-selected:bg-surface-hover data-[selected]:bg-surface-hover
        ${active ? 'bg-canvas-lavender' : ''}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <code className={`font-mono text-[11px] truncate ${active ? 'text-primary font-semibold' : 'text-ink'}`}>
            {expert ? m.id : m.name}
          </code>
          {m.is_free && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 font-semibold shrink-0">FREE</span>
          )}
        </div>
        {m.description && (
          <p className="text-[10px] text-ink-mute truncate mt-0.5">{m.description}</p>
        )}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5 text-[9px] text-ink-faint">
          <span>{'适用：' + m.scenario}</span>
          {m.context_length > 0 && <span>· {(m.context_length / 1000) | 0}K</span>}
          {(m.tags || []).map((tag) => (
            <span key={tag} className="px-1 py-0.5 rounded bg-surface-hover text-ink-faint">{tag}</span>
          ))}
        </div>
      </div>
      {active && <Check size={13} className="text-primary shrink-0 mt-1" />}
    </Command.Item>
  );
}
