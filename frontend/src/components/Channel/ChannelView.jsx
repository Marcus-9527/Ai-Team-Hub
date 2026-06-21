import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Hash, Bot, User, X, Loader2,
  ChevronDown, Plus, Trash2, Paperclip, Image,
  FileText, Eraser, Settings,
} from 'lucide-react';
import * as api from '../../services/api';
import { useTranslation } from '../../i18n';

export default function ChannelView({ channelId, triggerRefresh, refreshKey }) {
  const t = useTranslation();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [streamingAuthor, setStreamingAuthor] = useState('');
  const [channel, setChannel] = useState(null);
  const [teammates, setTeammates] = useState([]);
  const [channelTeammates, setChannelTeammates] = useState([]);
  const [selectedTeammate, setSelectedTeammate] = useState(null);
  const [showPicker, setShowPicker] = useState(false);
  const [showAddTeammate, setShowAddTeammate] = useState(false);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [showActions, setShowActions] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);
  const pickerRef = useRef(null);
  const actionsRef = useRef(null);

  useEffect(() => { loadChannel(); }, [channelId, refreshKey]);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, streamingContent]);
  useEffect(() => {
    const handleClick = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        setShowPicker(false);
        setShowAddTeammate(false);
      }
      if (actionsRef.current && !actionsRef.current.contains(e.target)) {
        setShowActions(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const loadChannel = async () => {
    try {
      const [chData, msgs, allTeammates] = await Promise.all([
        api.listChannels().then(chs => chs.find(c => c.id === channelId)),
        api.listMessages(channelId),
        api.listTeammates(),
      ]);
      setChannel(chData);
      setMessages(msgs);
      setTeammates(allTeammates);
      const chTeammates = (chData?.teammate_ids || [])
        .map(id => allTeammates.find(t => t.id === id)).filter(Boolean);
      setChannelTeammates(chTeammates);
      // Default: no specific selection → ALL teammates respond
      // User can click a specific one in the picker for single response
      setSelectedTeammate(prev => prev && chTeammates.find(t => t.id === prev.id) ? prev : null);
    } catch (e) { console.error(e); }
  };

  // ── File handling ──
  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    setPendingFiles(prev => [...prev, ...files]);
    e.target.value = '';
  };

  const removeFile = (idx) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== idx));
  };

  // ── Send ──
  const handleSend = async () => {
    const hasText = input.trim().length > 0;
    const hasFiles = pendingFiles.length > 0;
    if ((!hasText && !hasFiles) || loading) return;

    const content = input;
    setInput('');
    const filesToSend = [...pendingFiles];
    setPendingFiles([]);

    if (hasFiles) {
      for (const file of filesToSend) {
        try {
          await api.uploadFileMsg(channelId, file, 'You');
        } catch (e) {
          setMessages(prev => [...prev, { id: 'err-' + Date.now(), role: 'ai', author_name: 'System', content: t('channel.upload_failed', e.message) }]);
        }
      }
      const msgs = await api.listMessages(channelId);
      setMessages(msgs);
    }

    if (!hasText) return;

    const userMsg = { id: 'temp-' + Date.now(), role: 'user', author_name: 'You', content, created_at: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);

    // ── Determine which AIs should respond ──
    const responders = selectedTeammate ? [selectedTeammate] : channelTeammates;

    if (responders.length > 0) {
      setLoading(true);
      for (let i = 0; i < responders.length; i++) {
        const tm = responders[i];
        
        // Show thinking indicator for this teammate
        setStreamingContent('');
        setStreamingAuthor(tm.name);
        
        try {
          // First AI call saves user message + streams; subsequent skip user save
          const response = await api.sendMessage(channelId, content, tm.id, 'You', null, i > 0);
          if (!response.ok) {
            const errText = await response.text();
            let errMsg = errText;
            try { errMsg = JSON.parse(errText).detail || errText; } catch {}
            throw new Error(errMsg);
          }
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let fullText = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            fullText += decoder.decode(value, { stream: true });
            setStreamingContent(fullText);
          }
          // Add this AI's completed response
          setMessages(prev => [...prev, {
            id: 'ai-' + tm.id + '-' + Date.now(),
            role: 'ai',
            author_name: tm.name,
            author_id: tm.id,
            content: fullText,
            created_at: new Date().toISOString(),
          }]);
        } catch (e) {
          setMessages(prev => [...prev, {
            id: 'err-' + Date.now(),
            role: 'ai',
            author_name: tm.name,
            content: t('channel.error', e.message),
          }]);
        }
      }
      setStreamingContent('');
      setStreamingAuthor('');
      setLoading(false);
    } else {
      await api.sendMessage(channelId, content, null);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // ── Teammate management ──
  const handleAddTeammate = async (teammateId) => {
    try {
      const tm = teammates.find(t2 => t2.id === teammateId);
      await api.addTeammateToChannel(channelId, teammateId);
      await api.sendSystemMessage(channelId, `${tm?.avatar_emoji || '🤖'} ${tm?.name || ''} ${t('channel.join')}`);
      setShowAddTeammate(false);
      setShowPicker(false);
      loadChannel();
      triggerRefresh();
    } catch (e) { console.error(e); }
  };

  const handleRemoveTeammate = async (teammateId) => {
    try {
      const tm = channelTeammates.find(ct => ct.id === teammateId);
      await api.removeTeammateFromChannel(channelId, teammateId);
      await api.sendSystemMessage(channelId, `${tm?.avatar_emoji || '🤖'} ${tm?.name || ''} ${t('channel.left')}`);
      if (selectedTeammate?.id === teammateId) setSelectedTeammate(null);
      loadChannel();
      triggerRefresh();
    } catch (e) { console.error(e); }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-canvas">
      {/* Header */}
      <div className="h-14 flex items-center gap-3 px-5 border-b border-hairline bg-surface/80 backdrop-blur-sm flex-shrink-0">
        <Hash size={18} className="text-ink-faint" />
        <h2 className="font-bold text-[15px] text-ink">{channel?.name || 'Loading...'}</h2>
        <span className="text-xs text-ink-faint hidden md:inline">{channel?.description}</span>
        <div className="ml-auto flex items-center gap-2" ref={pickerRef}>
          {/* ── Channel Actions Dropdown ── */}
          <div className="relative" ref={actionsRef}>
            <button
              onClick={() => setShowActions(!showActions)}
              className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint hover:text-ink transition-all"
              title={t('channel.actions') || '频道操作'}
            >
              <Settings size={16} />
            </button>
            <AnimatePresence>
              {showActions && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.95 }}
                  className="absolute right-0 top-full mt-2 w-56 bg-surface rounded-xl shadow-card-lg border border-hairline py-1.5 z-50"
                >
                  {/* Clear chat */}
                  <button
                    onClick={async () => {
                      setShowActions(false);
                      if (!confirm(t('channel.clear_confirm', channel?.name || ''))) return;
                      try {
                        const result = await api.clearMessages(channelId);
                        setMessages([]);
                        // After clearing, reload channel to sync state
                        if (result?.deleted > 0) {
                          // Show a brief system-style notice
                          setMessages([{
                            id: 'system-cleared-' + Date.now(),
                            role: 'system',
                            author_name: 'System',
                            content: `已清空 ${result.deleted} 条消息`,
                          }]);
                        }
                      } catch (e) {
                        console.error('Failed to clear messages:', e);
                        // Still clear local state even if API fails
                        setMessages([]);
                      }
                    }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-ink hover:bg-surface-hover transition-colors"
                  >
                    <Eraser size={15} className="text-amber-500" />
                    <div className="flex-1 text-left">
                      <span className="block text-xs font-semibold">{t('channel.clear')}</span>
                      <span className="block text-[10px] text-ink-faint mt-0.5">{t('channel.clear_desc')}</span>
                    </div>
                  </button>
                  {/* Delete channel */}
                  <div className="border-t border-hairline my-1" />
                  <button
                    onClick={async () => {
                      setShowActions(false);
                      if (!confirm(t('channel.delete_confirm', channel?.name || ''))) return;
                      await api.deleteChannel(channelId);
                      triggerRefresh();
                    }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-ink hover:bg-red-50 hover:text-semantic-error transition-colors"
                  >
                    <Trash2 size={15} className="text-semantic-error" />
                    <div className="flex-1 text-left">
                      <span className="block text-xs font-semibold">{t('channel.delete')}</span>
                      <span className="block text-[10px] text-ink-faint mt-0.5">{t('channel.delete_desc')}</span>
                    </div>
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <div className="relative">
            <button
              onClick={() => setShowPicker(!showPicker)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-pill bg-canvas-lavender text-primary text-xs font-semibold hover:bg-canvas-lavender/80 transition-colors"
            >
              {selectedTeammate ? <><span>{selectedTeammate.avatar_emoji}</span><span>{selectedTeammate.name}</span></> : <><Bot size={14} /><span>All ({channelTeammates.length})</span></>}
              <ChevronDown size={12} />
            </button>
            <AnimatePresence>
              {showPicker && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.95 }}
                  className="absolute right-0 top-full mt-2 w-64 bg-surface rounded-xl shadow-card-lg border border-hairline py-2 z-50"
                >
                  <p className="px-4 py-1 text-[10px] font-semibold uppercase text-ink-faint tracking-wider">{t('sidebar.ai_teammates')}</p>
                  {/* All-mode option */}
                  <button
                    onClick={() => { setSelectedTeammate(null); setShowPicker(false); }}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
                      !selectedTeammate ? 'text-primary font-semibold bg-canvas-lavender' : 'text-ink hover:bg-surface-hover'}`}
                  >
                    <Bot size={16} />
                    <span>All ({channelTeammates.length}) — sequential</span>
                  </button>
                  {channelTeammates.length === 0 && <p className="px-4 py-2 text-xs text-ink-faint">{t('sidebar.no_channels')}</p>}
                  {channelTeammates.map(t => (
                    <button
                      key={t.id}
                      onClick={() => { setSelectedTeammate(t); setShowPicker(false); }}
                      className="w-full flex items-center gap-3 px-4 py-2 text-sm text-ink hover:bg-surface-hover transition-colors"
                    >
                      <span>{t.avatar_emoji}</span>
                      <span className="flex-1 text-left">{t.name}</span>
                      <button onClick={(e) => { e.stopPropagation(); handleRemoveTeammate(t.id); }} className="p-0.5 hover:bg-surface-active rounded"><X size={12} className="text-ink-faint" /></button>
                    </button>
                  ))}
                  <div className="border-t border-hairline mt-1 pt-1">
                    <button onClick={() => setShowAddTeammate(!showAddTeammate)} className="w-full flex items-center gap-2 px-4 py-2 text-xs font-semibold text-accent-teal hover:bg-surface-hover"><Plus size={14} />{t('channel.add_teammate')}</button>
                    {showAddTeammate && (
                      <div className="px-2 pb-1 max-h-40 overflow-y-auto">
                        {teammates.filter(t => !channelTeammates.find(ct => ct.id === t.id)).map(t => (
                          <button key={t.id} onClick={() => handleAddTeammate(t.id)} className="w-full flex items-center gap-3 px-3 py-1.5 text-xs text-ink hover:bg-surface-hover rounded-md">
                            <span>{t.avatar_emoji}</span><span>{t.name}</span><span className="ml-auto text-[10px] text-ink-faint">{t.model_provider}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 md:px-5 py-4 space-y-2">
        {messages.map(msg => {
          if (msg.role === 'system') return <SystemMessage key={msg.id} message={msg} />;
          return <MessageBubble key={msg.id} message={msg} />;
        })}
        {streamingContent && <MessageBubble message={{ id: 'streaming', role: 'ai', author_name: streamingAuthor, content: streamingContent }} streaming />}
        {loading && !streamingContent && (
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center"><Bot size={16} className="text-primary" /></div>
            <div className="ai-typing-indicator bg-canvas-lavender rounded-2xl px-4 py-3">
              <div className="ai-typing-dot" /><div className="ai-typing-dot" /><div className="ai-typing-dot" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 md:p-4 border-t border-hairline bg-surface/80 backdrop-blur-sm flex-shrink-0">
        {/* Pending files preview — above the input row */}
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2 max-w-4xl mx-auto">
            {pendingFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-1.5 px-2 py-1 bg-canvas-lavender rounded-lg text-[11px] font-medium text-primary">
                {f.type?.startsWith('image/') ? <Image size={12} /> : <FileText size={12} />}
                <span className="max-w-[100px] truncate">{f.name}</span>
                <button onClick={() => removeFile(i)} className="ml-0.5 hover:text-semantic-error"><X size={12} /></button>
              </div>
            ))}
          </div>
        )}
        <div className="max-w-4xl mx-auto">
          <div className="relative flex items-end bg-surface/40 hover:bg-surface/70 rounded-2xl transition-colors">
            {/* File upload button — inside left */}
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-9 h-9 ml-1 mb-1 rounded-lg text-ink-faint/60 hover:text-ink-mute hover:bg-surface-hover/60 flex items-center justify-center flex-shrink-0 transition-all"
              title="Attach file"
            >
              <Paperclip size={16} />
            </button>
            <input ref={fileInputRef} type="file" multiple accept="image/*,.pdf,.txt,.md,.csv" onChange={handleFileSelect} className="hidden" />

            {/* Textarea — flex-1, no border (parent has it) */}
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={selectedTeammate ? t('channel.message_placeholder', selectedTeammate.name) : t('channel.message_placeholder_noai')}
              className="flex-1 bg-transparent px-2 py-2.5 text-sm text-ink placeholder-ink-faint/50 resize-none focus:outline-none"
              rows={1} style={{ minHeight: '42px', maxHeight: '120px' }} disabled={loading}
            />

            {/* Send button — ghost icon, no bg */}
            <motion.button
              whileTap={{ scale: 0.85 }}
              onClick={handleSend}
              disabled={(!input.trim() && pendingFiles.length === 0) || loading}
              className="w-9 h-9 mr-1 mb-1 rounded-lg text-ink-faint/50 hover:text-primary hover:bg-primary/5 flex items-center justify-center disabled:opacity-20 disabled:cursor-not-allowed transition-all flex-shrink-0"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            </motion.button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── System Message ─── */
function SystemMessage({ message }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-center py-1"
    >
      <div className="flex items-center gap-2 px-4 py-1.5 bg-surface-active/60 rounded-pill">
        <div className="w-1 h-1 rounded-full bg-ink-faint/40" />
        <p className="text-[11px] text-ink-faint font-medium">{message.content}</p>
        <div className="w-1 h-1 rounded-full bg-ink-faint/40" />
      </div>
    </motion.div>
  );
}

/* ─── Message Bubble ─── */
function MessageBubble({ message, streaming }) {
  const isAI = message.role === 'ai';
  const isUser = message.role === 'user';
  const hasAttachments = message.attachments?.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', damping: 25, stiffness: 300, mass: 0.8 }}
      className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      <div className={`w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 text-sm ${isAI ? 'bg-canvas-lavender text-primary' : 'bg-primary text-white'} ${streaming ? 'animate-pulse-glow' : ''}`}>
        {isAI ? <Bot size={16} /> : <User size={16} />}
      </div>
      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>
        <p className={`text-[11px] font-semibold mb-1 ${isUser ? 'text-right text-ink-mute' : 'text-ink-mute'}`}>
          {message.author_name}{streaming && ' · typing...'}
        </p>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed message-content ${isAI ? 'bg-canvas-lavender text-ink rounded-tl-sm' : 'bg-primary text-white rounded-tr-sm'}`}>
          {streaming ? (
            <span>{message.content}<span className="inline-block w-1.5 h-4 bg-primary/40 ml-0.5 animate-pulse rounded-sm align-middle" /></span>
          ) : (
            <div dangerouslySetInnerHTML={{
              __html: message.content
                .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
                .replace(/`([^`]+)`/g, '<code>$1</code>')
                .replace(/\n/g, '<br/>')
            }} />
          )}
        </div>
        {/* File attachments */}
        {hasAttachments && !streaming && (
          <div className="mt-2 flex flex-wrap gap-2">
            {message.attachments.map((att, i) => (
              <div key={i} className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface border border-hairline rounded-lg text-xs">
                {att.mime?.startsWith('image/') ? <Image size={14} className="text-ink-mute" /> : <FileText size={14} className="text-ink-mute" />}
                <span className="text-ink-mute max-w-[120px] truncate">{att.filename}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
