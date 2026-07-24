"""OrganizationEvent — Activity Feed audit (Phase 14)

Audit whether existing action.* events (created/started/completed/failed)
can support a real-time Activity Feed UI.

╔══════════════════════════════════════════════════════════════════════╗
║  AUDIT: action.created / action.started / action.completed /       ║
║         action.failed  →  Activity Feed readiness                   ║
╚══════════════════════════════════════════════════════════════════════╝

Current payload shape (from action_runtime.py + router.py):

  action.created   → {"run_id": str, "action_type": str}
  action.started   → {"run_id": str, "action_type": str}
  action.completed → {"run_id": str, "action_type": str}
  action.failed    → {"run_id": str, "action_type": str, "error": str}

Available for FREE from the SessionEvent model itself:
  - id               → unique event id
  - trigger_id       → links to the trigger (session/chat context)
  - turn_id          → links to the turn (specific AI action)
  - event_type       → "action.created" / "action.started" / etc
  - timestamp        → when it happened (auto-set by model default)

═══════════════════════════════════════════════════════════════════════
MISSING FIELDS (needed for a rich Activity Feed)

  1. teammate_id  — Which teammate performed this action?
     Without it, the feed can't show "Zhang San is coding…" — it can only
     show a bare action_type. Currently only action.decided carries
     suggested_roles (roles, not actual teammate id).

  2. summary / display_text — Human-readable one-liner.
     Frontend needs something like "Executing code in project X" or
     "Delegating task: Refactor auth". Currently only raw action_type.

  3. source_label — What triggered this action?
     e.g. "Chat message from user" vs "Task: Refactor auth".
     Helps group events by context in the feed.

  4. status_hint — For "created" events, a pending indicator.
     Currently the frontend must cross-reference started/completed/failed
     to figure out if an action is still running. An explicit field like
     status_hint="pending|running|success|failed" would make the feed
     reactive without join queries. Not needed if the feed frontend
     deduplicates by action_type+run_id.

═══════════════════════════════════════════════════════════════════════
RECOMMENDATION (no model change — enrich payload at emission site)

  Add to payload at emission (not schema change):
    teammate_id: str         — who (from calling context)
    summary: str             — display text (derived from action_type+context)
    source_label: str=""     — "chat" / "task: <title>"

  Where to inject:
    action_runtime._emit_created() → accept teammate_id, summary
    router._emit()                  → forward teammate_id, summary
    emit_action_event()             → accept teammate_id, summary

  These are payload-only additions. SessionEvent model unchanged.
══════════════════════════════════════════════════════════════════════╝
"""
