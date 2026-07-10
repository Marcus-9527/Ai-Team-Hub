/**
 * eventBus.js — SSE Parser utilities
 *
 * Only parseSSELine / parseSSEBuffer are used by ChannelView.jsx.
 * EventBus class and normalizeSSEEvent are dead code (deprecated v6.28).
 */

/**
 * Parse a single SSE line from a fetch stream.
 * Returns parsed JSON object or null.
 */
export function parseSSELine(line) {
  if (!line || !line.startsWith('data:')) return null;
  const jsonStr = line.slice(5).trim();
  if (!jsonStr || jsonStr === '[DONE]') return null;
  try {
    return JSON.parse(jsonStr);
  } catch {
    return null;
  }
}

/**
 * Parse a full SSE buffer into an array of events.
 */
export function parseSSEBuffer(buffer) {
  const events = [];
  const lines = buffer.split('\n');
  for (const line of lines) {
    const event = parseSSELine(line);
    if (event) events.push(event);
  }
  return events;
}
