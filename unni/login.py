"""강남언니 로그인 / 로그아웃 / 로그인 상태 — 폰보드 여러 대를 한 번에.

로그인 흐름 (기기 전부 병렬):
    1. 시트 '강언아이디' 에서 로테이션 N 의 (폰보드 번호 -> 아이디/비번)
    2. 인터넷 안 되는 기기 걸러내기
    3. 홈 열기 -> 팝업 닫기 -> '로그인/가입' (이미 로그인된 기기는 건너뜀)
    4. 편지(이메일) 아이콘
    5. 이메일·비밀번호 입력(ADB 키보드) -> 값이 정확히 들어갔고 버튼이 켜진 기기만 로그인
    6. 홈에서 로그인 확인, 실패한 기기만 한 번 더
    7. 크롬 탭 모두 닫기

누를 곳은 전부 화면 구조(id / 이름)로 찾고, 못 찾으면 누르지 않고 실패로
남깁니다. 비밀번호는 화면·로그·파일 어디에도 남기지 않고, 아이디도 앞 3글자만 찍습니다.

GUI 에서:
    stop = threading.Event()
    result = login.run("60-99", rotation=1, log=my_log_fn, stop=stop)
    # {60: "ok", 61: "skip: 이미 로그인됨", 62: "fail: ...", ...}
`log` 는 워커 스레드에서 불립니다. `stop.set()` 은 다음 단계 경계에서 멈춥니다.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from typing import Callable, Optional

from core import chrome, keyboard, screen
from core.board import ROOT, Board, parse_panels
from core.sheet import Sheet, SheetError
from . import site
from .popups import close_popups

NO_NET = "fail: 인터넷 연결 없음 (기기 네트워크 확인)"
WRONG_PW = "fail: 이메일/비밀번호 불일치 (시트 계정 확인 — 재시도 안 함)"
NO_SCREEN = "fail: 화면 구조를 못 읽음"


class Stopped(Exception):
    """GUI 에서 중지를 눌렀을 때."""


def mask(value: str) -> str:
    head, _, host = str(value).partition("@")
    return f"{head[:3]}***@{host}" if host else f"{head[:3]}***"


# -- 계정 ------------------------------------------------------------------------

def load_accounts(rotation: int, tries: int = 3) -> dict[int, dict]:
    """{폰보드 번호: {"id", "pw"}}. 웹앱이 가끔 오류 페이지를 줘서 몇 번 다시 시도합니다."""
    last = None
    for i in range(tries):
        try:
            res = Sheet().accounts(rotation)
            break
        except SheetError as exc:
            last = exc
            print(f"  시트 읽기 실패 ({i + 1}/{tries}) — 다시 시도")
            time.sleep(2.0 + i * 2)
    else:
        raise RuntimeError(f"시트를 읽지 못했습니다: {last}")
    if res.get("skipped"):
        print(f"  사용여부 FALSE/빈칸이라 건너뜀: {res['skipped']}")
    return {int(no): {"id": str(a["id"]).strip(), "pw": str(a["pw"])}
            for no, a in res["accounts"].items() if a.get("id") and a.get("pw")}


# -- 기기 점검 ---------------------------------------------------------------------

def offline(board, devs) -> list:
    """unni.app 에 닿지 않는 기기. unni.app 은 ping 에 답하지 않아 이름 풀이(DNS)만
    보고, 실제 연결은 8.8.8.8 로 봅니다. (79번이 DNS 실패로 홈조차 못 연 적 있음)"""
    return [r.dev for r in board.shell(
        "ping -c 1 -W 1 unni.app 2>&1 | grep -q 'PING unni.app (' "
        "&& ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1 && echo NET_OK", devs, timeout=30)
        if "NET_OK" not in r.stdout]


def has_page(xml) -> bool:
    """웹 내용까지 구조에 잡혔는가. 아니면 '없다' 는 판정을 내리면 안 됩니다."""
    return screen.find(xml, rid=site.PAGE) is not None


# -- 홈 화면 판독 ------------------------------------------------------------------

def read_home(board, devs, rounds: int = 4) -> dict[int, tuple]:
    """홈을 열어 로그인 여부를 읽습니다. {번호: (상태, 닉네임, xml)}.

    상태: True = 우측 상단 닉네임 / False = '로그인/가입' / None = 판독 불가.
    누르는 건 팝업 닫기뿐입니다.
    """
    board.key(224, devs)
    chrome.open_url(board, devs, site.HOME)
    time.sleep(5.0)
    out: dict[int, tuple] = {}
    pending = chrome.wait_front(board, devs)
    for d in devs:
        if d not in pending:
            out[d.no] = (None, "", None)
    for i in range(rounds):
        if not pending:
            break
        screens = close_popups(board, pending, quiet=True)
        still = []
        for d in pending:
            xml = screens.get(d.no)
            prof = screen.find(xml, rid=site.HOME_PROFILE)
            if prof:
                out[d.no] = (True, prof.get("text", ""), xml)
            elif screen.find(xml, rid=site.HOME_LOGIN):
                out[d.no] = (False, "", xml)
            elif i >= 1 and has_page(xml) and "unni.app" in screen.url_of(xml):
                # 웹 내용은 다 읽혔는데 로그인/가입이 없음 = 로그인 상태.
                # 첫 바퀴는 덜 그려졌을 수 있어 판정하지 않습니다.
                out[d.no] = (True, "", xml)
            else:
                still.append(d)
        pending = still
        if pending:
            time.sleep(1.5)
    for d in pending:
        out[d.no] = (None, "", None)
    return out


# -- 로그인 단계 -------------------------------------------------------------------

def step_home(board, devs, status):
    """홈에서 '로그인/가입' 을 누릅니다. (누른 기기, 이미 로그인된 기기)."""
    home = read_home(board, devs)
    taps, logged = [], []
    for d in devs:
        state, _nick, xml = home[d.no]
        if state is True:
            logged.append(d)
        elif state is False:
            taps.append((d, *screen.point(xml, rid=site.HOME_LOGIN)))
        else:
            status[d.no] = "fail: 홈 화면을 못 읽음"
    if logged:
        print(f"  이미 로그인됨: {sorted(d.no for d in logged)}")
    if taps:
        print(f"  로그인/가입 탭: {sorted(d.no for d, _x, _y in taps)}")
        board.tap(taps)
        time.sleep(3.0)
    return [d for d, _x, _y in taps], logged


def step_mail_icon(board, devs) -> list:
    """로그인 방식 선택에서 편지 아이콘. /signin/email 에 도착한 기기를 돌려줍니다."""
    arrived, pending = [], list(devs)
    for _ in range(4):
        if not pending:
            break
        screens = close_popups(board, pending, quiet=True)
        taps, still = [], []
        for d in pending:
            xml = screens.get(d.no)
            if "signin/email" in screen.url_of(xml):
                arrived.append(d)
                continue
            pt = screen.point(xml, rid=site.MAIL_ICON)
            if pt:
                taps.append((d, *pt))
            still.append(d)
        if taps:
            print(f"  편지 아이콘 탭: {sorted(d.no for d, _x, _y in taps)}")
            board.tap(taps)
            time.sleep(3.0)
        elif still:
            time.sleep(1.5)
        pending = still
    if pending:
        # 버튼으로 못 온 기기는 이메일 로그인 주소를 직접 엽니다.
        print(f"  이메일 로그인 화면 주소로 직접: {sorted(d.no for d in pending)}")
        chrome.open_url(board, pending, site.SIGNIN_EMAIL)
        time.sleep(5.0)
        screens = close_popups(board, pending, quiet=True)
        arrived += [d for d in pending if "signin/email" in screen.url_of(screens.get(d.no))]
    return arrived


def step_form(board, devs, accounts, status) -> list:
    """이메일/비밀번호 입력 후 로그인 탭. 탭한 기기를 돌려줍니다.

    매 동작 직전에 구조를 새로 읽어 그 순간의 칸 위치를 누릅니다. 입력 후에는
    이메일 칸의 값이 시트 아이디와 **정확히 같은지**, 버튼이 켜졌는지 확인합니다.
    """
    for d in devs:
        print(f"  {d.no}: {mask(accounts[d.no]['id'])}")
    uid = lambda d: accounts[d.no]["id"]          # noqa: E731
    pw = lambda d: accounts[d.no]["pw"]           # noqa: E731

    with keyboard.adb_ime(board, devs) as on:
        # 1) 이메일 칸
        screens = close_popups(board, devs, quiet=True)
        taps = []
        for d in devs:
            pt = screen.point(screens.get(d.no), rid=site.EMAIL)
            if pt:
                taps.append((d, *pt))
            else:
                status[d.no] = "fail: 이메일 칸을 못 찾음"
        ok = [d for d, _x, _y in taps]
        board.tap(taps)
        time.sleep(1.2)
        keyboard.clear(board, ok, on)
        keyboard.type_text(board, ok, uid, on)
        time.sleep(1.0)

        # 2) 이메일 확인 (한 번은 다시 입력해 봄)
        for attempt in range(2):
            screens = screen.dump(board, ok)
            bad = [d for d in ok
                   if (screen.find(screens.get(d.no), rid=site.EMAIL) or {}).get("text") != uid(d)]
            if not bad or attempt == 1:
                break
            print(f"  이메일 다시 입력: {sorted(d.no for d in bad)}")
            again = [(d, *screen.point(screens.get(d.no), rid=site.EMAIL)) for d in bad
                     if screen.point(screens.get(d.no), rid=site.EMAIL)]
            board.tap(again)
            time.sleep(1.0)
            keyboard.clear(board, [d for d, _x, _y in again], on)
            keyboard.type_text(board, [d for d, _x, _y in again], uid, on)
            time.sleep(1.0)
        for d in bad:
            status[d.no] = "fail: 이메일이 정확히 안 들어감"
        ok = [d for d in ok if d not in bad]

        # 3) 비밀번호 칸 — 키보드가 화면을 줄여 높이가 0 이면 키보드를 내리고 다시 읽음
        squeezed = [d for d in ok if not screen.point(screens.get(d.no), rid=site.PASSWORD)]
        if squeezed:
            keyboard.hide(board, squeezed)
            screens.update(screen.dump(board, squeezed))
        taps = []
        for d in ok:
            pt = screen.point(screens.get(d.no), rid=site.PASSWORD)
            if pt:
                taps.append((d, *pt))
            else:
                status[d.no] = "fail: 비밀번호 칸을 못 찾음"
        ok = [d for d, _x, _y in taps]
        board.tap(taps)
        time.sleep(1.0)
        keyboard.clear(board, ok, on)
        keyboard.type_text(board, ok, pw, on)
        time.sleep(1.2)
        keyboard.hide(board, ok)

        # 4) 확인 후 로그인 버튼
        screens = screen.dump(board, ok)
        taps = []
        for d in ok:
            xml = screens.get(d.no)
            email = screen.find(xml, rid=site.EMAIL)
            pwd = screen.find(xml, rid=site.PASSWORD)
            btn = screen.find(xml, rid=site.SUBMIT)
            if not (email and btn):
                status[d.no] = NO_SCREEN
            elif email.get("text") != uid(d):
                status[d.no] = "fail: 이메일 값 불일치"
            elif pwd is not None and pwd.get("text") and len(pwd.get("text")) != len(pw(d)):
                status[d.no] = "fail: 비밀번호 길이 불일치"
            elif btn.get("enabled") != "true":
                status[d.no] = "fail: 로그인 버튼 비활성 (입력 안 됨)"
            else:
                taps.append((d, *screen.centre(btn)))
        if taps:
            print(f"  로그인 탭: {sorted(d.no for d, _x, _y in taps)}")
            board.tap(taps)
    return [d for d, _x, _y in taps]


def step_verify(board, devs, status):
    """로그인 탭 후: '비밀번호 저장?' 닫기 -> 홈에서 로그인 여부."""
    time.sleep(6.0)
    screens = close_popups(board, devs)          # '비밀번호 저장' 말풍선도 '안함'
    stuck = [d for d in devs if "signin/email" in screen.url_of(screens.get(d.no))]
    for d in stuck:
        # '일치하지 않아요' 면 시트 계정 문제 — 재시도하면 잠금 위험만 커집니다.
        status[d.no] = (WRONG_PW if site.WRONG_PASSWORD_TEXT in (screens.get(d.no) or "")
                        else "fail: 로그인 화면에 머묾 (아이디/비번 확인 필요)")
    if stuck:
        print(f"  !! 로그인 후에도 로그인 화면: {sorted(d.no for d in stuck)}")
    rest = [d for d in devs if d not in stuck]
    if not rest:
        return
    for no, (state, nick, _xml) in read_home(board, rest).items():
        if state is True:
            status[no] = "ok"
            print(f"  {no}: 로그인됨" + (f" — {nick}" if nick else ""))
        elif state is False:
            status[no] = "fail: 로그인 안 됨 (홈에 로그인/가입 버튼)"
        else:
            status[no] = NO_SCREEN


# -- 로그아웃 ---------------------------------------------------------------------

def logout(board, devs, rounds: int = 5) -> dict[int, Optional[bool]]:
    """마이페이지 -> '계정 관리' -> '로그아웃'. {번호: 로그아웃됐는가}.

    두 버튼 모두 content-desc 가 **정확히** 일치할 때만 누릅니다. 바로 옆에
    '회원 탈퇴'(withdraw member)가 있고, 한 번 잘못 누르면 되돌릴 수 없습니다.
    """
    board.key(224, devs)
    chrome.open_url(board, devs, site.MYPAGE)
    time.sleep(3.0)
    pending = chrome.wait_front(board, devs)
    opened: set[int] = set()            # '계정 관리' 시트를 연 기기
    for _ in range(rounds):
        if not pending:
            break
        # 계정 관리 시트에도 '닫기' 버튼이 있어서, 시트를 연 뒤 팝업 닫기를 돌리면
        # 그 시트를 닫아 버립니다(2026-10-07 78번 로그아웃 실패 원인). 연 기기는 읽기만.
        screens = close_popups(board, [d for d in pending if d.no not in opened], quiet=True)
        screens.update(screen.dump(board, [d for d in pending if d.no in opened]))
        taps, reopen, still = [], [], []
        for d in pending:
            xml = screens.get(d.no)
            out_pt = screen.point(xml, desc=site.SIGN_OUT)
            menu_pt = screen.point(xml, desc=site.ACCOUNT_MENU)
            if out_pt:
                taps.append((d, *out_pt))              # 끝
            elif menu_pt:
                taps.append((d, *menu_pt))
                opened.add(d.no)
                still.append(d)
            elif xml and "mypage" not in screen.url_of(xml):
                reopen.append(d)                       # 이미 로그아웃이면 홈으로 튕김
                opened.discard(d.no)
                still.append(d)
            else:
                still.append(d)
        if taps:
            board.tap(taps)
        if reopen:
            chrome.open_url(board, reopen, site.MYPAGE)
        if taps or reopen:
            time.sleep(2.4)
        pending = still
    # 눌렀다고 로그아웃된 건 아닙니다. 홈에서 '로그인/가입' 이 보이는지로 확인합니다.
    home = read_home(board, devs)
    result = {no: (None if s is None else s is False) for no, (s, _n, _x) in home.items()}
    done = sorted(no for no, v in result.items() if v)
    bad = sorted(no for no, v in result.items() if not v)
    print(f"  로그아웃 완료: {done}")
    if bad:
        print(f"  !! 로그아웃 안 됨/판독 불가: {bad}")
    return result


# -- 빠른 계정 전환 (한 기기) -----------------------------------------------------------
# run() 은 40대를 한꺼번에 로그인시키는 용도라 홈 화면을 여러 번 읽으며 꼼꼼히
# 확인합니다(한 대에 4분 남짓). 글 작업은 한 대씩 계정만 바꾸면 되므로
# 마이페이지 한 번 -> (로그아웃) -> 이메일 로그인 주소로 바로 갑니다. 로그인 결과는
# 이어서 여는 커뮤니티 화면의 닉네임으로 확인합니다(post.write 1단계).

NICKS = ROOT / "account_nicks.json"          # 아이디 -> 닉네임 (비밀번호 없음)


def known_nicks() -> dict[str, str]:
    try:
        return json.loads(NICKS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember_nick(account_id: str, nick: str):
    if not (account_id and nick):
        return
    data = known_nicks()
    if data.get(account_id) != nick:
        data[account_id] = nick
        NICKS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def switch(board, dev, account: dict, log=print) -> str:
    """dev 를 account({"id","pw"}) 로 로그인. 'ok' / 'skip: 이미 이 계정' / 'fail: …'."""
    devs = [dev]
    board.key(224, devs)
    chrome.open_url(board, devs, site.MYPAGE)
    time.sleep(3.0)
    if not chrome.wait_front(board, devs, timeout=15):
        return "fail: 크롬이 앞에 없음"

    # 1. 지금 누구로 로그인돼 있나
    xml = None
    for _ in range(3):
        xml = close_popups(board, devs, quiet=True).get(dev.no)
        if screen.find(xml, rid=site.HOME_PROFILE) or screen.find(xml, rid=site.HOME_LOGIN):
            break
        time.sleep(1.5)
    prof = screen.find(xml, rid=site.HOME_PROFILE)
    now = prof.get("text", "") if prof else ""
    want = known_nicks().get(account["id"], "")
    if prof and want and now == want:
        log(f"  {dev.no}: 이미 {mask(account['id'])} ({now}) — 전환 생략")
        return "skip: 이미 이 계정"

    # 2. 다른 계정이면 로그아웃: 계정 관리 -> sign out (정확히 일치할 때만)
    if prof:
        log(f"  {dev.no}: 지금 {now} -> 로그아웃")
        menu = None
        for _ in range(3):
            menu = screen.point(xml, desc=site.ACCOUNT_MENU)
            if menu:
                break
            time.sleep(1.5)
            xml = screen.dump(board, devs).get(dev.no)
        if not menu:
            return "fail: 계정 관리 버튼을 못 찾음"
        board.tap([(dev, *menu)])
        out = None
        for _ in range(3):
            time.sleep(1.5)
            out = screen.point(screen.dump(board, devs).get(dev.no), desc=site.SIGN_OUT)
            if out:
                break
        if not out:
            return "fail: 로그아웃 버튼을 못 찾음"
        board.tap([(dev, *out)])
        time.sleep(2.5)
    elif not screen.find(xml, rid=site.HOME_LOGIN):
        return "fail: 마이페이지를 못 읽음"

    # 3. 이메일 로그인 화면으로 바로
    chrome.open_url(board, devs, site.SIGNIN_EMAIL)
    time.sleep(4.0)
    xml = close_popups(board, devs, quiet=True).get(dev.no)
    if "signin/email" not in screen.url_of(xml):
        return "fail: 이메일 로그인 화면이 안 열림 (로그아웃이 안 됐을 수 있음)"
    status: dict[int, str] = {}
    if not step_form(board, devs, {dev.no: account}, status):
        return status.get(dev.no, "fail: 입력 실패")
    time.sleep(5.0)
    xml = close_popups(board, devs).get(dev.no) or ""     # '비밀번호 저장' 말풍선도 '안함'
    if "signin/email" in screen.url_of(xml):
        return WRONG_PW if site.WRONG_PASSWORD_TEXT in xml else "fail: 로그인 화면에 머묾"
    # 로그인 뒤 화면 머리의 닉네임을 기억해 두면, 다음엔 같은 계정인지 보고 전환을
    # 건너뜁니다 (미리 로그인한 폰을 작업 때 또 로그아웃하던 문제, 2026-10-08 83번).
    prof = screen.find(xml, rid=site.HOME_PROFILE)
    if not prof:
        chrome.open_url(board, devs, site.HOME)
        time.sleep(3.0)
        prof = screen.find(close_popups(board, devs, quiet=True).get(dev.no), rid=site.HOME_PROFILE)
    nick = prof.get("text", "") if prof else ""
    if nick:
        remember_nick(account["id"], nick)
    log(f"  {dev.no}: {mask(account['id'])} 로그인됨" + (f" ({nick})" if nick else ""))
    return "ok"


# -- 한 바퀴 ----------------------------------------------------------------------

def _login_pass(board, devs, accounts, status, logout_first, check):
    board.key(224, devs)
    chrome.make_default(board, devs)
    check()

    print("[1] unni.app 홈 + 팝업 닫기 + 로그인/가입")
    tapped, logged = step_home(board, devs, status)
    if logged and logout_first:
        print(f"  로그아웃 먼저: {sorted(d.no for d in logged)}")
        out = logout(board, logged)
        check()
        again = [d for d in logged if out.get(d.no)]
        for d in logged:
            if d not in again:
                status[d.no] = "fail: 로그아웃 안 됨"
        more, logged = step_home(board, again, status)
        tapped += more
    for d in logged:
        status[d.no] = "skip: 이미 로그인됨"
    if not tapped:
        return
    check()

    print("[2] 편지(이메일) 아이콘")
    arrived = step_mail_icon(board, tapped)
    for d in tapped:
        if d not in arrived:
            status[d.no] = "fail: 이메일 로그인 화면으로 못 감"
    if not arrived:
        return
    check()

    print("[3] 아이디/비번 입력")
    submitted = step_form(board, arrived, accounts, status)
    if not submitted:
        return
    check()

    print("[4] 로그인 확인")
    step_verify(board, submitted, status)


def run(panels: str = "60-99", rotation: int = 1,
        log: Callable[[str], None] = print,
        stop: Optional[threading.Event] = None,
        retries: int = 1, logout_first: bool = False,
        dry_run: bool = False, close_tabs: bool = True) -> dict[int, str]:
    """로그인. {폰보드 번호: 결과}.
    결과: "ok" / "skip: …" / "fail: …" / "no_account" / "not_connected" / "dry-run"."""
    stop = stop or threading.Event()

    def check():
        if stop.is_set():
            raise Stopped()

    status: dict[int, str] = {}
    t0 = time.time()
    with _redirect(log) as flush:
        try:
            wanted = parse_panels(panels)
            print(f"로테이션 {rotation} 계정 읽는 중 (시트 '강언아이디')")
            accounts = load_accounts(rotation)
            for no in wanted:
                if no not in accounts:
                    status[no] = "no_account"
            missing = sorted(n for n, v in status.items() if v == "no_account")
            if missing:
                print(f"  !! 계정 없는 폰보드: {missing}")
            print(f"  계정 {sum(1 for n in wanted if n in accounts)}대 확인")
            check()

            if dry_run:
                for no in wanted:
                    if no in accounts:
                        print(f"  {no}: {mask(accounts[no]['id'])}")
                        status[no] = "dry-run"
                return status

            board = Board()
            devs = [d for d in board.select(wanted) if d.no in accounts]
            connected = {d.no for d in devs}
            for no in wanted:
                if no in accounts and no not in connected:
                    status[no] = "not_connected"
            gone = sorted(n for n, v in status.items() if v == "not_connected")
            if gone:
                print(f"  !! 연결 안 된 폰보드: {gone}")
            print(f"대상 {len(devs)}대: {[d.no for d in devs]}")
            if not devs:
                return status

            print("인터넷 연결 점검")
            dead = offline(board, devs)
            for d in dead:
                status[d.no] = NO_NET
            if dead:
                print(f"  !! 인터넷 안 되는 기기 — 건너뜀: {sorted(d.no for d in dead)}")
            devs = [d for d in devs if d not in dead]

            for attempt in range(1 + max(0, retries)):
                todo = [d for d in devs
                        if attempt == 0 or (status.get(d.no, "").startswith("fail")
                                            and status.get(d.no) != WRONG_PW)]
                if not todo:
                    break
                if attempt:
                    # 입력·버튼 다 정상인데 로그인만 안 되는 기기가 40대 중 1~2대
                    # 나옵니다. 같은 절차를 다시 밟으면 됩니다.
                    print(f"\n=== 재시도 {attempt}: {[d.no for d in todo]} ===")
                for d in todo:
                    status[d.no] = "fail: 진행 중 중단됨"
                _login_pass(board, todo, accounts, status, logout_first, check)
                for d in todo:
                    if status.get(d.no) == "fail: 진행 중 중단됨":
                        status[d.no] = "fail: 크롬이 앞에 없음/단계 진행 불가"

            if close_tabs and devs:
                # 작업하며 쌓인 탭을 끝에 비웁니다. 로그인은 쿠키라 풀리지 않습니다.
                check()
                print("\n크롬 탭 모두 닫기")
                chrome.close_all_tabs(board, devs)
        except Stopped:
            print("\n중지됨")
        finally:
            _summary(status)
            print(f"소요 {time.time() - t0:.0f}초")
            flush()
    return status


def run_state(panels: str = "60-99", log: Callable[[str], None] = print) -> dict:
    """로그인 상태 점검만. {번호: (True/False/None, 닉네임)}"""
    with _redirect(log) as flush:
        board = Board()
        wanted = parse_panels(panels)
        devs = board.select(wanted)
        gone = sorted(set(wanted) - {d.no for d in devs})
        print(f"상태 점검 {len(devs)}대")
        home = read_home(board, devs)
        print("\n=== 로그인 상태 ===")
        label = {True: "로그인됨", False: "로그인 안 됨", None: "판독 불가"}
        for no in sorted(home):
            s, nick, _xml = home[no]
            print(f"  {no}: {label[s]}" + (f" — {nick}" if nick else ""))
        by = lambda v: sorted(n for n, (s, _a, _b) in home.items() if s is v)  # noqa: E731
        print(f"\n로그인됨 {len(by(True))}대")
        print(f"로그인 안 됨 {len(by(False))}대: {by(False)}")
        if by(None):
            print(f"판독 불가 {len(by(None))}대: {by(None)}")
        if gone:
            print(f"연결 안 됨 {len(gone)}대: {gone}")
        flush()
    return {no: (s, nick) for no, (s, nick, _x) in home.items()}


def _summary(status):
    groups: dict[str, list[int]] = {}
    for no, v in sorted(status.items()):
        groups.setdefault(v, []).append(no)
    print("\n=== 결과 ===")
    for v, nos in sorted(groups.items(), key=lambda kv: (kv[0] != "ok", kv[0])):
        print(f"  {v}: {len(nos)}대 {nos}")


@contextlib.contextmanager
def _redirect(log):
    """print 를 log 콜백으로. GUI 에서도 같은 로그 창에 나오게 합니다."""
    if log is print:
        yield lambda: None
        return
    writer = _LineWriter(log)
    with contextlib.redirect_stdout(writer):
        yield writer.flush


class _LineWriter:
    def __init__(self, log):
        self.log, self.buf = log, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.log(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.log(self.buf)
            self.buf = ""
