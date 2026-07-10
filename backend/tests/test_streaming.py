"""
test_streaming.py — SSE Streaming Pipeline Tests

Covers:
  1. SSE event emission format
  2. Stream chunk accumulation
  3. Event type routing
"""
import pytest
import json
from datetime import datetime, timezone


class TestSSEEventFormat:
    """SSE event format validation."""

    def test_emit_event_format(self):
        """emit_event should produce valid data: JSON\\n\\n format."""
        from backend.services.team_collaboration import emit_event

        result = emit_event(
            event_type="teammate_message",
            message_id="msg_001",
            role="engineer",
            phase="round_1",
            payload={"content": "Hello", "teammate_id": "tm_123"},
            channel_id="ch_001",
        )

        assert result.startswith("data: ")
        assert result.endswith("\n\n")

        # Parse the JSON part
        json_str = result[5:].strip()
        event = json.loads(json_str)
        assert event["type"] == "teammate_message"
        assert event["message_id"] == "msg_001"
        assert event["role"] == "engineer"
        assert event["phase"] == "round_1"
        assert event["payload"]["content"] == "Hello"
        assert event["payload"]["teammate_id"] == "tm_123"
        assert "timestamp" in event

    def test_event_has_channel_id(self):
        """Event should include channel_id."""
        from backend.services.team_collaboration import emit_event

        result = emit_event(
            event_type="system_message",
            message_id="sys_001",
            payload={"content": "System notice"},
            channel_id="ch_042",
        )
        event = json.loads(result[5:].strip())
        assert event["channel_id"] == "ch_042"

    def test_multiple_event_types(self):
        """Different event types should all produce valid SSE."""
        from backend.services.team_collaboration import emit_event

        for evt_type in ("teammate_message", "teammate_end", "system_message", "error"):
            result = emit_event(
                event_type=evt_type,
                message_id=f"msg_{evt_type}",
                payload={"content": f"Test {evt_type}"},
            )
            assert result.startswith("data: ")
            parsed = json.loads(result[5:].strip())
            assert parsed["type"] == evt_type


class TestStreamParsing:
    """Frontend SSE parser behavior."""

    def test_parse_sse_line_valid(self):
        """parseSSELine should extract valid JSON."""
        # Simulate the frontend parseSSELine logic
        def parse_sse_line(line):
            if not line or not line.startswith("data:"):
                return None
            json_str = line[5:].strip()
            if not json_str or json_str == "[DONE]":
                return None
            try:
                return json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                return None

        valid_line = 'data: {"type":"teammate_message","message_id":"m1","payload":{"content":"hi"}}'
        result = parse_sse_line(valid_line)
        assert result is not None
        assert result["type"] == "teammate_message"

        invalid_line = "data: not-json"
        assert parse_sse_line(invalid_line) is None

        done_line = "data: [DONE]"
        assert parse_sse_line(done_line) is None

        non_data_line = "random text"
        assert parse_sse_line(non_data_line) is None

    def test_parse_sse_buffer(self):
        """parseSSEBuffer should extract all events from a buffer."""
        # Simulate the frontend parseSSEBuffer logic
        def parse_sse_buffer(buffer):
            events = []
            for line in buffer.split("\n"):
                if not line or not line.startswith("data:"):
                    continue
                json_str = line[5:].strip()
                if not json_str or json_str == "[DONE]":
                    continue
                try:
                    events.append(json.loads(json_str))
                except (json.JSONDecodeError, ValueError):
                    continue
            return events

        buffer = (
            'data: {"type":"teammate_message","message_id":"m1","payload":{"content":"a"}}\n'
            'data: {"type":"teammate_message","message_id":"m1","payload":{"content":"b"}}\n'
            "data: [DONE]\n"
        )
        events = parse_sse_buffer(buffer)
        assert len(events) == 2
        assert events[0]["message_id"] == "m1"
        assert events[1]["payload"]["content"] == "b"
