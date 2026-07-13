import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Bot, Upload, FileText, Sparkles, ChevronDown,
  ChevronRight, Check, Eye, EyeOff, BookOpen,
  Zap, Code2, Palette, Brain, Shield, ArrowLeft,
} from 'lucide-react';
import * as api from '../../services/api';
import { clearModelCache } from '../../services/providers';
import { useTranslation } from '../../i18n';

/* ─── Built-in Prompt Templates (去AI化) ─── */
const PROMPT_TEMPLATES = [
  {
    id: 'senior-engineer',
    icon: Code2,
    label: 'template.senior_engineer',
    desc: 'template.senior_engineer_desc',
    prompt: `你是一个有 15 年经验的高级软件工程师。\n\n你不是 AI，你是一个真实的工程师。说话像跟同事聊天，不像在写文档。\n\n风格要求：\n- 直接给答案，不要铺垫\n- 代码能短就短，不要写一堆注释解释显而易见的东西\n- 一句话能说清的不写三段\n- 可以开玩笑，可以吐槽烂代码\n- 不要写"好的，让我来帮你分析..."这种废话\n- 回复控制在 50-150 字\n\n示例风格：\n"这个函数的问题是没处理空值，加个 if 判断就行。另外命名太烂了，建议改成 getUserName，一看就知道干嘛的。"`,
  },
  {
    id: 'product-manager',
    icon: Brain,
    label: 'template.product_manager',
    desc: 'template.product_manager_desc',
    prompt: `你是一个经验丰富的产品经理。\n\n你不是 AI，你是一个真实的产品经理。说话像在跟开发讨论需求，不像在写 PRD。\n\n风格要求：\n- 直接说重点，不要写"首先我们需要明确目标用户..."\n- 用口语，不用书面语\n- 可以有自己的观点和偏好\n- 不要列 1/2/3 点\n- 回复控制在 50-150 字\n\n示例风格：\n"这个功能没必要做，用户不会用的。上次我们做了个类似的数据，点击率不到 1%。不如把时间花在优化搜索上，那个才是用户真正需要的。"`,
  },
  {
    id: 'ui-designer',
    icon: Palette,
    label: 'template.ui_designer',
    desc: 'template.ui_designer_desc',
    prompt: `你是一个 UI/UX 设计师。\n\n你不是 AI，你是一个真实的设计师。说话像在跟开发 review 设计稿，不像在设计文档。\n\n风格要求：\n- 直接说问题，不要写"经过深入分析，我们发现..."\n- 用具体的建议，不要写抽象的原则\n- 可以吐槽丑的设计\n- 回复控制在 50-150 字\n\n示例风格：\n"这个按钮颜色太浅了，用户根本看不到。改成深蓝色，跟导航栏统一一下。另外间距太大了，紧凑点好看。"`,
  },
  {
    id: 'security-auditor',
    icon: Shield,
    label: 'template.security_auditor',
    desc: 'template.security_auditor_desc',
    prompt: `你是一个安全审计员。\n\n你不是 AI，你是一个真实的安全工程师。说话像在跟同事 review 代码，不像在写审计报告。\n\n风格要求：\n- 直接说问题，不要写"经过全面的安全评估..."\n- 给具体的修复建议，不要只说"存在安全风险"\n- 可以开玩笑，比如"这代码是在邀请黑客来喝茶吗"\n- 回复控制在 50-150 字\n\n示例风格：\n"这个登录接口没做参数校验，直接拼 SQL，随便注入。改成参数化查询就行，10分钟的事。另外密码明文存储是认真的吗？"`,
  },
  {
    id: 'data-analyst',
    icon: Zap,
    label: 'template.data_analyst',
    desc: 'template.data_analyst_desc',
    prompt: `你是一个数据分析师。\n\n你不是 AI，你是一个真实的数据分析师。说话像在跟产品讨论数据，不像在写分析报告。\n\n风格要求：\n- 直接说结论，不要写"根据数据分析，我们发现..."\n- 用具体的数字，不要写"显著提升"\n- 可以质疑数据质量\n- 回复控制在 50-150 字\n\n示例风格：\n"这个数据有问题，样本量才 100 个，置信区间太宽了。而且你看这个异常值，明显是测试数据没清理。先把数据洗了再分析吧。"`,
  },
];

