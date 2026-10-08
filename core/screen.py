"""화면 구조(uiautomator dump)로 누를 곳을 찾습니다.

좌표를 박아 두면 크롬 업데이트·해상도 차이(89번 1080x2280@420dpi)에 조용히
빗나갑니다. 구조에서 id / 글자 / content-desc 로 찾으면 그 기기 화면의 실제
위치가 나옵니다. 크롬은 웹 페이지 요소의 id 를 resource-id 로, aria-label 을
content-desc 로 내보내서 웹 안의 버튼도 이렇게 찾을 수 있습니다.

**찾지 못하면 누르지 않습니다.** 짐작해서 누르는 게 가장 위험합니다 —
예전에 픽셀로 찾던 코드가 로그아웃 대신 회원 탈퇴를 누른 적이 있습니다.
"""
from __future__ import annotations

import html
import re
import time
from typing import Optional

from .board import Board, Device

NODE = re.compile(r"<node\b[^>]*>")
ATTR = re.compile(r'(\S+?)="([^"]*)"')
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

DUMP_CMD = ("uiautomator dump /sdcard/pbui.xml >/dev/null 2>&1; "
            "cat /sdcard/pbui.xml; rm -f /sdcard/pbui.xml")


def dump(board: Board, devs, timeout: float = 60, tries: int = 2) -> dict[int, str]:
    """{폰보드 번호: xml}. 못 읽은 기기는 빠집니다.

    애니메이션 중에는 dump 가 빈손으로 끝나는 일이 잦아서(79번), 못 읽은
    기기만 잠깐 쉬었다가 한 번 더 읽습니다.
    """
    out: dict[int, str] = {}
    pending = list(devs)
    for i in range(tries):
        if not pending:
            break
        if i:
            time.sleep(1.5)
        for r in board.shell(DUMP_CMD, pending, timeout=timeout):
            if "<node" in r.stdout:
                out[r.dev.no] = r.stdout
        pending = [d for d in pending if d.no not in out]
    return out


def nodes(xml: Optional[str]):
    # 속성값은 XML 이스케이프 상태(줄바꿈 '&#10;', '&amp;' …)라 풀어서 돌려줍니다.
    # 안 풀면 여러 줄 글을 입력한 뒤 원본과 비교할 때 틀렸다고 나옵니다.
    for m in NODE.finditer(xml or ""):
        yield {k: html.unescape(v) for k, v in ATTR.findall(m.group(0))}


def rect(node) -> Optional[tuple[int, int, int, int]]:
    m = BOUNDS.search(node.get("bounds", ""))
    return tuple(int(v) for v in m.groups()) if m else None


def centre(node) -> Optional[tuple[int, int]]:
    """크기가 0 인 노드(화면 밖·접힌 것)는 None — 누를 수 없습니다."""
    r = rect(node) if node else None
    if not r or r[2] <= r[0] or r[3] <= r[1]:
        return None
    return ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)


def area(node) -> int:
    r = rect(node)
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1]) if r else 0


def find(xml: Optional[str], rid=None, text=None, desc=None, cls=None,
         clickable: Optional[bool] = None):
    """조건을 **전부 정확히** 만족하는 첫 노드(화면에 보이는 것만), 없으면 None.

    부분 일치는 일부러 두지 않았습니다. 'sign out' 을 찾다가
    'sign out later' 같은 게 걸리면 안 되는 화면이 있습니다.
    rid 는 문자열 또는 목록(버전마다 id 가 바뀌는 크롬용).
    """
    rids = [rid] if isinstance(rid, str) else (rid or [])
    for n in nodes(xml):
        if rids and n.get("resource-id") not in rids:
            continue
        if text is not None and n.get("text") != text:
            continue
        if desc is not None and n.get("content-desc") != desc:
            continue
        if cls is not None and n.get("class") != cls:
            continue
        if clickable is not None and n.get("clickable") != str(clickable).lower():
            continue
        if centre(n):
            return n
    return None


def point(xml, **what) -> Optional[tuple[int, int]]:
    n = find(xml, **what)
    return centre(n) if n else None


def url_of(xml) -> str:
    """크롬 주소창의 글자 (예: 'unni.app/community')."""
    n = find(xml, rid="com.android.chrome:id/url_bar")
    return n.get("text", "") if n else ""


def tap_found(board: Board, devs, label: str = "", screens=None, **what):
    """기기마다 찾아서 그 자리를 누릅니다. (누른 기기, 못 찾은 기기)."""
    screens = screens if screens is not None else dump(board, devs)
    points, miss = [], []
    for d in devs:
        pt = point(screens.get(d.no), **what)
        (points.append((d, *pt)) if pt else miss.append(d))
    if points:
        board.tap(points)
        if label:
            print(f"  {label}: {sorted(d.no for d, _x, _y in points)}")
    return [d for d, _x, _y in points], miss
