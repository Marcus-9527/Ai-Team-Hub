/**
 * OrganizationRunView tests — rendering + API mock.
 *
 * Requires vitest + jsdom. Run: npx vitest run
 * Install: npm i -D vitest jsdom
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as api from '../services/api';

// ── Mocks ──
vi.mock('../services/api');

const mockStatus = {
  run_id: 'test-run-1', status: 'active',
  current_action: { action_type: 'respond', status: 'running' },
  progress_state: { responded: false },
  latest_event: { event_type: 'run.created', payload: {}, timestamp: '2026-07-23T10:00:00Z' },
};

const mockTimeline = [
  { event_id: 'ev-1', event_type: 'run.created', payload: {}, timestamp: '2026-07-23T10:00:00Z' },
  { event_id: 'ev-2', event_type: 'action.created', payload: { action_type: 'respond' }, timestamp: '2026-07-23T10:00:01Z' },
];

const mockSummary = {
  run_id: 'test-run-1', status: 'active', run_type: 'chat',
  duration_seconds: 120, action_count: 2, failure_count: 0,
  teammates: ['tm-eng'], trigger_count: 1,
};

describe('OrganizationRunView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getRunStatus).mockResolvedValue(mockStatus);
    vi.mocked(api.getRunTimeline).mockResolvedValue(mockTimeline);
    vi.mocked(api.getRunSummary).mockResolvedValue(mockSummary);
  });

  // ── 1. Render test: shows prompt when no runId ──
  it('shows input prompt when no runId', async () => {
    const { default: OrganizationRunView } = await import('../pages/OrganizationRunView');
    render(<OrganizationRunView initialRunId="" />);
    expect(screen.getByText(/输入 Run ID/)).toBeTruthy();
  });

  // ── 2. API mock test: loads and displays status/timeline/summary ──
  it('loads and displays run data on mount', async () => {
    const { default: OrganizationRunView } = await import('../pages/OrganizationRunView');
    render(<OrganizationRunView initialRunId="test-run-1" />);

    await waitFor(() => {
      expect(screen.getByText('test-run-1')).toBeTruthy();
    });

    expect(screen.getByText('respond')).toBeTruthy();
    expect(screen.getByText('run.created')).toBeTruthy();
    expect(screen.getByText('tm-eng')).toBeTruthy();
  });

  // ── 3. Control buttons call correct API ──
  it('calls pauseRun on pause button click', async () => {
    vi.mocked(api.pauseRun).mockResolvedValue({ id: 'test-run-1', status: 'paused' });
    const { default: OrganizationRunView } = await import('../pages/OrganizationRunView');
    render(<OrganizationRunView initialRunId="test-run-1" />);

    await waitFor(() => screen.getByText('暂停'));
    await userEvent.click(screen.getByText('暂停'));

    expect(api.pauseRun).toHaveBeenCalledWith('test-run-1');
  });
});
