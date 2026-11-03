"""바비톡 앱 버전 지켜보기 (2026-11-03 요청).

폰마다 플레이스토어가 따로 업데이트해서 버전이 섞임(11/03: 7.0.35·7.0.36·7.0.37). 새 버전은 화면이 바뀔 수 있어
(7.0.37: 아래 탭 '전체 서비스'→'전체', 'MY 바비톡'→'마이') 처음 보이면 텔레그램·메일로 알려 미리 점검하게 함.
화면은 건드리지 않고 adb 로 설치 버전만 읽음. 기록은 app_versions.json (공개 저장소 제외).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

from core.board import ROOT, Board
from . import site

STATE = ROOT / "app_versions.json"     # {"known": [...], "phones": {폰: 버전}, "checked": "YYYY-MM-DD HH:MM"}


def _key(v: str):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v))


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_versions(nos=range(60, 100)) -> dict[int, str]:
    """{폰: 바비톡 버전} — 연결된 폰만."""
    b = Board()
    devs = b.select(list(nos))
    out = {}
    for d, r in zip(devs, b.shell(f"dumpsys package {site.PKG} | grep -m1 versionName", devs, timeout=40)):
        m = re.search(r"versionName=(\S+)", r.stdout or "")
        if m:
            out[d.no] = m.group(1)
    return out


def check(notify=None, log=print) -> list[str]:
    """버전을 읽어 기록. 처음 보는 버전이 있으면 알림(notify(title, body))하고 그 버전 목록을 돌려줌.
    기록이 처음이면(파일 없음) 지금 버전들을 '아는 버전' 으로만 적고 알리지 않음."""
    now = read_versions()
    if not now:
        return []
    st = load()
    first = "known" not in st
    known = set(st.get("known", []))
    by_ver = defaultdict(list)
    for no, v in sorted(now.items()):
        by_ver[v].append(no)
    new = sorted((v for v in by_ver if v not in known), key=_key)
    st.update(known=sorted(known | set(by_ver), key=_key), phones={str(k): v for k, v in now.items()},
              checked=datetime.now().strftime("%Y-%m-%d %H:%M"))
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = " · ".join(f"{v} {len(n)}대" for v, n in sorted(by_ver.items(), key=lambda kv: _key(kv[0]), reverse=True))
    if first or not new:
        log(f"바비톡 앱 버전 확인: {summary}")
        return []
    for v in new:
        nos = ", ".join(map(str, by_ver[v]))
        log(f"!! 바비톡 새 버전 {v} — {nos}번 (화면이 바뀌었을 수 있음, 미리 점검 필요)")
        if notify:
            notify(f"🆕 바비톡 새 버전 {v}",
                   f"처음 보인 폰: {nos}번\n지금 버전별: {summary}\n"
                   f"화면이 바뀌었을 수 있어요. 이 폰으로 로그인 점검(글쓰기까지)을 먼저 해 보세요.")
    return new
