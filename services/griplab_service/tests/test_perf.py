import json

from griplab_service import perf


def test_perf_writes_configured_trace_file(monkeypatch, tmp_path) -> None:
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("GRIPLAB_TRACE_FILE", str(trace_file))
    monkeypatch.delenv("GRIPLAB_TRACE", raising=False)

    perf.clear()
    perf.record("unit.test", 1.234, ok=True, label="demo")

    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "perf"
    assert event["name"] == "unit.test"
    assert event["ok"] is True
    assert event["label"] == "demo"
    assert isinstance(event["pid"], int)
    assert perf.payload(1)["traceFile"] == str(trace_file)


def test_perf_trace_defaults_to_scratch_when_stderr_trace_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRIPLAB_TRACE", "1")
    monkeypatch.delenv("GRIPLAB_TRACE_FILE", raising=False)

    perf.clear()
    perf.record("unit.default", 2.0)

    trace_file = tmp_path / "scratch" / "griplab-perf.jsonl"
    event = json.loads(trace_file.read_text(encoding="utf-8").splitlines()[0])
    assert event["event"] == "perf"
    assert event["name"] == "unit.default"
    assert perf.payload(1)["traceFile"] == perf.DEFAULT_TRACE_FILE
