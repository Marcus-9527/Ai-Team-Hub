import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Hash, ArrowLeft, Sparkles, Users, Plus, Check, UserPlus } from 'lucide-react';
import { useTranslation } from '../../i18n';
import * as api from '../../services/api';
import { CHINESE_PROVIDERS, OVERSEAS_PROVIDERS } from '../../services/providers';

const TEAMMATE_TEMPLATES = [
  {
    name: 'Senior Engineer',
    role: 'engineer',
    avatar_emoji: '👨‍💻',
    system_prompt: 'You are a Senior Engineer. Write clean, efficient code. Review for bugs and suggest improvements. Be precise and technical.',
    model_provider: 'openrouter',
    model_name: 'openrouter/auto',
  },
  {
    name: 'Product Manager',
    role: 'pm',
    avatar_emoji: '🧠',
    system_prompt: 'You are a Product Manager. Focus on user needs, prioritize features, and ensure the team delivers value. Think strategically about product decisions.',
    model_provider: 'openrouter',
    model_name: 'openrouter/auto',
  },
  {
    name: 'QA Tester',
    role: 'qa',
    avatar_emoji: '🧪',
    system_prompt: 'You are a QA Tester. Identify edge cases, test scenarios, and potential bugs. Ensure quality and reliability in every feature.',
    model_provider: 'openrouter',
    model_name: 'openrouter/auto',
  },
  {
    name: 'Tech Lead',
    role: 'lead',
    avatar_emoji: '🏗️',
    system_prompt: 'You are a Tech Lead. Make architectural decisions, mentor the team, and ensure technical excellence. Balance pragmatism with best practices.',
    model_provider: 'openrouter',
    model_name: 'openrouter/auto',
  },
];

