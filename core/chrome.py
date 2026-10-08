"""크롬: 주소 열기, 앞에 있는지 확인, 기본 브라우저 지정, 탭 모두 닫기."""
from __future__ import annotations

import time

from . import screen
from .board import Board

PKG = "com.android.chrome"
MAIN = f"{PKG}/com.google.android.apps.chrome.Main"


def open_url(board: Board, devs, url: str):
    """주소 열기. application_id 를 붙이면 크롬이 새 탭을 만들지 않고
    지난번에 연 탭을 다시 씁니다 (안 붙이면 열 때마다 탭이 하나씩 쌓입니다)."""
    board.run(devs, lambda d: ["shell", "am", "start", "-a", "android.intent.action.VIEW",
                               "-d", url, "--es", "com.android.browser.application_id",
                               PKG, "-n", MAIN], timeout=60)


def in_front(board: Board, devs) -> list:
    """크롬이 맨 앞(Resumed)에 있는 기기만.

    'ResumedActivity' 로 찾는 이유: 안드로이드 13 은 topResumedActivity,
    12(89번)는 mResumedActivity 로 찍습니다. mCurrentFocus 는 SM-F700F 에서
    크롬이 앞에 있어도 null 이라 쓰면 안 됩니다.
    """
    return [r.dev for r in board.shell(
        "dumpsys activity activities | grep -m1 ResumedActivity", devs, timeout=40)
        if PKG in r.stdout]


def wait_front(board: Board, devs, timeout: float = 30.0) -> list:
    """크롬이 앞에 올라온 기기만 돌려줍니다. 안 올라온 기기에 입력을 보내면
    그 입력이 다른 앱(VPN, 파일 관리자 …)으로 들어갑니다."""
    ok, pending, t0 = [], list(devs), time.time()
    while pending and time.time() - t0 < timeout:
        got = in_front(board, pending)
        ok += got
        pending = [d for d in pending if d not in got]
        if pending:
            time.sleep(1.5)
    if pending:
        print(f"  !! 크롬이 앞에 없음 — 건너뜀: {sorted(d.no for d in pending)}")
    return sorted(ok, key=lambda d: d.no)


def make_default(board: Board, devs):
    """크롬을 기본 브라우저로. '기본 브라우저 선택' 창이 앞을 차지하면 이후
    입력이 전부 엉뚱한 곳으로 갑니다 (40대 중 19대가 이것으로 빠진 적 있음)."""
    board.shell("cmd role add-role-holder android.app.role.BROWSER com.android.chrome",
                devs, timeout=60)
    stuck = [r.dev for r in board.shell(
        "dumpsys activity activities | grep -m1 ResumedActivity", devs, timeout=60)
        if "permissioncontroller" in r.stdout]
    if not stuck:
        return
    _hit, miss = screen.tap_found(board, stuck, "기본 브라우저 창 닫기", rid="android:id/button1")
    if miss:
        print(f"  !! 기본 브라우저 창을 못 닫음: {sorted(d.no for d in miss)}")
    time.sleep(2.0)


# -- 탭 모두 닫기 ------------------------------------------------------------------
# adb 에 '탭 모두 닫기' 명령이 없어서 화면으로 합니다:
#   탭 전환 → ⋮ → 탭 모두 닫기 → (확인)

SWITCHER = f"{PKG}:id/tab_switcher_button"
MENU = f"{PKG}:id/menu_button"
CLOSE_ALL = f"{PKG}:id/close_all_tabs_menu_id"
CONFIRM = ["android:id/button1", f"{PKG}:id/positive_button"]
SIGNIN_PROMO = f"{PKG}:id/signin_promo_dismiss_button"
EMPTY_SWITCHER = "여기에서 탭을 확인할 수"      # 탭이 하나도 없을 때 안내 문구
BACK = "BACK"


def _close_step(xml):
    """(이름, 누를 곳 | BACK | None, 끝났는지).

    40대가 같은 화면에 있지 않습니다 — 메뉴가 열린 채인 폰, 이미 빈 폰,
    확인 창이 떠 있는 폰이 섞여 있어서, 화면을 보고 다음 할 일을 고릅니다.
    가장 진행된 상태부터 봅니다.
    """
    if EMPTY_SWITCHER in xml or PKG not in xml:
        # 마지막 탭을 닫으면 크롬이 그대로 꺼지는 기기도 있습니다(89번).
        return None, None, True
    pt = screen.point(xml, rid=CONFIRM)
    if pt and ("모든 탭" in xml or "닫을까요" in xml):
        return "확인", pt, True
    n = screen.find(xml, rid=CLOSE_ALL)
    if n:
        if n.get("enabled") == "false":              # 닫을 탭이 없어 회색
            return "이미 비어 있음", None, True
        return "탭 모두 닫기", screen.centre(n), False
    for label, rid in (("탭 전환", SWITCHER), ("로그인 권유 닫기", SIGNIN_PROMO),
                       ("메뉴", MENU)):
        pt = screen.point(xml, rid=rid)
        if pt:
            return label, pt, False
    # 처음 보는 창(탭 그룹 안내 등)은 뒤로가기로 빠져나온 뒤 다시 봅니다.
    return "뒤로", BACK, False


def close_all_tabs(board: Board, devs, max_steps: int = 6):
    """크롬 탭을 전부 닫습니다. 로그인은 쿠키에 남아 풀리지 않습니다."""
    board.key(224, devs)
    make_default(board, devs)
    pending = _bring_up(board, devs)
    finished, stuck = [], []
    for _ in range(max_steps):
        if not pending:
            break
        screens = screen.dump(board, pending)
        taps, backs, still = [], [], []
        for d in pending:
            xml = screens.get(d.no)
            if not xml:
                stuck.append(d)
                continue
            _label, pt, done = _close_step(xml)
            if pt is None:
                (finished if done else stuck).append(d)
            elif pt == BACK:
                backs.append(d)
                still.append(d)
            else:
                taps.append((d, *pt))
                (finished if done else still).append(d)
        if backs:
            board.key(4, backs)
        if taps:
            board.tap(taps)
        if taps or backs:
            time.sleep(2.4)
        pending = still
    if finished:
        # 메뉴가 열린 채 끝난 기기가 섞여 있어, 다음 작업의 첫 탭이 메뉴를
        # 누르지 않도록 한 번 닫아 둡니다.
        board.key(4, finished)
        time.sleep(1.2)
        print(f"  탭 모두 닫음: {sorted(d.no for d in finished)}")
    left = sorted(d.no for d in pending + stuck)
    if left:
        print(f"  !! 탭을 다 못 닫은 기기: {left}")


def _bring_up(board: Board, devs, tries: int = 3, each: float = 6.0) -> list:
    """크롬을 앞으로. 첫 실행이 씹히는 기기가 있어 안 올라온 기기만 다시 띄웁니다.
    (탭 전환 화면이 열린 뒤에 다시 띄우면 그 화면이 닫히므로 확인만 반복합니다.)"""
    ready, pending = [], list(devs)
    for _ in range(tries):
        if not pending:
            break
        board.run(pending, lambda d: ["shell", "am", "start", "-n", MAIN], timeout=30)
        t0 = time.time()
        while pending and time.time() - t0 < each:
            time.sleep(1.0)
            got = in_front(board, pending)
            ready += got
            pending = [d for d in pending if d not in got]
    if pending:
        print(f"  !! 크롬이 안 올라온 기기: {sorted(d.no for d in pending)}")
    return ready
