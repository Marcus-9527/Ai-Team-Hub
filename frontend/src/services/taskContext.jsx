/**
 * taskContext.jsx — React Context for Task State
 *
 * Provides:
 *   tasks, selectedTaskId, selectTask, refreshTasks,
 *   polling status, loading/error states
 *
 * Auto-polling when provider is mounted.
 * Subscribes to taskEventBus for real-time updates.
 */
import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import * as taskApi from './api/task';
import { subscribeTaskEvents, isTaskEventType } from './taskEventBus';

const TaskContext = createContext(null);

const POLL_INTERVAL = 10_000; // 10s

export function TaskProvider({ children }) {
  const [tasks, setTasks] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [activeFilter, setActiveFilter] = useState('');
  const pollingRef = useRef(null);

  // ── Fetch tasks ──
  const refreshTasks = useCallback(async (filter = activeFilter) => {
    try {
      setLoading(true);
      setError(null);
      const params = {};
      if (filter) params.status = filter;
      const data = await taskApi.listTasks(params);
      setTasks(data.tasks || []);
      setTotal(data.total || 0);
    } catch (e) {
      setError(e.message);
      console.error('[TaskContext] refresh failed:', e);
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  // ── Filter change ──
  const setFilter = useCallback((filter) => {
    setActiveFilter(filter);
    refreshTasks(filter);
  }, [refreshTasks]);

  // ── Select / deselect ──
  const selectTask = useCallback((id) => {
    setSelectedTaskId(id);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedTaskId(null);
  }, []);

  // ── Initial load + polling ──
  useEffect(() => {
    refreshTasks();
    pollingRef.current = setInterval(() => {
      refreshTasks();
    }, POLL_INTERVAL);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Real-time SSE events — refresh on any task event ──
  useEffect(() => {
    const unsub = subscribeTaskEvents((event) => {
      const { type, task_id } = event || {};
      if (isTaskEventType(type) && task_id) {
        // refresh the task list and update the selected task if it matches
        refreshTasks();
      }
    });
    return unsub;
  }, [refreshTasks]);

  const value = {
    tasks,
    total,
    loading,
    error,
    selectedTaskId,
    activeFilter,
    refreshTasks: () => refreshTasks(),
    setFilter,
    selectTask,
    clearSelection,
  };

  return (
    <TaskContext.Provider value={value}>
      {children}
    </TaskContext.Provider>
  );
}

export function useTaskContext() {
  const ctx = useContext(TaskContext);
  if (!ctx) throw new Error('useTaskContext must be used within TaskProvider');
  return ctx;
}
