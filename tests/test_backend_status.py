"""后端状态条的行为验证：不依赖真实后端，用 monkeypatch 替换 _session。"""
import sys, os
sys.path.insert(0, os.getcwd())

import pytest
import requests
import streamlit as st

from src.ui import backend_status


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        assert url.endswith("/api/health"), url
        assert timeout == backend_status.PROBE_TIMEOUT
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    st.session_state.pop("_backend_probe", None)
    yield
    st.session_state.pop("_backend_probe", None)


def test_probe_reports_ok_with_version(monkeypatch):
    monkeypatch.setattr(backend_status, "_session", _Session(_Resp(200, {"version": "0.4.2"})))
    probe = backend_status.probe_backend(force=True)
    assert probe["ok"] is True
    assert probe["status_code"] == 200
    assert probe["detail"] == "0.4.2"
    assert probe["latency_ms"] is not None and probe["latency_ms"] >= 0


def test_probe_connection_error_is_not_ok(monkeypatch):
    monkeypatch.setattr(
        backend_status, "_session", _Session(requests.ConnectionError("Max retries exceeded"))
    )
    probe = backend_status.probe_backend(force=True)
    assert probe["ok"] is False
    # 报错只留异常类型名：真实报错里含端口与 Errno，对用户没有信息量
    assert probe["detail"] == "ConnectionError"


def test_probe_non_200_is_not_ok(monkeypatch):
    monkeypatch.setattr(backend_status, "_session", _Session(_Resp(404, {})))
    probe = backend_status.probe_backend(force=True)
    assert probe["ok"] is False
    assert probe["status_code"] == 404


def test_probe_result_is_cached_within_ttl(monkeypatch):
    session = _Session(_Resp(200, {"version": "0.4.2"}))
    monkeypatch.setattr(backend_status, "_session", session)
    backend_status.probe_backend(force=True)
    backend_status.probe_backend()
    backend_status.probe_backend()
    # 10 秒内多次交互只打一次网络请求，否则侧栏每次点击都要等一次超时
    assert session.calls == 1


def test_probe_force_bypasses_cache(monkeypatch):
    session = _Session(_Resp(200, {"version": "0.4.2"}))
    monkeypatch.setattr(backend_status, "_session", session)
    backend_status.probe_backend(force=True)
    backend_status.probe_backend(force=True)
    assert session.calls == 2
