"""Unit tests for the standing drop-classifier (the denominator that prevents phantom chases)."""

from context_kernel.ingester.drop_diagnostics import (
    candidate_bare, classify_drops, format_report,
)
from context_kernel.ingester.entity_resolver import STOPLIST, normalize


def _classify(drops, *, names=None, ambiguous=None, files=None):
    return classify_drops(
        drops,
        code_name_count=names or {},
        ambiguous_bases=ambiguous or set(),
        file_paths=files or set(),
        stoplist=STOPLIST,
        normalize=normalize,
    )


def test_candidate_bare_strips_context_echo_and_path_symbol():
    assert candidate_bare("ToolDefinition (class, src/tools/models.py)") == "ToolDefinition"
    assert candidate_bare("src/tools/models.py:ToolDefinition") == "ToolDefinition"
    assert candidate_bare("src/bot/agent.py:407-432") == "src/bot/agent.py:407-432"  # line ref, not a symbol
    assert candidate_bare("plain_name") == "plain_name"


def test_ambiguous_and_stoplist_are_correct_drops():
    r = _classify([("main", "realizes"), ("validate", "governed-by")],
                  names={"validate": 3})            # validate defined 3× → ambiguous
    assert r.buckets.get("ambiguous") == 2
    assert r.recoverable_count == 0


def test_external_library_is_correct_drop():
    r = _classify([("asyncio.create_task", "realizes"), ("anthropic.messages.create", "motivates")])
    assert r.buckets.get("external") == 2


def test_directory_target_is_correct_drop():
    r = _classify([("src/tools/analysis", "governed-by")])
    assert r.buckets.get("directory") == 1


def test_prose_phrase_is_correct_drop():
    r = _classify([("the master agent loop coordinator", "realizes")])
    assert r.buckets.get("prose") == 1


def test_unique_real_name_is_recoverable():
    # A drop whose candidate uniquely names a real code entity is a genuine resolver gap.
    r = _classify([("ToolDefinition (class, src/tools/models.py)", "realizes")],
                  names={"ToolDefinition": 1})
    assert r.recoverable_count == 1
    assert r.recoverable[0]["candidate"] == "ToolDefinition"


def test_path_naming_real_file_is_recoverable():
    r = _classify([("src/bot/agent.py:1088", "realizes")], files={"src/bot/agent.py"})
    assert r.recoverable_count == 1


def test_no_referent_short_name_is_correct_drop():
    r = _classify([("WidgetThatNeverExisted", "realizes")])
    assert r.buckets.get("no_referent") == 1
    assert r.recoverable_count == 0


def test_format_report_renders_clean_when_no_recoverable():
    r = _classify([("main", "realizes")])
    out = format_report(r)
    assert "Relationship-drop diagnostics" in out
    assert "No recoverable drops" in out


def test_format_report_lists_recoverable():
    r = _classify([("src/tools/models.py:ToolDefinition", "realizes")], names={"ToolDefinition": 1})
    out = format_report(r)
    assert "Recoverable sample" in out and "ToolDefinition" in out
