import { useState, useEffect, useMemo } from 'react';
import * as api from '../../services/api';

const STATUS_COLORS = {
  PENDING:    '#9ca3af',
  SCHEDULED:  '#3b82f6',
  RUNNING:    '#6366f1',
  COMPLETED:  '#22c55e',
  FAILED:     '#ef4444',
  SKIPPED:    '#9ca3af',
};

const NODE_W = 200;
const NODE_H = 72;
const GAP_Y = 30;

export default function DAGViewer({ steps = [] }) {
  const [teammateMap, setTeammateMap] = useState({});

  useEffect(() => {
    api.listTeammates().then(list => {
      const m = {};
      for (const t of list) m[t.id] = t.name;
      setTeammateMap(m);
    }).catch(() => {});
  }, []);

  const layout = useMemo(() => {
    const nodes = steps.map((s, i) => ({
      id: s.id,
      label: s.objective || `步骤 ${s.order}`,
      teammate: s.teammate_id ? (teammateMap[s.teammate_id] || s.teammate_id) : '',
      status: s.status,
      x: 0,
      y: i * (NODE_H + GAP_Y),
    }));
    const edges = [];
    for (let i = 0; i < nodes.length - 1; i++) {
      edges.push({
        from: nodes[i].id, to: nodes[i + 1].id,
        sx: nodes[i].x + NODE_W, sy: nodes[i].y + NODE_H / 2,
        ex: nodes[i + 1].x, ey: nodes[i + 1].y + NODE_H / 2,
      });
    }
    const h = nodes.length * (NODE_H + GAP_Y) - GAP_Y + 40;
    return { nodes, edges, w: NODE_W + 40, h: Math.max(h, 120) };
  }, [steps, teammateMap]);

  if (steps.length === 0) {
    return <div className="flex items-center justify-center h-32 text-xs text-ink-faint">暂无步骤</div>;
  }

  return (
    <div className="overflow-auto">
      <svg width={layout.w} height={layout.h} className="block mx-auto">
        {layout.edges.map((e, i) => (
          <g key={`edge-${i}`}>
            <line x1={e.sx} y1={e.sy} x2={e.ex} y2={e.ey} stroke="#d1d5db" strokeWidth="2" markerEnd="url(#arrowhead)" />
          </g>
        ))}
        <defs>
          <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polyline points="0 0, 8 3, 0 6" fill="#d1d5db" />
          </marker>
        </defs>
        {layout.nodes.map(n => {
          const c = STATUS_COLORS[n.status] || STATUS_COLORS.PENDING;
          return (
            <g key={n.id}>
              <rect x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx="10" ry="10" fill="white" stroke={c} strokeWidth="2" />
              <text x={n.x + 12} y={n.y + 20} fontSize="11" fontWeight="600" fill="#1f2937">
                {n.label.length > 22 ? n.label.slice(0, 22) + '…' : n.label}
              </text>
              <text x={n.x + 12} y={n.y + 38} fontSize="10" fill="#9ca3af">
                {n.teammate || '未分配'}
              </text>
              <circle cx={n.x + NODE_W - 14} cy={n.y + 16} r="5" fill={c} />
              <text x={n.x + NODE_W - 14} y={n.y + 58} fontSize="9" fill={c} textAnchor="middle" fontWeight="500">
                {n.status}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="text-[10px] text-ink-faint text-center mt-2">
        CSS/SVG 布局 · 如需拖拽/缩放请启用 React Flow
      </p>
    </div>
  );
}
