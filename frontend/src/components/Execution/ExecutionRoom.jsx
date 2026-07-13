import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Activity, Clock, CheckCircle2, XCircle, Loader2, Radio, ChevronRight, Expand, Minimize } from 'lucide-react';
import * as api from '../../services/api';

const BASE = import.meta.env.VITE_API_BASE || '';

const STATUS_COLORS = {
  COMPLETED: 'text-green-600 bg-green-50',
  FAILED: 'text-red-500 bg-red-50',
  RUNNING: 'text-blue-600 bg-blue-50',
  PENDING: 'text-yellow-600 bg-yellow-50',
};

const STATUS_ICONS = {
  COMPLETED: CheckCircle2,
  FAILED: XCircle,
  RUNNING: Loader2,
  PENDING: Clock,
};

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function EventBadge({ type }) {
  const colors = {
    runtime_start: 'bg-blue-100 text-blue-700',
    teammate_start: 'bg-purple-100 text-purple-700',
    tool_call: 'bg-amber-100 text-amber-700',
    runtime_complete: 'bg-green-100 text-green-700',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[9px] font-medium ${colors[type] || 'bg-gray-100 text-gray-600'}`}>
      {type}
    </span>
  );
}

export default function ExecutionRoom() {
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [events, setEvents] = useState([]);
  const [live, setLive] = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const eventsEndRef = useRef(null);
  const evtSrcRef = useRef(null);

  useEffect(() => { loadExecutions(); }, [filterStatus]);

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const loadExecutions = async () => {
    setLoading(true);
    try {
      const data = await api.listExecutions(filterStatus, 30, 0);
      setExecutions(data.executions || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const connectSSE = (execId) => {
    if (evtSrcRef.current) { evtSrcRef.current.close(); }
    setLive(true);
    setEvents([]);
    const src = new EventSource(`${BASE}/api/executions/${execId}/stream`);
    evtSrcRef.current = src;
    src.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        setEvents(prev => [...prev, payload]);
      } catch {}
    };
    src.onerror = () => {
      setLive(false);
      src.close();
    };
  };

  const handleSelect = async (exec) => {
    setSelected(exec);
    try {
      const full = await api.getExecution(exec.execution_id);
      setEvents(full.events || []);
    } catch { setEvents([]); }
  };

  const handleLiveStream = (execId) => {
    api.getExecution(execId).then(r => {
      setSelected(r);
      setEvents(r.events || []);
    });
    connectSSE(execId);
  };

  // Cleanup on unmount
  useEffect(() => () => { if (evtSrcRef.current) evtSrcRef.current.close(); }, []);

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Sidebar: execution list */}
      <div className="w-72 border-r border-hairline flex flex-col bg-gray-50/50">
        <div className="p-3 border-b border-hairline">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={16} className="text-primary" />
            <h2 className="font-bold text-sm text-ink">Execution Room</h2>
          </div>
          <div className="flex gap-1">
            {['', 'RUNNING', 'COMPLETED', 'FAILED'].map(s => (
              <button key={s} onClick={() => setFilterStatus(s)}
                className={`px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
                  filterStatus === s ? 'bg-primary text-white' : 'bg-white border border-hairline text-ink-faint hover:bg-gray-100'
                }`}
              >{s || 'ALL'}</button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-8"><Loader2 size={16} className="animate-spin text-ink-faint" /></div>
          ) : executions.length === 0 ? (
            <div className="p-4 text-center text-[11px] text-ink-faint">暂无执行记录</div>
          ) : executions.map((e, i) => {
            const Icon = STATUS_ICONS[e.status] || Activity;
            return (
              <motion.button
                key={e.execution_id}
                initial={{ opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.02 }}
                onClick={() => handleSelect(e)}
                className={`w-full text-left p-3 border-b border-hairline hover:bg-white transition-all ${
                  selected?.execution_id === e.execution_id ? 'bg-white shadow-sm' : ''
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon size={12} className={STATUS_COLORS[e.status]?.split(' ')[0] || 'text-ink-faint'} />
                  <span className="text-[11px] font-medium text-ink truncate flex-1">{e.task_id || e.execution_id.slice(0, 12)}</span>
                  <ChevronRight size={10} className="text-ink-faint" />
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[9px] text-ink-faint">{e.teammate || '-'}</span>
                  {e.duration_ms > 0 && <span className="text-[9px] text-ink-faint">{(e.duration_ms / 1000).toFixed(1)}s</span>}
                  {e.total_tokens > 0 && <span className="text-[9px] text-ink-faint">{e.total_tokens}t</span>}
                </div>
              </motion.button>
            );
          })}
        </div>
      </div>

      {/* Main: execution timeline + live stream */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selected ? (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 p-3 border-b border-hairline bg-white">
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_COLORS[selected.status] || ''}`}>
                {selected.status}
              </span>
              <span className="text-xs text-ink-faint">Task: {selected.task_id?.slice(0, 16) || '-'}</span>
              <span className="text-xs text-ink-faint">Teammate: {selected.teammate || '-'}</span>
              {selected.duration_ms > 0 && <span className="text-xs text-ink-faint">{(selected.duration_ms / 1000).toFixed(1)}s</span>}
              {selected.total_tokens > 0 && <span className="text-xs text-ink-faint">{selected.total_tokens} tokens</span>}
              <div className="flex-1" />
              <button
                onClick={() => handleLiveStream(selected.execution_id)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all ${
                  live ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-ink-faint hover:bg-gray-200'
                }`}
              >
                <Radio size={11} className={live ? 'animate-pulse' : ''} />
                {live ? 'LIVE' : 'Stream'}
              </button>
            </div>

            {/* Timeline */}
            <div className="flex-1 overflow-y-auto p-4 space-y-2 bg-gray-50/30">
              {events.length === 0 ? (
                <div className="text-center py-8 text-[11px] text-ink-faint">暂无事件</div>
              ) : events.map((evt, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.01 }}
                  className="bg-white rounded-lg border border-hairline p-3"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <EventBadge type={evt.type} />
                    <span className="text-[9px] text-ink-faint">{formatTime(evt.timestamp)}</span>
                  </div>
                  <pre className="text-[10px] text-ink-mute whitespace-pre-wrap font-mono leading-relaxed">
                    {JSON.stringify(evt.data, null, 2)}
                  </pre>
                </motion.div>
              ))}
              <div ref={eventsEndRef} />
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-ink-faint gap-2">
            <Radio size={20} className="text-ink-faint/40" />
            选择左侧执行记录查看时间线
          </div>
        )}
      </div>
    </div>
  );
}