export default function CreateChannelView({ onDone, onCancel }) {
  const t = useTranslation();
  const [step, setStep] = useState('channel'); // 'channel' | 'teammates' | 'create-teammate'
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [createdChannel, setCreatedChannel] = useState(null);

  // Teammate selection state
  const [existingTeammates, setExistingTeammates] = useState([]);
  const [selectedTeammates, setSelectedTeammates] = useState(new Set());
  const [addingTeammates, setAddingTeammates] = useState(false);

  // Create teammate state
  const [newTeammateName, setNewTeammateName] = useState('');
  const [newTeammateEmoji, setNewTeammateEmoji] = useState('');
  const [newTeammatePrompt, setNewTeammatePrompt] = useState('');
  const [newTeammateRole, setNewTeammateRole] = useState('');
  const [creatingTeammate, setCreatingTeammate] = useState(false);

  useEffect(() => {
    if (step === 'teammates' || step === 'create-teammate') {
      loadTeammates();
    }
  }, [step]);

  const loadTeammates = async () => {
    try {
      const tm = await api.listTeammates();
      setExistingTeammates(tm);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateChannel = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError(t('channel.name_required')); return; }
    setSaving(true);
    setError('');
    try {
      const ch = await api.createChannel({ name: name.trim(), description: description.trim() });
      setCreatedChannel(ch);
      setStep('teammates');
    } catch (err) {
      setError(err.message || 'Failed');
    } finally {
      setSaving(false);
    }
  };

  const toggleTeammate = (id) => {
    setSelectedTeammates(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAddTeammatesAndDone = async () => {
    if (!createdChannel) { onDone(null); return; }
    setAddingTeammates(true);
    try {
      for (const tmId of selectedTeammates) {
        await api.addTeammateToChannel(createdChannel.id, tmId);
      }
      onDone(createdChannel);
    } catch (err) {
      console.error('Failed to add teammates:', err);
      onDone(createdChannel); // still navigate even if adding fails
    } finally {
      setAddingTeammates(false);
    }
  };

  const handleSkipTeammates = () => {
    onDone(createdChannel);
  };

  const handleTemplateSelect = (template) => {
    setNewTeammateName(template.name);
    setNewTeammateEmoji(template.avatar_emoji);
    setNewTeammatePrompt(template.system_prompt);
    setNewTeammateRole(template.role);
  };

  const handleCreateTeammate = async () => {
    if (!newTeammateName.trim()) return;
    setCreatingTeammate(true);
    try {
      // Get or create an API key
      const keys = await api.listAPIKeys();
      let keyId;
      if (keys.length === 0) {
        const newKey = await api.createAPIKey({ provider: 'openrouter', label: 'Default' });
        keyId = newKey.id;
      } else {
        keyId = keys[0].id;
      }

      const tm = await api.createTeammate({
        name: newTeammateName.trim(),
        role: newTeammateRole || 'teammate',
        avatar_emoji: newTeammateEmoji || '🤖',
        system_prompt: newTeammatePrompt || 'You are a helpful AI teammate.',
        model_provider: 'openrouter',
        model_name: 'openrouter/auto',
        api_key_ref: keyId,
      });

      // Auto-select the new teammate and add to channel
      if (createdChannel) {
        await api.addTeammateToChannel(createdChannel.id, tm.id);
      }
      setSelectedTeammates(prev => new Set(prev).add(tm.id));
      await loadTeammates();
      setStep('teammates');

      // Reset form
      setNewTeammateName('');
      setNewTeammateEmoji('');
      setNewTeammatePrompt('');
      setNewTeammateRole('');
    } catch (err) {
      console.error('Failed to create teammate:', err);
    } finally {
      setCreatingTeammate(false);
    }
  };

  const presets = [
    { name: 'feature-planning', desc: 'Plan and scope new features', emoji: '🚀' },
    { name: 'code-review', desc: 'Code reviews and PR discussions', emoji: '🔍' },
    { name: 'debug-war-room', desc: 'Urgent debugging sessions', emoji: '🛠️' },
    { name: 'design-system', desc: 'UI/UX and design system work', emoji: '🎨' },
    { name: 'architecture', desc: 'System architecture discussions', emoji: '🏗️' },
    { name: 'data-analysis', desc: 'Data exploration and insights', emoji: '📊' },
  ];

  // ── Step 1: Channel Info ──
  if (step === 'channel') {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex-1 overflow-y-auto bg-canvas">
        <div className="max-w-xl mx-auto px-8 py-12">
          <motion.div initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.05 }}
            className="flex items-center gap-4 mb-10">
            <button onClick={onCancel} className="w-10 h-10 rounded-xl hover:bg-surface-hover flex items-center justify-center">
              <ArrowLeft size={20} className="text-ink-mute" />
            </button>
            <div>
              <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">{t('channel.create_title')}</h1>
              <p className="text-sm text-ink-mute mt-0.5">{t('channel.create_desc')}</p>
            </div>
          </motion.div>

          <motion.form initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.1 }}
            onSubmit={handleCreateChannel} className="space-y-6">
            <div>
              <label className="flex items-center gap-2 text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">
                <Hash size={13} /> {t('channel.name')}
              </label>
              <input value={name} onChange={e => { setName(e.target.value); setError(''); }}
                placeholder={t('channel.name_placeholder')}
                className="w-full px-4 py-3.5 rounded-xl bg-surface border border-hairline text-lg font-semibold focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary/30 transition-all placeholder:text-ink-faint/50" autoFocus />
            </div>
            <div>
              <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">{t('channel.description')}</label>
              <input value={description} onChange={e => setDescription(e.target.value)}
                placeholder={t('channel.description_placeholder')}
                className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm focus:outline-none focus:ring-2 focus:ring-primary/10 transition-all placeholder:text-ink-faint/50" />
            </div>
            {error && <motion.p initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="text-xs text-semantic-error bg-red-50 rounded-xl px-4 py-2.5">{error}</motion.p>}
            <div className="flex gap-3 pt-2">
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} type="submit" disabled={saving}
                className="flex-1 px-8 py-3.5 bg-primary text-white font-semibold text-sm rounded-pill shadow-md hover:shadow-lg disabled:opacity-50 transition-all flex items-center justify-center gap-2">
                {saving ? <><motion.div animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}><Sparkles size={16} /></motion.div>{t('channel.creating')}</> : <><Hash size={16} /> {t('channel.create_btn')}</>}
              </motion.button>
              <button type="button" onClick={onCancel} className="px-6 py-3.5 text-sm font-semibold text-ink-mute hover:text-ink">{t('channel.cancel')}</button>
            </div>
          </motion.form>

          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }} className="mt-12">
            <p className="text-xs font-semibold text-ink-faint uppercase tracking-wide mb-3">{t('channel.quick_presets')}</p>
            <div className="grid grid-cols-2 gap-2">
              {presets.map(p => (
                <motion.button key={p.name} whileHover={{ scale: 1.02, y: -1 }} whileTap={{ scale: 0.97 }} type="button"
                  onClick={() => { setName(p.name); setDescription(p.desc); }}
                  className="flex items-center gap-3 p-3 rounded-xl bg-surface border border-hairline hover:border-primary/20 hover:shadow-sm text-left transition-all group">
                  <span className="text-lg">{p.emoji}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-ink font-mono text-xs truncate">#{p.name}</p>
                    <p className="text-[11px] text-ink-mute truncate">{p.desc}</p>
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.div>
        </div>
      </motion.div>
    );
  }

  // ── Step 2: Select Teammates ──
  if (step === 'teammates') {
    const hasTeammates = existingTeammates.length > 0;
    return (
      <motion.div initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="flex-1 overflow-y-auto bg-canvas">
        <div className="max-w-xl mx-auto px-8 py-12">
          <motion.div initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.05 }}
            className="flex items-center gap-4 mb-10">
            <button onClick={onCancel} className="w-10 h-10 rounded-xl hover:bg-surface-hover flex items-center justify-center">
              <ArrowLeft size={20} className="text-ink-mute" />
            </button>
            <div>
              <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">Add Teammates</h1>
              <p className="text-sm text-ink-mute mt-0.5">Select AI teammates to add to <span className="font-semibold text-ink">#{createdChannel?.name}</span></p>
            </div>
          </motion.div>

          {hasTeammates ? (
            <motion.div initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.1 }}
              className="space-y-2 mb-8">
              {existingTeammates.map(tm => (
                <button
                  key={tm.id}
                  onClick={() => toggleTeammate(tm.id)}
                  className={`w-full flex items-center gap-4 p-4 rounded-xl border transition-all text-left ${
                    selectedTeammates.has(tm.id)
                      ? 'border-primary/30 bg-canvas-lavender shadow-sm'
                      : 'border-hairline bg-surface hover:border-primary/10 hover:bg-surface-hover'
                  }`}
                >
                  <div className="w-10 h-10 rounded-xl bg-canvas-cream flex items-center justify-center text-xl flex-shrink-0">
                    {tm.avatar_emoji}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm text-ink">{tm.name}</p>
                    <p className="text-[11px] text-ink-faint truncate">{tm.system_prompt}</p>
                  </div>
                  {selectedTeammates.has(tm.id) && (
                    <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center flex-shrink-0">
                      <Check size={14} className="text-white" />
                    </div>
                  )}
                </button>
              ))}

              <button
                onClick={() => setStep('create-teammate')}
                className="w-full flex items-center gap-4 p-4 rounded-xl border border-dashed border-hairline hover:border-primary/20 hover:bg-surface-hover transition-all text-left"
              >
                <div className="w-10 h-10 rounded-xl bg-canvas-lavender flex items-center justify-center flex-shrink-0">
                  <Plus size={20} className="text-primary" />
                </div>
                <div>
                  <p className="font-semibold text-sm text-primary">Create new teammate</p>
                  <p className="text-[11px] text-ink-faint">Add a custom AI teammate</p>
                </div>
              </button>
            </motion.div>
          ) : (
            <motion.div initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.1 }}
              className="text-center py-8">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-canvas-lavender flex items-center justify-center">
                <UserPlus size={28} className="text-primary" />
              </div>
              <h2 className="text-lg font-bold text-ink mb-2">No teammates yet</h2>
              <p className="text-sm text-ink-mute mb-6">Create your first AI teammate to get started</p>
              <motion.button
                whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                onClick={() => setStep('create-teammate')}
                className="px-6 py-3 bg-primary text-white font-semibold text-sm rounded-pill shadow-md hover:shadow-lg transition-all inline-flex items-center gap-2"
              >
                <Plus size={16} /> Create your first teammate
              </motion.button>
            </motion.div>
          )}

          {/* Bottom actions */}
          <div className="flex gap-3 pt-2">
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={handleAddTeammatesAndDone}
              disabled={addingTeammates || selectedTeammates.size === 0}
              className="flex-1 px-8 py-3.5 bg-primary text-white font-semibold text-sm rounded-pill shadow-md hover:shadow-lg disabled:opacity-50 transition-all flex items-center justify-center gap-2">
              {addingTeammates
                ? <><motion.div animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}><Sparkles size={16} /></motion.div>Adding...</>
                : <><Users size={16} /> Add {selectedTeammates.size > 0 ? `${selectedTeammates.size} Teammate${selectedTeammates.size > 1 ? 's' : ''}` : 'Teammates'}</>}
            </motion.button>
            <button onClick={handleSkipTeammates} className="px-6 py-3.5 text-sm font-semibold text-ink-mute hover:text-ink">
              Skip for now
            </button>
          </div>
        </div>
      </motion.div>
    );
  }

  // ── Step 2b: Create Teammate ──
  if (step === 'create-teammate') {
    return (
      <motion.div initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="flex-1 overflow-y-auto bg-canvas">
        <div className="max-w-xl mx-auto px-8 py-12">
          <motion.div initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.05 }}
            className="flex items-center gap-4 mb-10">
            <button onClick={() => setStep('teammates')} className="w-10 h-10 rounded-xl hover:bg-surface-hover flex items-center justify-center">
              <ArrowLeft size={20} className="text-ink-mute" />
            </button>
            <div>
              <h1 className="text-2xl font-extrabold text-ink tracking-[-0.02em]">Create Teammate</h1>
              <p className="text-sm text-ink-mute mt-0.5">Pick a template or customize your own</p>
            </div>
          </motion.div>

          {/* Templates */}
          <motion.div initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.1 }}
            className="mb-8">
            <p className="text-xs font-semibold text-ink-faint uppercase tracking-wide mb-3">Quick Templates</p>
            <div className="grid grid-cols-2 gap-2">
              {TEAMMATE_TEMPLATES.map(tmpl => (
                <motion.button key={tmpl.name} whileHover={{ scale: 1.02, y: -1 }} whileTap={{ scale: 0.97 }} type="button"
                  onClick={() => handleTemplateSelect(tmpl)}
                  className={`flex items-center gap-3 p-3 rounded-xl border text-left transition-all ${
                    newTeammateName === tmpl.name
                      ? 'border-primary/30 bg-canvas-lavender shadow-sm'
                      : 'border-hairline bg-surface hover:border-primary/20'
                  }`}>
                  <span className="text-xl">{tmpl.avatar_emoji}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-ink">{tmpl.name}</p>
                    <p className="text-[11px] text-ink-mute truncate">{tmpl.role}</p>
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.div>

          {/* Custom form */}
          <motion.div initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.15 }}
            className="space-y-4">
            <div className="grid grid-cols-[60px_1fr] gap-3 items-end">
              <div>
                <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">Emoji</label>
                <input value={newTeammateEmoji} onChange={e => setNewTeammateEmoji(e.target.value)}
                  placeholder="🤖"
                  className="w-full px-3 py-3 rounded-xl bg-surface border border-hairline text-xl text-center focus:outline-none focus:ring-2 focus:ring-primary/10" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">Name</label>
                <input value={newTeammateName} onChange={e => setNewTeammateName(e.target.value)}
                  placeholder="e.g. Senior Engineer"
                  className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-primary/10 placeholder:text-ink-faint/50" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold text-ink-mute uppercase tracking-wide mb-2">System Prompt</label>
              <textarea value={newTeammatePrompt} onChange={e => setNewTeammatePrompt(e.target.value)}
                rows={4} placeholder="Describe what this teammate does..."
                className="w-full px-4 py-3 rounded-xl bg-surface border border-hairline text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/10 resize-none placeholder:text-ink-faint/50" />
            </div>
          </motion.div>

          <div className="flex gap-3 pt-6">
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={handleCreateTeammate}
              disabled={creatingTeammate || !newTeammateName.trim()}
              className="flex-1 px-8 py-3.5 bg-primary text-white font-semibold text-sm rounded-pill shadow-md hover:shadow-lg disabled:opacity-50 transition-all flex items-center justify-center gap-2">
              {creatingTeammate
                ? <><motion.div animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}><Sparkles size={16} /></motion.div>Creating...</>
                : <><Plus size={16} /> Create Teammate</>}
            </motion.button>
            <button onClick={() => setStep('teammates')} className="px-6 py-3.5 text-sm font-semibold text-ink-mute hover:text-ink">
              Back
            </button>
          </div>
        </div>
      </motion.div>
    );
  }

  return null;
}
