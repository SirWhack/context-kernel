"""Tests for the structured logging module. See S8 spec."""

import json
import logging

from context_kernel.logging import _HumanFormatter, _JsonFormatter, configure, invocation_id


class TestConfigure:
    def test_default_human_format(self):
        configure()
        root = logging.getLogger("context_kernel")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, _HumanFormatter)
        assert root.level == logging.INFO

    def test_json_format(self):
        configure(log_format="json")
        root = logging.getLogger("context_kernel")
        assert isinstance(root.handlers[0].formatter, _JsonFormatter)

    def test_log_level_debug(self):
        configure(log_level="DEBUG")
        root = logging.getLogger("context_kernel")
        assert root.level == logging.DEBUG

    def test_log_level_warning(self):
        configure(log_level="WARNING")
        root = logging.getLogger("context_kernel")
        assert root.level == logging.WARNING

    def test_reconfigure_replaces_handlers(self):
        configure()
        configure(log_format="json")
        root = logging.getLogger("context_kernel")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, _JsonFormatter)

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("CK_LOG_FORMAT", "json")
        monkeypatch.setenv("CK_LOG_LEVEL", "DEBUG")
        configure()
        root = logging.getLogger("context_kernel")
        assert isinstance(root.handlers[0].formatter, _JsonFormatter)
        assert root.level == logging.DEBUG


class TestJsonFormatter:
    def test_basic_fields(self):
        configure(log_format="json")
        invocation_id.set("test-uuid-1234")
        logger = logging.getLogger("context_kernel.test_module")
        handler = logging.getLogger("context_kernel").handlers[0]
        record = logger.makeRecord(
            "context_kernel.test_module", logging.INFO, "", 0, "test message", (), None,
        )
        output = handler.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["invocation"] == "test-uuid-1234"
        assert parsed["module"] == "context_kernel.test_module"
        assert parsed["msg"] == "test message"
        assert "ts" in parsed
        invocation_id.set(None)

    def test_extra_fields(self):
        configure(log_format="json")
        logger = logging.getLogger("context_kernel.test_extra")
        handler = logging.getLogger("context_kernel").handlers[0]
        record = logger.makeRecord(
            "context_kernel.test_extra", logging.INFO, "", 0, "materialized", (), None,
        )
        record.scope = "src/auth"
        record.graph_commit = "abc12345"
        record.duration_ms = 42
        record.files_written = 2
        output = handler.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["scope"] == "src/auth"
        assert parsed["graph_commit"] == "abc12345"
        assert parsed["duration_ms"] == 42
        assert parsed["files_written"] == 2

    def test_null_invocation(self):
        configure(log_format="json")
        invocation_id.set(None)
        logger = logging.getLogger("context_kernel.test_null")
        handler = logging.getLogger("context_kernel").handlers[0]
        record = logger.makeRecord(
            "context_kernel.test_null", logging.INFO, "", 0, "msg", (), None,
        )
        output = handler.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["invocation"] is None


class TestHumanFormatter:
    def test_basic_output(self):
        configure(log_format="human")
        invocation_id.set("abcdef12-3456-7890-abcd-ef1234567890")
        logger = logging.getLogger("context_kernel.test_human")
        handler = logging.getLogger("context_kernel").handlers[0]
        record = logger.makeRecord(
            "context_kernel.test_human", logging.INFO, "", 0, "freshness hit", (), None,
        )
        record.scope = "src/auth"
        output = handler.formatter.format(record)
        assert "[INFO]" in output
        assert "test_human:" in output
        assert "freshness hit" in output
        assert "scope=src/auth" in output
        assert "invocation=abcdef12" in output
        invocation_id.set(None)

    def test_no_invocation(self):
        configure(log_format="human")
        invocation_id.set(None)
        logger = logging.getLogger("context_kernel.test_no_inv")
        handler = logging.getLogger("context_kernel").handlers[0]
        record = logger.makeRecord(
            "context_kernel.test_no_inv", logging.INFO, "", 0, "test", (), None,
        )
        output = handler.formatter.format(record)
        assert "invocation=" not in output


class TestContextVar:
    def test_default_is_none(self):
        token = invocation_id.set("temp")
        invocation_id.reset(token)
        assert invocation_id.get() is None

    def test_set_and_get(self):
        invocation_id.set("my-uuid")
        assert invocation_id.get() == "my-uuid"
        invocation_id.set(None)
