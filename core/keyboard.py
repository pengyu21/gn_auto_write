"""ADB 키보드로 입력합니다.

`input text` 는 한글을 못 보내고 특수문자마다 이스케이프가 필요합니다. ADB
키보드(com.android.adbkeyboard)에 base64 로 보내면 둘 다 해결되고, 화면
키보드가 안 떠서 페이지가 줄어들지도 않습니다. (삼성 HoneyBoard 기기
64·83·85·99 는 키보드 + '저장된 비밀번호' 바 때문에 비밀번호 칸 높이가
0 이 된 적이 있습니다.)

쓰기 전 키보드는 ime_backup.json 에 적어 두고 끝나면 되돌립니다. 도중에
죽어도 `python unni_login.py --restore-ime` 로 되돌릴 수 있습니다.

    with keyboard.adb_ime(board, devs) as on:      # on = 전환된 기기
        keyboard.type_text(board, devs, lambda d: "안녕하세요", on)
"""
from __future__ import annotations

import base64
import contextlib
import json
import threading
import time

from .board import ROOT, Board

ADB_IME = "com.android.adbkeyboard/.AdbIME"
BACKUP = ROOT / "ime_backup.json"           # 기기별 원래 키보드 (비밀 정보 없음)
_SHELL_SPECIAL = "\\()<>|;&*~\"'`$"
# 자동 실행은 여러 폰을 동시에 돌립니다. 백업 파일을 동시에 읽고 쓰면 한쪽 기록이
# 사라지므로 파일 갱신은 한 번에 하나씩.
_FILE_LOCK = threading.Lock()


def current(board: Board, devs) -> dict[int, str]:
    return {r.dev.no: r.stdout.strip() for r in board.shell(
        "settings get secure default_input_method", devs, timeout=40)}


def _backup() -> dict:
    try:
        return json.loads(BACKUP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def switch_on(board: Board, devs) -> set:
    """ADB 키보드로 전환. 전환된 기기 번호 집합."""
    if not devs:
        return set()
    now = current(board, devs)
    with _FILE_LOCK:
        saved = _backup()
        for no, ime in now.items():
            if ime and ADB_IME not in ime:
                saved[f"#{no}"] = ime
        BACKUP.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    board.shell(f"ime enable {ADB_IME}; ime set {ADB_IME}", devs, timeout=40)
    time.sleep(1.5)
    on = {no for no, ime in current(board, devs).items() if ADB_IME in ime}
    off = sorted(d.no for d in devs if d.no not in on)
    if off:
        print(f"  !! ADB 키보드 전환 실패 -> 기본 입력 사용: {off}")
    return on


def restore(board: Board, devs):
    """ime_backup.json 의 원래 키보드로 되돌립니다."""
    saved = _backup()
    targets = [d for d in devs if saved.get(f"#{d.no}")]
    if not targets:
        return
    board.run(targets, lambda d: ["shell", "ime", "set", saved[f"#{d.no}"]], timeout=30)
    time.sleep(1.0)
    left = sorted(no for no, ime in current(board, targets).items() if ADB_IME in ime)
    print(f"  !! 아직 ADB 키보드인 기기: {left}" if left else "  키보드 원래대로 복구")


@contextlib.contextmanager
def adb_ime(board: Board, devs):
    on = switch_on(board, devs)
    try:
        yield on
    finally:
        restore(board, devs)


def clear(board: Board, devs, on=frozenset()):
    """포커스된 칸 비우기. ADB 키보드면 ADB_CLEAR_TEXT, 아니면 END 후 DEL 반복."""
    adb = [d for d in devs if d.no in on]
    other = [d for d in devs if d.no not in on]
    if adb:
        board.shell("am broadcast -a ADB_CLEAR_TEXT", adb, timeout=40)
    if other:
        board.shell("input keyevent 123 " + " ".join(["67"] * 45), other, timeout=40)


def type_text(board: Board, devs, value_for, on=frozenset()):
    """포커스된 칸에 입력. value_for(기기) -> 글자. 줄바꿈도 그대로 들어갑니다."""
    adb = [d for d in devs if d.no in on]
    other = [d for d in devs if d.no not in on]
    if adb:
        board.run(adb, lambda d: ["shell", "am broadcast -a ADB_INPUT_B64 --es msg "
                                  + base64.b64encode(value_for(d).encode()).decode()])
    if other:
        # 기본 키보드로는 영문·숫자만 됩니다.
        board.run(other, lambda d: ["shell", "input", "text", _escape(value_for(d))])


def hide(board: Board, devs):
    """키보드가 실제로 떠 있는 기기에서만 BACK. 없는데 보내면 이전 페이지로 갑니다."""
    up = [r.dev for r in board.shell("dumpsys input_method | grep -m1 mIsInputViewShown",
                                     devs, timeout=40)
          if "mIsInputViewShown=true" in r.stdout]
    if up:
        board.key(4, up)
        time.sleep(1.5)


def _escape(text: str) -> str:
    for ch in _SHELL_SPECIAL:
        text = text.replace(ch, "\\" + ch)
    return text.replace(" ", "%s")
