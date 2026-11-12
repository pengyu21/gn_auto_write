"""OpenVPN 다시 연결 (2026-11-12 요청).

폰보드는 OpenVPN for Android(de.blinkt.openvpn)로 인터넷에 나감. VPN 이 붙어 있는데 통신이 안 되는 일이 잦아
(82·84번 등) 사람이 앱을 열어 연결된 프로필을 누르고 '다시 연결' 을 누르면 바로 살아남 (11/12 82번: 5초).
그 동작을 그대로 함:

    앱 열기 → 'Connected…' 인 프로필 줄을 누름 → 창의 '다시 연결'(button3)
           → 연결된 프로필이 없으면 그 폰 번호 프로필(예: '82_1')을 눌러 연결
    → 최대 30초 동안 인터넷이 돌아오는지 확인 → 홈 버튼

ensure_online() 이 작업·점검 앞에서 부름: 인터넷이 없을 때만 다시 연결해 보고, 그래도 안 되는 폰만 돌려줌.
"""
from __future__ import annotations

import re
import time

from . import screen

PKG = "de.blinkt.openvpn"
MAIN = f"{PKG}/.activities.MainActivity"
RECONNECT = ("다시 연결", "Reconnect", "RECONNECT")
CONNECTED = ("Connected", "연결됨")


def _rows(xml):
    """[(제목, 부제목 노드)] — 프로필 목록."""
    nodes = list(screen.nodes(xml or ""))
    out, title = [], None
    for n in nodes:
        rid = n.get("resource-id", "")
        if rid.endswith("vpn_item_title"):
            title = n
        elif rid.endswith("vpn_item_subtitle"):
            out.append((title.get("text", "") if title is not None else "", n))
            title = None
    if title is not None:
        out.append((title.get("text", ""), title))
    return out


def reconnect(board, dev, log=print, wait: float = 30.0) -> str:
    """dev 의 OpenVPN 을 다시 연결. 'ok' / 'fail: 이유'."""
    from unni import login                       # 인터넷 확인 (순환 import 피하려고 여기서)
    devs = [dev]
    board.shell(f"am start -n {MAIN}", devs)
    time.sleep(3.5)
    xml = screen.dump(board, devs).get(dev.no) or ""
    if PKG not in xml:
        return "fail: OpenVPN 앱이 안 뜸"
    rows = _rows(xml)
    target = next((n for _t, n in rows if n.get("text", "").startswith(CONNECTED)), None)
    how = "연결된 프로필 '다시 연결'"
    if target is None:                              # 연결된 게 없으면 이 폰 번호 프로필로 연결
        target = next((n for t, n in rows if re.match(rf"{dev.no}(\D|$)", t or "")), None)
        how = "이 폰 프로필 연결"
    if target is None:
        board.key(3, devs)
        return f"fail: OpenVPN 에 연결된 프로필도 {dev.no}번 프로필도 없음"
    pt = screen.centre(target)
    board.tap([(dev, 400, pt[1])])                  # 줄의 왼쪽(편집 연필 말고)
    time.sleep(2.5)
    xml = screen.dump(board, devs).get(dev.no) or ""
    btn = next((screen.find(xml, text=t) for t in RECONNECT if screen.find(xml, text=t)), None)
    if btn is not None:
        board.tap([(dev, *screen.centre(btn))])
    elif how.startswith("연결된"):
        board.key(3, devs)
        return "fail: '다시 연결' 창이 안 뜸"
    log(f"  {dev.no}: OpenVPN {how}")
    t0 = time.time()
    ok = False
    while time.time() - t0 < wait:
        time.sleep(4)
        if not login.offline(board, devs):
            ok = True
            break
    board.key(3, devs)                              # 홈으로 (다음 단계가 자기 앱을 띄움)
    if ok:
        log(f"  {dev.no}: VPN 다시 연결 → 인터넷 됨 ({time.time() - t0:.0f}초)")
        return "ok"
    return f"fail: VPN 다시 연결했지만 {wait:.0f}초 안에 인터넷이 안 돌아옴"


def ensure_online(board, devs, log=print, fixed: list | None = None) -> list:
    """인터넷이 안 되는 폰만 OpenVPN 다시 연결을 해 보고, 그래도 안 되는 폰 목록을 돌려줌.
    (Wi-Fi 자체가 끊긴 경우·비행기 모드 등은 VPN 으로 안 되니 그대로 돌려줌)
    fixed 를 주면 다시 연결해서 살아난 폰을 거기에 담음 — 그 폰의 앱은 끊기기 전 연결을 붙잡고 있어
    '통신에 실패했습니다' 가 나므로 앱을 껐다 켜야 함 (2026-11-12 84번 바비톡)."""
    from unni import login
    dead = login.offline(board, devs)
    still = []
    for d in dead:
        why = login.net_reason(board, d)
        if "비행기" in why or why.startswith("Wi-Fi 연결 안 됨"):      # VPN 으로는 못 고침
            still.append(d)
            continue
        log(f"  {d.no}: 인터넷 안 됨 ({why}) — OpenVPN 다시 연결 시도")
        try:
            r = reconnect(board, d, log=log)
        except Exception as exc:                    # noqa: BLE001
            r = f"fail: {exc}"
        if r != "ok":
            log(f"  {d.no}: {r[5:].strip()}")
            still.append(d)
        elif fixed is not None:
            fixed.append(d)
    return still
