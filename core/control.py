"""대시보드 일시중단 / 정지 (2026-11-12 요청) — 강남언니·바비톡 같이.

    일시중단  새 작업을 시작하지 않음(미리 로그인·닉네임·버전 확인도 쉼). 돌고 있는 작업은 끝까지.
    정지      일시중단 + 돌고 있는 작업도 다음 단계로 넘어가기 전에 멈춤 + 5분 뒤 재시도 취소.
    다시 시작 둘 다 풂.

일시중단 상태는 pause.json 에 남겨 대시보드를 다시 켜도 그대로. 정지 신호는 메모리에만 (다시 켜면 이미 멈춘 것).
작업 코드는 단계 사이에서 check() 를 불러, 정지면 Stopped 를 던져 그 작업을 '실패: 정지됨' 으로 끝냄.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

from .board import ROOT

STATE = ROOT / "pause.json"
_STOP = threading.Event()
_LOCK = threading.Lock()


class Stopped(Exception):
    """대시보드에서 '정지' 를 눌러 멈춘 작업."""

    def __init__(self, where: str = ""):
        super().__init__("정지됨 — 대시보드에서 정지" + (f" ({where} 전)" if where else ""))


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    try:
        STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def status() -> dict:
    """{'paused': bool, 'since': 'YYYY-MM-DD HH:MM', 'stopped': bool}"""
    d = _load()
    return {"paused": bool(d.get("paused")), "since": d.get("since", ""), "stopped": _STOP.is_set()}


def paused() -> bool:
    return bool(_load().get("paused"))


def pause():
    with _LOCK:
        d = _load()
        if not d.get("paused"):
            d.update(paused=True, since=datetime.now().strftime("%Y-%m-%d %H:%M"))
            _save(d)


def stop():
    pause()
    _STOP.set()


def resume():
    with _LOCK:
        _save({"paused": False})
        _STOP.clear()


def stop_requested() -> bool:
    return _STOP.is_set()


def check(where: str = ""):
    """작업 단계 사이에서 부름 — 정지를 눌렀으면 Stopped."""
    if _STOP.is_set():
        raise Stopped(where)


def wait(seconds: float) -> bool:
    """seconds 동안 기다림. 중간에 정지를 누르면 바로 True (재시도 대기 취소용)."""
    return _STOP.wait(seconds)