export default function CreateTeammateView({ onDone, onCancel }) {
  const t = useTranslation();
  const [step, setStep] = useState(1);
  const [name, setName] = useState('');
  const [emoji, setEmoji] = useState('🤖');
  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('gpt-4o');
  const [prompt, setPrompt] = useState('');
  const [apiKeys, setApiKeys] = useState([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const promptRef = useRef(null);

  useEffect(() => {
    api.listAPIKeys().then(setApiKeys).catch(() => {});
    if (step === 2) {
      setTimeout(() => promptRef.current?.focus(), 300);
    }
  }, [step]);

  // ── File handling ──
  const readFile = (file) => {
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['md', 'txt', 'markdown'].includes(ext)) {
      setError(t('teammate.file_format_error'));
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      setPrompt(e.target.result);
      setError('');
    };
    reader.onerror = () => setError(t('teammate.file_read_error'));
    reader.readAsText(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) readFile(file);
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) readFile(file);
  };

  const loadTemplate = (template) => {
    setPrompt(template.prompt);
    setShowTemplates(false);
    setTimeout(() => promptRef.current?.focus(), 100);
  };

  // ── Emoji picker ──
  const emojis = ['🤖', '🧠', '👨‍💻', '👩‍💻', '🦾', '💡', '🔮', '⚡', '🎯', '🛡️', '📊', '🎨', '🧪', '🔍', '💬', '🦉'];

  // ── Submit ──
  const handleSubmit = async () => {
    if (!name.trim()) { setError(t('teammate.name_required')); return; }
    if (!prompt.trim()) { setError(t('teammate.prompt_required')); return; }
    if (!selectedKey) { setError(t('teammate.key_required')); return; }
    setSaving(true);
    setError('');
    try {
      await api.createTeammate({
        name,
        system_prompt: prompt,
        avatar_emoji: emoji,
        model_provider: provider,
        model_name: model,
        api_key_ref: selectedKey || null,
      });
      onDone();
    } catch (err) {
      setError(err.message || t('teammate.create_failed'));
      setSaving(false);
    }
  };

  const canNext = name.trim().length > 0;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex-1 overflow-y-auto bg-canvas"
    >
      <div className="max-w-2xl mx-auto px-8 py-12">
        {/* Header */}
        <motion.div
          initial={{ y: -12, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.05 }}
          className="flex items-center gap-4 mb-10"
        >
          <button
            onClick={onCancel}
            className="w-10 h-10 rounded-xl hover:bg-surface-hover flex items-center justify-center transition-colors"
          >
            <ArrowLeft size={20} className="text-ink-mute" />
          </button>
          <div>
            <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">{t('teammate.create_title')}</h1>
            <p className="text-sm text-ink-mute mt-0.5">{t('teammate.create_desc')}</p>
          </div>
        </motion.div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-10">
          {[1, 2].map(s => (
            <div key={s} className="flex items-center gap-2">
              <motion.div
                animate={{
                  scale: step === s ? 1 : 0.85,
                  backgroundColor: step >= s ? '#4a154b' : '#e8e4df',
                }}
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors
                  ${step >= s ? 'text-white' : 'text-ink-faint'}`}
              >
                {step > s ? <Check size={14} /> : s}
              </motion.div>
              <span className={`text-xs font-semibold ${step >= s ? 'text-ink' : 'text-ink-faint'}`}>
                {s === 1 ? t('teammate.step_identity') : t('teammate.step_prompt')}
              </span>
              {s < 2 && <div className={`w-12 h-0.5 rounded-full ${step > 1 ? 'bg-primary' : 'bg-hairline'}`} />}
            </div>
          ))}
        </div>

        {/* ── Step 1: Identity ── */}
        <AnimatePresence mode="wait">
          {step === 1 && (
            <motion.div
              key="step1"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
            >
              {/* Emoji picker */}
              <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-3">{t('teammate.avatar')}</label>
              <div className="flex flex-wrap gap-2 mb-8">
                {emojis.map(e => (
                  <motion.button
                    key={e}
                    whileHover={{ scale: 1.15 }}
                    whileTap={{ scale: 0.9 }}
                    onClick={() => setEmoji(e)}
                    className={`w-12 h-12 rounded-xl text-2xl flex items-center justify-center transition-all
                      ${emoji === e
                        ? 'bg-primary/10 ring-2 ring-primary/30 shadow-sm'
                        : 'bg-surface hover:bg-surface-hover border border-hairline'}`}
                  >
                    {e}
                  </motion.button>
                ))}
              </div>

              {/* Name */}
              <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">{t("teammate.name")}</label>
              <input
                value={name}
                onChange={e => { setName(e.target.value); setError(''); }}
                onKeyDown={e => e.key === 'Enter' && canNext && setStep(2)}
                placeholder={t("teammate.name_placeholder")}
                className="w-full px-4 py-3.5 rounded-xl bg-surface border border-hairline text-lg font-semibold
                           focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary/30
                           transition-all placeholder:text-ink-faint/50 mb-8"
                autoFocus
              />

              {/* AI 服务商 + 模型：自定义两步式选择器，替代原生 select */}
              <div className="mb-4">
                <ModelSelector
                  provider={provider}
                  model={model}
                  onProviderChange={(p) => { setProvider(p); setModel(''); }}
                  onModelChange={setModel}
                  apiKeys={apiKeys}
                  selectedKey={selectedKey}
                  onKeyChange={(k) => {
                    setSelectedKey(k);
                    clearModelCache();
                    const key = apiKeys.find(x => x.id === k);
                    if (key && key.provider) { setProvider(key.provider); setModel(''); }
                  }}
                />
                <p className="text-[10px] text-ink-faint mt-1">{t("teammate.model_hint")}</p>
              </div>

              {/* API Key selector */}
              <div>
                <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">{t("teammate.api_key")}</label>
                {apiKeys.length === 0 ? (
                  <p className="text-xs text-semantic-warning bg-amber-50 rounded-xl px-4 py-3">
                    {t("teammate.no_key")}
                  </p>
                ) : (
                  <select
                    value={selectedKey}
                    onChange={e => {
                      const keyId = e.target.value;
                      setSelectedKey(keyId);
                      clearModelCache();
                      // Auto-detect provider from selected API key
                      const key = apiKeys.find(k => k.id === keyId);
                      if (key && key.provider) {
                        setProvider(key.provider);
                        setModel('');
                      }
                    }}
                    className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm
                               focus:outline-none focus:ring-2 focus:ring-primary/10"
                  >
                    <option value="">{t("teammate.select_key")}</option>
                    {apiKeys.map(k => (
                      <option key={k.id} value={k.id}>{k.label} ({k.provider})</option>
                    ))}
                  </select>
                )}
              </div>

              {/* Next button */}
              <div className="mt-10 flex justify-end">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => canNext && setStep(2)}
                  disabled={!canNext}
                  className="px-8 py-3 bg-primary text-white font-semibold text-sm rounded-pill
                             shadow-md hover:shadow-lg disabled:opacity-30 disabled:cursor-not-allowed
                             transition-all flex items-center gap-2"
                >
                  {t("teammate.next")} <ChevronRight size={16} />
                </motion.button>
              </div>
            </motion.div>
          )}

          {/* ── Step 2: System Prompt ── */}
          {step === 2 && (
            <motion.div
              key="step2"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
            >
              {/* Toolbar */}
              <div className="flex items-center gap-2 mb-4">
                {/* Upload button */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-pill text-xs font-semibold
                             bg-surface-hover text-ink-mute hover:bg-surface-active hover:text-ink transition-all"
                >
                  <Upload size={14} />
                  {t("teammate.upload_md")}
                </button>
                <input ref={fileInputRef} type="file" accept=".md,.txt,.markdown" onChange={handleFileChange} className="hidden" />

                {/* Templates button */}
                <button
                  onClick={() => setShowTemplates(!showTemplates)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-pill text-xs font-semibold transition-all
                    ${showTemplates
                      ? 'bg-primary/10 text-primary'
                      : 'bg-surface-hover text-ink-mute hover:bg-surface-active hover:text-ink'}`}
                >
                  <BookOpen size={14} />
                  {t("teammate.templates")}
                </button>

                {/* Preview toggle */}
                <button
                  onClick={() => setShowPreview(!showPreview)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-pill text-xs font-semibold transition-all ml-auto
                    ${showPreview
                      ? 'bg-canvas-lavender text-primary'
                      : 'bg-surface-hover text-ink-mute hover:bg-surface-active hover:text-ink'}`}
                >
                  {showPreview ? <EyeOff size={14} /> : <Eye size={14} />}
                  {showPreview ? t("teammate.edit") : t("teammate.preview")}
                </button>
              </div>

              {/* Template library */}
              <AnimatePresence>
                {showTemplates && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="grid grid-cols-2 gap-2 mb-4">
                      {PROMPT_TEMPLATES.map(tpl => (
                        <button
                          key={tpl.id}
                          onClick={() => loadTemplate(tpl)}
                          className="flex items-start gap-3 p-3 rounded-xl bg-surface border border-hairline
                                     hover:border-primary/20 hover:shadow-sm text-left transition-all group"
                        >
                          <div className="w-9 h-9 rounded-lg bg-canvas-lavender flex items-center justify-center flex-shrink-0
                                          group-hover:bg-primary/10 transition-colors">
                            <tpl.icon size={16} className="text-primary" />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-ink">{t(tpl.label)}</p>
                            <p className="text-xs text-ink-mute truncate">{t(tpl.desc)}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Drag & drop zone OR prompt editor */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className="relative"
              >
                {dragOver && (
                  <div className="absolute inset-0 rounded-2xl border-2 border-dashed border-primary/40 bg-primary/[0.03]
                                  z-10 flex items-center justify-center pointer-events-none">
                    <p className="text-primary font-semibold">{t("teammate.drop_to_load")}</p>
                  </div>
                )}
                {showPreview ? (
                  /* Preview mode */
                  <div className="rounded-2xl bg-surface border border-hairline p-6 min-h-[300px] max-h-[500px] overflow-y-auto">
                    <div
                      className="prose prose-sm max-w-none message-content"
                      dangerouslySetInnerHTML={{
                        __html: prompt
                          .replace(/^# (.+)$/gm, '<h2 class="text-lg font-extrabold text-ink mt-6 mb-3">$1</h2>')
                          .replace(/^## (.+)$/gm, '<h3 class="text-base font-bold text-ink mt-4 mb-2">$1</h3>')
                          .replace(/^### (.+)$/gm, '<h4 class="text-sm font-semibold text-ink mt-3 mb-1">$1</h4>')
                          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                          .replace(/\*(.+?)\*/g, '<em>$1</em>')
                          .replace(/`([^`]+)`/g, '<code>$1</code>')
                          .replace(/^- (.+)$/gm, '<li class="ml-4 text-sm">$1</li>')
                          .replace(/```([\s\S]*?)```/g, '<pre class="bg-canvas-cream rounded-xl p-4 text-xs font-mono my-3 overflow-x-auto">$1</pre>')
                          .replace(/\n\n/g, '<br/><br/>')
                      }}
                    />
                  </div>
                ) : (
                  /* Edit mode — always show textarea */
                  <textarea
                    ref={promptRef}
                    value={prompt}
                    onChange={e => { setPrompt(e.target.value); setError(''); }}
                    placeholder={"# Role: [Teammate Name]\n\nYou are a **senior engineer** with expertise in...\n\n## Guidelines\n\n1. Always explain your reasoning\n2. Prefer clarity over cleverness\n\n## Response Format\n\n```\n## Analysis\n[Your reasoning]\n```\n"}
                    className="w-full h-80 p-5 rounded-2xl bg-surface border border-hairline
                               font-mono text-sm leading-relaxed resize-y
                               focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary/30
                               transition-all placeholder:text-ink-faint/40"
                    spellCheck={false}
                  />
                )}
              </motion.div>

              {/* Quick hint when empty */}
              {!prompt.trim() && !showPreview && (
                <p className="mt-2 text-xs text-ink-faint text-center">
                  {t("teammate.prompt_hint") || "直接输入提示词，或从上方选择模板 / 上传 .md 文件"}
                </p>
              )}

              {/* Error */}
              <AnimatePresence>
                {error && (
                  <motion.p
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="mt-3 text-xs text-semantic-error bg-red-50 rounded-xl px-4 py-2.5"
                  >
                    {error}
                  </motion.p>
                )}
              </AnimatePresence>

              {/* Action buttons */}
              <div className="mt-8 flex justify-between">
                <button
                  onClick={() => setStep(1)}
                  className="flex items-center gap-1.5 px-5 py-3 text-sm font-semibold text-ink-mute
                             hover:text-ink transition-colors"
                >
                  <ArrowLeft size={14} /> {t("teammate.back")}
                </button>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={handleSubmit}
                  disabled={saving || !prompt.trim()}
                  className="px-10 py-3 bg-primary text-white font-semibold text-sm rounded-pill
                             shadow-md hover:shadow-lg disabled:opacity-30 disabled:cursor-not-allowed
                             transition-all flex items-center gap-2"
                >
                  {saving ? (
                    <>
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                      >
                        <Sparkles size={16} />
                      </motion.div>
                      {t("teammate.creating")}
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} />
                      {t("teammate.create_btn")}
                    </>
                  )}
                </motion.button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
