# SDK Usage Guide

## Python

### Install

```bash
pip install ai-team-hub
# Or from source:
pip install ./sdk/python/
```

### Quick Start

```python
from ai_team_hub import Client

client = Client(api_key="cfut_your_key")
result = client.run("Analyze market trends for AI code editors")
print(result.result)
```

### With Options

```python
result = client.run(
    task="Write a Python script for data analysis",
    mode="debug",          # auto | control | debug
    budget=1.0,            # max cost in USD
    timeout=180,           # seconds
)

print(f"Status: {result.status}")
print(f"Latency: {result.latency}")
print(f"Trace: {result.trace_id}")
```

### One-Liner (no client setup)

```python
from ai_team_hub import run_task
result = run_task("Summarize Q3 results", api_key="cfut_y...")
```

### Workspace

```python
ws = client.create_workspace(
    title="Q3 Analysis",
    description="Quarterly data analysis project"
)
print(f"Workspace ID: {ws.workspace_id}")
```

### Trace & Observability

```python
result = client.run("Complex research task")
trace = client.get_trace(result.trace_id)

print(f"Steps: {len(trace.steps)}")
print(f"Agents used: {len(trace.agent_calls)}")
print(f"Cache hits: {trace.cache_hits}")
print(f"FSM transitions: {len(trace.fsm_transitions)}")

for step in trace.steps:
    print(f"  {step.step}: {step.latency_ms}ms")
```

### Chat (Simple Mode)

```python
resp = client.chat("What did we decide last time?")
print(resp.response)
```

### Error Handling

```python
from httpx import HTTPError

try:
    result = client.run("Task description")
    if result.ok():
        print(result.result)
    else:
        print(f"Failed: {result.message}")
except HTTPError as e:
    print(f"HTTP error: {e}")
```

---

## TypeScript / JavaScript

### Install

```bash
npm install ai-team-hub
```

### Quick Start

```typescript
import { Client } from 'ai-team-hub';

const client = new Client({ apiKey: 'cfut_your_key' });
const result = await client.run('Analyze market trends');
console.log(result.result);
```

### With Options

```typescript
const result = await client.run('Write a Python script', {
  mode: 'debug',
  budget: 1.0,
  timeout: 180,
});

console.log(`Status: ${result.status}`);
console.log(`Latency: ${result.latency}`);
console.log(`Trace: ${result.trace_id}`);
```

### React Example

```tsx
import { useState } from 'react';
import { Client } from 'ai-team-hub';

const client = new Client({ apiKey: process.env.REACT_APP_API_KEY });

function TaskRunner() {
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);

  const runTask = async (task: string) => {
    setLoading(true);
    try {
      const res = await client.run(task);
      setResult(res.result);
    } catch (err) {
      setResult(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button onClick={() => runTask('Analyze competitors')}>
        {loading ? 'Running...' : 'Run Analysis'}
      </button>
      <pre>{result}</pre>
    </div>
  );
}
```

### Node.js Express Integration

```javascript
const express = require('express');
const { Client } = require('ai-team-hub');

const app = express();
const client = new Client({ apiKey: process.env.API_KEY });

app.post('/api/run', async (req, res) => {
  try {
    const result = await client.run(req.body.task, {
      mode: req.body.mode || 'auto',
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(3000);
```

### Error Handling

```typescript
try {
  const result = await client.run('Complex task');
  if (result.status === 'ok') {
    console.log(result.result);
  }
} catch (err) {
  if (err.message.includes('401')) {
    console.error('Invalid API key');
  } else if (err.message.includes('429')) {
    console.error('Rate limited — retry later');
  }
}
```
