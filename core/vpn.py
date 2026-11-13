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
        record_drop(d.no, log=log)
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


# -- VPN 끊김 기록 · 'VPN 점검 필요' (2026-11-12 요청) -------------------------------------------
# 인터넷이 VPN 때문에 끊긴 걸 볼 때마다 폰별로 시각을 남김(같은 작업의 재시도처럼 20분 안에 또 보면 한 번으로).
# 최근 FLAG_DAYS 일 안에 FLAG_COUNT 번 이상이면 'VPN 점검 필요' — 폰보드 칸·문제 폰 목록에 표시, 처음 되면 하루 한 번 알림.
import json as _json
import threading as _threading
from datetime import datetime as _dt, timedelta as _td

from .board import ROOT as _ROOT

LOG = _ROOT / "vpn_drops.json"      # {"drops": {폰: ["YYYY-MM-DD HH:MM", …]}, "alerted": {폰: "YYYY-MM-DD"}}
FLAG_DAYS = 3
FLAG_COUNT = 3
SHOW_HOURS = 24        # 대시보드 표시는 마지막 끊김이 이 시간 안일 때만 (이미 정상인 폰에 며칠씩 떠 있지 않게, 2026-11-13)
SAME_EVENT_MIN = 20                  # 같은 작업의 재시도(5분 간격 3번 ≈ 11분)는 한 번으로
_LOGLOCK = _threading.Lock()


def _read() -> dict:
    try:
        return _json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _recent(times, now=None):
    now = now or _dt.now()
    out = []
    for t in times:
        try:
            if now - _dt.strptime(t, "%Y-%m-%d %H:%M") <= _td(days=FLAG_DAYS):
                out.append(t)
        except ValueError:
            pass
    return out


def record_drop(no: int, log=print):
    """폰 no 의 VPN 끊김을 한 번 기록. 기준을 처음 넘으면 텔레그램·메일 (폰마다 하루 한 번)."""
    now = _dt.now()
    with _LOGLOCK:
        d = _read()
        drops = d.setdefault("drops", {})
        times = _recent(drops.get(str(no), []), now)
        seen = d.setdefault("seen", {})
        last = seen.get(str(no))
        seen[str(no)] = now.strftime("%Y-%m-%d %H:%M")
        if last and now - _dt.strptime(last, "%Y-%m-%d %H:%M") < _td(minutes=SAME_EVENT_MIN):
            try:                                     # 같은 끊김(재시도 등) — 한 번으로. 마지막으로 '본' 시각만 갱신
                LOG.write_text(_json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass
            return
        times.append(now.strftime("%Y-%m-%d %H:%M"))
        drops[str(no)] = times
        alert = len(times) >= FLAG_COUNT and d.setdefault("alerted", {}).get(str(no)) != now.strftime("%Y-%m-%d")
        if alert:
            d["alerted"][str(no)] = now.strftime("%Y-%m-%d")
        try:
            LOG.write_text(_json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    if alert:
        log(f"!! {no}번 VPN 점검 필요 — 최근 {FLAG_DAYS}일 {len(times)}번 끊김")
        try:
            from unni import notify
            notify.both_async(f"📶 VPN 점검 필요 — {no}번",
                              f"{no}번 폰의 VPN 이 최근 {FLAG_DAYS}일 동안 {len(times)}번 끊겼습니다 ({', '.join(t[5:] for t in times[-5:])}).\n"
                              f"프로그램이 OpenVPN '다시 연결' 로 이어 가고 있지만, 자주 끊기면 그 폰의 VPN 프로필·서버를 점검해 주세요.")
        except Exception:                            # noqa: BLE001
            pass


def flagged() -> dict[int, dict]:
    """{폰: {'count': 최근 끊김 수, 'last': 'MM-DD HH:MM', 'why': 설명}} — 'VPN 점검 필요' 인 폰만.
    최근 FLAG_DAYS 일 FLAG_COUNT 번 이상 끊겼고, 마지막 끊김이 SHOW_HOURS 시간 안일 때."""
    out = {}
    now = _dt.now()
    for no, times in _read().get("drops", {}).items():
        t = _recent(times, now)
        if len(t) >= FLAG_COUNT and now - _dt.strptime(t[-1], "%Y-%m-%d %H:%M") <= _td(hours=SHOW_HOURS):
            out[int(no)] = {"count": len(t), "last": t[-1][5:],
                            "why": f"VPN 점검 필요 — 최근 {FLAG_DAYS}일 {len(t)}번 끊김 (마지막 {t[-1][5:]})"}
    return out
