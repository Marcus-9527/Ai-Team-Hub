import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Hash, Bot, User, X, Loader2,
  Trash2, Paperclip, Image,
  FileText, Eraser, Settings, Users,
  UserPlus, UserMinus,
} from 'lucide-react';
import * as api from '../../services/api';
import { parseSSEBuffer } from '../../services/eventBus';
import { useTranslation } from '../../i18n';
import { dispatchTaskEvent, isTaskEventType } from '../../services/taskEventBus';

export default function ChannelView({ channelId, triggerRefresh, refreshKey }) {
  const t = useTranslation();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [channel, setChannel] = useState(null);
  const [teammates, setTeammates] = useState([]);
  const [teammatesById, setTeammatesById] = useState({});
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploadStatus, setUploadStatus] = useState({});
  const [showActions, setShowActions] = useState(false);
  const [showMemberList, setShowMemberList] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);
  const [showMention, setShowMention] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [mentionStartPos, setMentionStartPos] = useState(-1);
  const [selectedMentionIdx, setSelectedMentionIdx] = useState(0);

  useEffect(() => { loadChannel(); }, [channelId, refreshKey]);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const loadChannel = async () => {
    try {
      const [chData, msgs, allTeammates] = await Promise.all([
        api.listChannels().then(chs => chs.find(c => c.id === channelId)),
        api.listMessages(channelId),
        api.listTeammates(),
      ]);
      setChannel(chData);
      // RECONCILE: use backend message_id directly as the unique group key
      const reconciled = msgs.map(m => ({
        ...m,
        message_id: m.message_id || m.id,  // fallback to DB id if message_id not set yet
      }));
      setMessages(reconciled);
      setTeammates(allTeammates);
      const map = {};
      allTeammates.forEach(tm => { map[tm.id] = tm; });
      setTeammatesById(map);
    } catch (e) { console.error(e); }
  };

  // Get teammates in this channel
  const channelTeammates = (channel?.teammate_ids || [])
    .map(id => teammatesById[id])
    .filter(Boolean);

  // Filtered list for @mention popup
  const filteredMentions = showMention
    ? channelTeammates.filter(tm => tm.name.toLowerCase().includes(mentionFilter.toLowerCase()))
    : [];

  /**
   * Direct SSE event handler — no EventBus, no normalization.
   * Backend events directly update message state.
   *
   * Unified message key: message_id (per-teammate uuid, unique per request)
   * NO author_id, NO group_id, NO teammate_start event.
   * Each teammate_message with same message_id appends to the same bubble.
   */
  const handleStreamEvent = useCallback((event) => {
    const { type, message_id, role, phase, payload } = event || {};
    if (!type || !message_id) return;

    // ── Dispatch task events to global bus (V3.0 Phase A) ──
    if (isTaskEventType(type)) {
      dispatchTaskEvent(event);
      // Task events don't render as chat bubbles, but we log them
      console.log('[ChannelView] task event:', type, event);
      return; // Don't render task events as chat bubbles
    }

    // ONLY teammate_message creates/updates bubbles
    // teammate_end → no-op (bubble already created by teammate_message)
    if (type === 'teammate_message') {
      const { content, author_name, teammate_id: payloadTmId } = payload || {};
      const teammate_id = payloadTmId || role;  // payload has real UUID, fallback role
      const author = channelTeammates.find(t => t.id === teammate_id);
      const displayAuthorName = author?.name || author_name || 'Team';
      const displayAvatar = author?.avatar_emoji || '�';

      setMessages(prev => {
        // STRICT dedup: only append if SAME message_id AND role='team'
        const existing = prev.find(m => m.message_id === message_id && m.role === 'team');
        if (existing) {
          return prev.map(m =>
            m.id === existing.id
              ? { ...m, content: m.content + content }
              : m
          );
        }
        // New message_id → new bubble (never merge across teammate/phase/message)
        return [...prev, {
          id: 'msg-' + message_id,
          role: 'team',
          author_name: displayAuthorName,
          teammate_id: teammate_id,
          message_id: message_id,
          avatar_emoji: displayAvatar,
          content: content || '',
          phase: phase || '',
          created_at: new Date().toISOString(),
        }];
      });
    }

    // teammate_end — no-op, bubble already rendered by teammate_message
    if (type === 'teammate_end') {
      // No UI action needed (bubble is already complete)
    }

    if (type === 'error') {
      setMessages(prev => [...prev, {
        id: 'err-' + message_id + '-' + Date.now(),
        role: 'system',
        author_name: 'System',
        teammate_id: '',
        avatar_emoji: '⚠️',
        content: payload?.message || 'An error occurred',
        created_at: new Date().toISOString(),
      }]);
    }
  }, [channelTeammates]);

  // Track messages count for debugging
  useEffect(() => {
    const teamMsgs = messages.filter(m => m.role === 'team');
    console.log(`[DEBUG] messages updated: total=${messages.length}, team=${teamMsgs.length}`, teamMsgs.map(m => `${m.author_name}[${m.message_id?.slice(-8)}]: ${m.content.slice(0,20)}`));
  }, [messages]);

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    setPendingFiles(prev => [...prev, ...files]);
    e.target.value = '';
  };

  const removeFile = (idx) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSend = async () => {
    console.log('[ChannelView] handleSend called, version=2026-07-04-mention');
    let content = input.trim();
    let teammateIds = null;

    // Parse consecutive @mentions from the start — collect all mentioned teammate IDs
    const ids = [];
    const mentionBlock = content.match(/^(?:@\S+\s*)+/);
    if (mentionBlock) {
      const names = mentionBlock[0].match(/@(\S+)/g);
      if (names) {
        for (const n of names) {
          const name = n.slice(1);
          const tm = channelTeammates.find(t =>
            t.name.toLowerCase() === name.toLowerCase()
          );
          if (tm) ids.push(tm.id);
        }
      }
      content = content.slice(mentionBlock[0].length).trim();
    }
    if (ids.length > 0) teammateIds = ids;

    const hasText = content.length > 0;
    const hasFiles = pendingFiles.length > 0;
    if ((!hasText && !hasFiles) || loading) return;

    setInput('');
    const filesToSend = [...pendingFiles];
    setPendingFiles([]);

    if (hasFiles) {
      for (const file of filesToSend) {
        setUploadStatus(prev => ({ ...prev, [file.name]: 'reading' }));
        try {
          const res = await api.uploadFileMsg(channelId, file, 'You');
          if (!res.ok) {
            const errText = await res.text();
            throw new Error(errText);
          }
          setUploadStatus(prev => ({ ...prev, [file.name]: 'done' }));
          setTimeout(() => setUploadStatus(prev => {
            const next = { ...prev };
            delete next[file.name];
            return next;
          }), 3000);
        } catch (e) {
          setUploadStatus(prev => ({ ...prev, [file.name]: 'error' }));
          setMessages(prev => [...prev, { id: 'err-' + Date.now(), role: 'system', author_name: 'System', content: `File upload failed: ${e.message}` }]);
        }
      }
      const msgs = await api.listMessages(channelId);
      setMessages(msgs);
    }

    if (!hasText) return;

    // Show user message with original @mention visible
    const displayContent = input.trim();
    const userMsg = { id: 'temp-' + Date.now(), role: 'user', author_name: 'You', content: displayContent, created_at: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);

    setLoading(true);

    try {
      const response = await api.sendMessage(channelId, content, 'You', teammateIds);
      if (!response.ok) {
        const errText = await response.text();
        let errMsg = errText;
        try { errMsg = JSON.parse(errText).detail || errText; } catch {}
        throw new Error(errMsg);
      }
      // Phase 3: JSON event stream, no string parsing
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE parse: split on double newline (event boundaries)
        const parts = buffer.split('\n\n');
        buffer = parts.pop(); // Keep incomplete last part

        for (const part of parts) {
          const events = parseSSEBuffer(part + '\n\n');
          for (const event of events) {
            handleStreamEvent(event);
          }
        }
      }

      // Process remaining buffer
      if (buffer.trim()) {
        const events = parseSSEBuffer(buffer);
        for (const event of events) {
          handleStreamEvent(event);
        }
      }
      setLoading(false);

    } catch (e) {
      setMessages(prev => [...prev, {
        id: 'err-' + Date.now(),
        role: 'system',
        author_name: 'System',
        content: t('channel.error', e.message),
      }]);
    }
    setLoading(false);
  };

  const handleKeyDown = (e) => {
    if (showMention && filteredMentions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedMentionIdx(prev => Math.min(prev + 1, filteredMentions.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedMentionIdx(prev => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        selectMention(filteredMentions[selectedMentionIdx]);
        return;
      }
      if (e.key === 'Escape') {
        setShowMention(false);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // ── @mention handlers ──
  const handleInputChange = (e) => {
    const val = e.target.value;
    const pos = e.target.selectionStart;
    setInput(val);
    setShowMention(false);

    const textBefore = val.slice(0, pos);
    const lastAt = textBefore.lastIndexOf('@');
    if (lastAt === -1) return;

    const afterAt = textBefore.slice(lastAt + 1);
    // Must be a word (no spaces) and preceded by space or start of line
    if (/\s/.test(afterAt)) return;
    if (lastAt > 0 && textBefore[lastAt - 1] !== ' ' && textBefore[lastAt - 1] !== '\n') return;

    setShowMention(true);
    setMentionFilter(afterAt);
    setMentionStartPos(lastAt);
    setSelectedMentionIdx(0);
  };

  const selectMention = (tm) => {
    const before = input.slice(0, mentionStartPos);
    const after = input.slice(inputRef.current?.selectionStart || mentionStartPos + 1 + mentionFilter.length);
    const newVal = before + '@' + tm.name + ' ' + after;
    setInput(newVal);
    setShowMention(false);
    inputRef.current?.focus();
  };

  return (
    <>
    <div className="flex-1 flex flex-col h-full bg-canvas">
      {/* Channel Header with Member List */}
      <div className="h-auto min-h-14 flex flex-col border-b border-hairline bg-surface/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3 px-5 py-2.5">
          <Hash size={18} className="text-ink-faint flex-shrink-0" />
          <h2 className="font-bold text-[15px] text-ink">{channel?.name || 'Loading...'}</h2>
          <span className="text-xs text-ink-faint hidden md:inline truncate">{channel?.description}</span>
          <div className="ml-auto flex items-center gap-2 flex-shrink-0">
            {/* Member count badge → clickable manage teammates */}
            <div className="relative">
              <button
                onClick={() => setShowMemberList(!showMemberList)}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-canvas-lavender/50 text-xs text-ink-mute hover:bg-canvas-lavender/70 transition-all"
              >
                <Users size={12} />
                <span>{channelTeammates.length}</span>
              </button>
              <AnimatePresence>
                {showMemberList && (
                  <motion.div
                    initial={{ opacity: 0, y: -4, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -4, scale: 0.95 }}
                    className="absolute right-0 top-full mt-2 w-64 bg-surface rounded-xl shadow-card-lg border border-hairline py-1 z-50"
                    onClick={e => e.stopPropagation()}
                  >
                    <div className="px-4 py-2 text-xs font-semibold text-ink-faint uppercase tracking-wider border-b border-hairline">
                      {t('channel.manage_teammates')} ({teammates.length})
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      {teammates.length === 0 && (
                        <p className="text-xs text-ink-faint text-center py-4">{t('channel.no_teammates_in_modal')}</p>
                      )}
                      {teammates.map(tm => {
                        const inChannel = (channel?.teammate_ids || []).includes(tm.id);
                        return (
                          <div key={tm.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-hover transition-colors">
                            <span className="text-base">{tm.avatar_emoji || '🤖'}</span>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-semibold text-ink truncate">{tm.name}</p>
                              <p className="text-[10px] text-ink-faint truncate">{tm.model_provider} / {tm.model_name}</p>
                            </div>
                            {inChannel ? (
                              <button
                                onClick={async () => {
                                  await api.removeTeammateFromChannel(channelId, tm.id);
                                  setChannel(prev => ({ ...prev, teammate_ids: (prev?.teammate_ids || []).filter(id => id !== tm.id) }));
                                  setMessages(prev => [...prev, { id: 'sys-' + Date.now(), role: 'system', author_name: 'System', content: `${tm.avatar_emoji} ${tm.name} removed from channel` }]);
                                }}
                                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-semantic-error hover:bg-red-50 transition-colors"
                              >
                                <UserMinus size={13} /> {t('channel.remove')}
                              </button>
                            ) : (
                              <button
                                onClick={async () => {
                                  await api.addTeammateToChannel(channelId, tm.id);
                                  setChannel(prev => ({ ...prev, teammate_ids: [...(prev?.teammate_ids || []), tm.id] }));
                                  setMessages(prev => [...prev, { id: 'sys-' + Date.now(), role: 'system', author_name: 'System', content: `${tm.avatar_emoji} ${tm.name} added to channel` }]);
                                }}
                                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-primary hover:bg-primary/5 transition-colors"
                              >
                                <UserPlus size={13} /> {t('channel.add')}
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <div className="relative">
              <button
                onClick={() => setShowActions(!showActions)}
                className="p-1.5 rounded-lg hover:bg-surface-hover text-ink-faint hover:text-ink transition-all"
                title={t('channel.actions')}
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
                    <button
                      onClick={async () => {
                        setShowActions(false);
                        if (!confirm(t('channel.clear_confirm_short') || 'Clear messages?')) return;
                        try {
                          const result = await api.clearMessages(channelId);
                          setMessages([]);
                          if (result?.deleted > 0) {
                            setMessages([{
                              id: 'system-cleared-' + Date.now(),
                              role: 'system',
                              author_name: 'System',
                              content: `Cleared ${result.deleted} messages`,
                            }]);
                          }
                        } catch (e) {
                          setMessages([]);
                        }
                      }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-ink hover:bg-surface-hover transition-colors"
                    >
                      <Eraser size={15} className="text-amber-500" />
                      <span className="text-xs font-semibold">{t('channel.clear')}</span>
                    </button>
                    <div className="border-t border-hairline my-1" />
                    <button
                      onClick={async () => {
                        setShowActions(false);
                        if (!confirm(t('channel.delete_confirm_no_name') || 'Delete this channel?')) return;
                        await api.deleteChannel(channelId);
                        triggerRefresh();
                      }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-ink hover:bg-red-50 hover:text-semantic-error transition-colors"
                    >
                      <Trash2 size={15} className="text-semantic-error" />
                      <span className="text-xs font-semibold">{t('channel.delete')}</span>
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
        {/* Teammate member list bar */}
        {channelTeammates.length > 0 && (
          <div className="flex items-center gap-1.5 px-5 pb-2.5 overflow-x-auto">
            {channelTeammates.map(tm => (
              <div
                key={tm.id}
                className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-canvas-lavender/40 border border-hairline/50 flex-shrink-0"
                title={tm.system_prompt ? tm.system_prompt.slice(0, 60) + '...' : tm.name}
              >
                <span className="text-sm leading-none">{tm.avatar_emoji || '🤖'}</span>
                <span className="text-[11px] font-medium text-ink-mute whitespace-nowrap">{tm.name}</span>
                {tm.system_prompt && (
                  <span className="text-[9px] text-ink-faint whitespace-nowrap max-w-[120px] truncate">
                    · {tm.system_prompt.slice(0, 15)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Removed: old inline manage panel */}
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-3 md:px-5 py-4 space-y-2">
        {messages.map(msg => {
          if (msg.role === 'system') return <SystemMessage key={msg.id} message={msg} />;
          if (msg.role === 'loading') return <LoadingBubble key={msg.id} message={msg} />;
          if (msg.role === 'team') return <TeamMessageBubble key={msg.id} message={msg} teammatesById={teammatesById} />;
          return <MessageBubble key={msg.id} message={msg} teammatesById={teammatesById} />;
        })}

        {/* Loading indicator */}
        {loading && (
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center text-sm border-2 border-surface">
              <Loader2 size={14} className="animate-spin text-ink-faint" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-3 md:p-4 border-t border-hairline bg-surface/80 backdrop-blur-sm flex-shrink-0">
        {pendingFiles.length > 0 && (
          <div className="flex flex-col gap-1.5 mb-2 max-w-4xl mx-auto">
            {pendingFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2 bg-surface border border-hairline rounded-xl text-xs">
                <div className="w-7 h-7 rounded-lg bg-canvas-lavender flex items-center justify-center flex-shrink-0">
                  {f.type?.startsWith('image/') ? <Image size={14} className="text-primary" /> : <FileText size={14} className="text-primary" />}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-ink font-medium truncate block max-w-[200px]">{f.name}</span>
                  <span className="text-ink-faint text-[10px]">{(f.size / 1024).toFixed(1)} KB</span>
                </div>
                <button onClick={() => removeFile(i)} className="p-1 hover:text-semantic-error rounded"><X size={14} /></button>
              </div>
            ))}
          </div>
        )}
        <div className="max-w-4xl mx-auto">
          {/* @mention popup */}
          <AnimatePresence>
            {showMention && filteredMentions.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 4, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 4, scale: 0.95 }}
                className="mb-2 bg-surface border border-hairline rounded-xl shadow-card-lg overflow-hidden"
              >
                <div className="px-3 py-1.5 text-[10px] text-ink-faint font-semibold uppercase tracking-wider border-b border-hairline/50">
                  选择队友 · {filteredMentions.length} 人
                </div>
                <div className="max-h-36 overflow-y-auto">
                  {filteredMentions.map((tm, idx) => (
                    <button
                      key={tm.id}
                      onMouseDown={(e) => { e.preventDefault(); selectMention(tm); }}
                      onMouseEnter={() => setSelectedMentionIdx(idx)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm text-left transition-colors ${
                        idx === selectedMentionIdx
                          ? 'bg-primary/10 text-primary'
                          : 'text-ink hover:bg-surface-hover'
                      }`}
                    >
                      <span className="text-base">{tm.avatar_emoji || '🤖'}</span>
                      <span className="font-semibold">{tm.name}</span>
                      <span className="text-[10px] text-ink-faint ml-auto truncate max-w-[100px]">
                        {tm.role || tm.model_name || ''}
                      </span>
                    </button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="relative flex items-end bg-surface/40 hover:bg-surface/70 rounded-2xl transition-colors">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-9 h-9 ml-1 mb-1 rounded-lg text-ink-faint/60 hover:text-ink-mute hover:bg-surface-hover/60 flex items-center justify-center flex-shrink-0 transition-all"
              title="Attach file"
            >
              <Paperclip size={16} />
            </button>
            <input ref={fileInputRef} type="file" multiple accept="image/*,.pdf,.txt,.md,.csv,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.py,.js,.ts,.json,.html,.css" onChange={handleFileSelect} className="hidden" />
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={t('channel.message_placeholder') || "输入消息... @选择队友"}
              className="flex-1 bg-transparent px-2 py-2.5 text-sm text-ink placeholder-ink-faint/50 resize-none focus:outline-none"
              rows={1} style={{ minHeight: '42px', maxHeight: '120px' }} disabled={loading}
            />
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
        {Object.keys(uploadStatus).length > 0 && (
          <div className="max-w-4xl mx-auto px-2 pb-1 flex flex-wrap gap-2">
            {Object.entries(uploadStatus).map(([name, status]) => (
              <span key={name} className={`text-xs px-2 py-0.5 rounded-full flex items-center gap-1 ${
                status === 'done' ? 'bg-emerald-500/10 text-emerald-400' :
                status === 'error' ? 'bg-red-500/10 text-red-400' :
                'bg-primary/10 text-primary'
              }`}>
                {status === 'done' ? '✓' : status === 'error' ? '✗' : '⋯'}
                <span className="max-w-[120px] truncate">{name}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>

    </>
  );
}

// ─── Loading Bubble (per-teammate "thinking..." indicator) ───
function LoadingBubble({ message }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center text-sm flex-shrink-0">
        {message.avatar_emoji || '🤖'}
      </div>
      <div className="max-w-[75%]">
        <p className="text-[11px] font-semibold mb-1 text-ink-mute">{message.author_name}</p>
        <div className="px-4 py-3 rounded-2xl bg-canvas-lavender/50 text-ink-faint rounded-tl-sm flex items-center gap-1">
          <span className="text-xs">{t('channel.thinking')}</span>
          <span className="flex gap-0.5 ml-1">
            <span className="w-1 h-1 bg-ink-faint/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 bg-ink-faint/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 bg-ink-faint/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── System Message (join/leave/clear) ───
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


function MessageBubble({ message, teammatesById }) {
  const isUser = message.role === 'user';
  const hasAttachments = message.attachments?.length > 0;
  // Look up teammate info from teammatesById for AI messages
  const tmId = message.teammate_id || message.author_id;
  const tm = !isUser && tmId ? teammatesById[tmId] : null;
  const avatarDisplay = tm?.avatar_emoji || message.avatar_emoji || (isUser ? null : '🤖');

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', damping: 25, stiffness: 300, mass: 0.8 }}
      className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      <div className={`w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 text-base ${isUser ? 'bg-primary text-white' : 'bg-canvas-lavender'}`}>
        {isUser ? <User size={16} /> : avatarDisplay}
      </div>
      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>
        <p className={`text-[11px] font-semibold mb-1 ${isUser ? 'text-right text-ink-mute' : 'text-ink-mute'}`}>
          {tm?.name || message.author_name}
        </p>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed message-content ${!isUser ? 'bg-canvas-lavender text-ink rounded-tl-sm' : 'bg-primary text-white rounded-tr-sm'}`}>
          <div className="message-text">
            {message.content.split('\n').map((line, i) => (
              <p key={i} className={i > 0 ? 'mt-1' : ''}>{line}</p>
            ))}
          </div>
        </div>
        {hasAttachments && (
          <div className="mt-2 flex flex-col gap-1.5">
            {message.attachments.map((att, i) => (
              <div key={i} className="flex items-start gap-2 px-3 py-2 bg-surface border border-hairline rounded-xl text-xs">
                <div className="w-8 h-8 rounded-lg bg-canvas-lavender flex items-center justify-center flex-shrink-0 mt-0.5">
                  {att.is_image || att.mime?.startsWith('image/') ? <Image size={16} className="text-primary" /> : <FileText size={16} className="text-primary" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-ink font-medium truncate max-w-[180px]">{att.filename}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-emerald-500/10 text-emerald-400">
                      {att.status === 'ready' ? '✓ Ready' : att.status === 'indexed' ? '✓ Done' : '↑ Uploaded'}
                    </span>
                  </div>
                  {att.preview_text && att.preview_text !== '[Image]' && (
                    <p className="text-ink-faint text-[11px] mt-1 line-clamp-2 leading-relaxed">{att.preview_text}</p>
                  )}
                  <div className="flex items-center gap-2 mt-1 text-[10px] text-ink-faint">
                    <span>{(att.size / 1024).toFixed(1)} KB</span>
                    {att.chunk_count > 0 && <span>· {att.chunk_count} chunks</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ─── Team Message Bubble (WeChat-style: one teammate = one bubble) ───
function TeamMessageBubble({ message, teammatesById }) {
  const tmId = message.teammate_id || message.author_id;
  const tm = tmId ? teammatesById?.[tmId] : null;
  const avatar = tm?.avatar_emoji || message.avatar_emoji || '🤖';
  const name = tm?.name || message.author_name || 'Team';

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', damping: 25, stiffness: 300, mass: 0.8 }}
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center text-base flex-shrink-0">
          {avatar}
        </div>
        <div className="max-w-[75%]">
          <p className="text-[11px] font-semibold mb-1 text-ink-mute">{name}</p>
          <div className="px-4 py-3 rounded-2xl text-sm leading-relaxed bg-canvas-lavender text-ink rounded-tl-sm message-content">
            <div className="message-text">
              {message.content.split('\n').filter(l => l.trim()).map((line, i) => (
                <p key={i} className={i > 0 ? 'mt-1' : ''}>{line}</p>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Individual Teammate Response Bubble ───
function TeamResponseBubble({ response }) {
  if (response.type === 'team' || !response.author) {
    return (
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center text-sm">
          <Bot size={16} className="text-primary" />
        </div>
        <div className="max-w-[75%]">
          <p className="text-[11px] font-semibold mb-1 text-ink-mute">Team</p>
          <div className="px-4 py-3 rounded-2xl text-sm leading-relaxed bg-canvas-lavender text-ink rounded-tl-sm">
            <div className="message-text">
              {response.content.split('\n').filter(l => l.trim()).map((line, i) => (
                <p key={i} className={i > 0 ? 'mt-1' : ''}>{line}</p>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const author = response.author;
  const personaTag = author.system_prompt ? author.system_prompt.slice(0, 15) : '';

  return (
    <div className="flex items-start gap-3">
      <div className="w-9 h-9 rounded-full bg-canvas-lavender flex items-center justify-center text-sm flex-shrink-0">
        {author.avatar_emoji || '🤖'}
      </div>
      <div className="max-w-[75%]">
        <div className="flex items-center gap-2 mb-1">
          <p className="text-[11px] font-semibold text-ink-mute">{author.name}</p>
          {personaTag && (
            <span className="text-[9px] text-ink-faint bg-surface-active/60 px-1.5 py-0.5 rounded-full">
              {personaTag}
            </span>
          )}
        </div>
        <div className="px-4 py-3 rounded-2xl text-sm leading-relaxed bg-canvas-lavender text-ink rounded-tl-sm">
          <div className="message-text">
            {response.content.split('\n').filter(l => l.trim()).map((line, i) => (
              <p key={i} className={i > 0 ? 'mt-1' : ''}>{line}</p>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}


