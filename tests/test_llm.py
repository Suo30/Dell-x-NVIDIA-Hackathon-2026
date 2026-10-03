import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import _config
import _llm

BAD = "Sure! Here is the data you asked for."


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('<think>reasoning with {braces}</think>{"a":1}', {"a": 1}),
    ('Here you go: {"a": 1} hope that helps', {"a": 1}),
    ('{"a":{"b":2}}', {"a": {"b": 2}}),
])
def test_extract_ok(text, expected):
    assert _llm._extract(text) == expected


@pytest.mark.parametrize("text", ["[1, 2]", "", "{bad"])
def test_extract_raises(text):
    with pytest.raises(ValueError):
        _llm._extract(text)


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"replies": [], "requests": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            state["requests"].append(json.loads(self.rfile.read(n)))
            status, content, finish = state["replies"].pop(0)
            payload = json.dumps(
                {"choices": [{"message": {"content": content}, "finish_reason": finish}]}
            ).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(_config, "LLM_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setattr(_config, "MOCK", False)
    yield state
    srv.shutdown()
    srv.server_close()


def _call():
    return _llm.chat_json("sys", "user", mock={"mock": True})


def test_good_reply(fake_llm):
    fake_llm["replies"] = [(200, '{"a":1}', "stop")]
    assert _call() == {"a": 1}
    assert len(fake_llm["requests"]) == 1
    body = fake_llm["requests"][0]
    assert body["model"] == _config.LLM_MODEL
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_retry_then_good(fake_llm):
    fake_llm["replies"] = [(200, BAD, "stop"), (200, '{"a":1}', "stop")]
    assert _call() == {"a": 1}
    assert len(fake_llm["requests"]) == 2
    msgs = fake_llm["requests"][1]["messages"]
    assert msgs[-2] == {"role": "assistant", "content": BAD}
    assert "valid JSON" in msgs[-1]["content"]


def test_bad_twice(fake_llm):
    fake_llm["replies"] = [(200, BAD, "stop"), (200, BAD, "stop")]
    out = _call()
    assert "invalid JSON after retry" in out["error"]
    assert len(fake_llm["requests"]) == 2


def test_http_500(fake_llm):
    fake_llm["replies"] = [(500, "boom", "stop")]
    out = _call()
    assert "unreachable" in out["error"]


def test_truncated_no_retry(fake_llm):
    fake_llm["replies"] = [(200, '{"a":', "length")]
    out = _call()
    assert "max_tokens" in out["error"]
    assert len(fake_llm["requests"]) == 1


def test_closed_port(monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(_config, "LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setattr(_config, "MOCK", False)
    out = _call()
    assert "unreachable" in out["error"]


def test_mock_is_copied(mock_llm):
    mock = {"skills": [{"skill_id": "python"}]}
    out = _llm.chat_json("s", "u", mock=mock)
    out["skills"].append("x")
    assert mock == {"skills": [{"skill_id": "python"}]}
