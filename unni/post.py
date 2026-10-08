"""강남언니 커뮤니티 글 올리기 / 지우기 — 폰보드 여러 대를 한 번에.

올리기 (사용자가 정한 순서):
    1. 로그인 확인   커뮤니티 머리의 닉네임 버튼 (없으면 실패 — 로그인은 login.py 몫)
    2. 커뮤니티      unni.app/community
    3. 글쓰기 버튼   content-desc 'Write document'
    4. 게시판 설정   카테고리 칸 -> 크롬 선택 목록에서 글자가 정확히 같은 항목
    5. 내용 입력     EditText 에 ADB 키보드로 G열 글 -> 들어간 글자 확인
    6. 등록하기      켜졌을 때만 누름 -> 주소가 /community/<글번호> 로 바뀌면 성공

지우기:
    글 주소 열기 -> 'more icon' -> 시트의 '삭제하기' -> 확인창('내가 쓴 글을
    삭제할까요?')이 떴을 때만 그 안의 '삭제하기' -> 글 주소를 다시 열어
    /community 로 튕기거나 '페이지를 찾을 수 없어요' 면 삭제 확인.

요소 이름은 2026-10-07 78번에서 실측 (unni/site.py).
누를 곳을 못 찾으면 누르지 않고 실패로 남깁니다.
"""
from __future__ import annotations

import re
import time

from core import chrome, keyboard, screen
from . import site
from .popups import close_popups

POST_URL = re.compile(r"unni\.app/community/(\d+)")
EDIT = "android.widget.EditText"
CATEGORIES = {"자유수다", "시술/수술 질문", "발품후기", "병원질문", site.DEFAULT_CATEGORY, "시술/수술 후 고민"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _dismiss_native_list(board, devs):
    """지난번에 열린 채 남은 크롬 선택 목록(게시판 고르기)을 닫습니다."""
    screens = screen.dump(board, devs)
    left = [d for d in devs if screen.find(screens.get(d.no), rid=site.CATEGORY_ITEM)]
    if left:
        board.key(4, left)
        time.sleep(1.2)


# -- 올리기 ------------------------------------------------------------------------

def write(board, devs, text_for, category_for, log=print, expect_for=None) -> dict[int, dict]:
    """{번호: {"ok", "url", "nick", "error"}}. text_for / category_for(기기) -> 글자.

    expect_for(기기) -> 닉네임: 주면 커뮤니티 머리의 닉네임이 그와 다를 때 글을 쓰지
    않습니다 (엉뚱한 계정으로 올라가는 것 방지). 빈 글자면 확인하지 않습니다.
    """
    res = {d.no: {"ok": False, "url": "", "nick": "", "error": ""} for d in devs}
    fail = lambda d, msg: res[d.no].update(error=msg) or log(f"  !! {d.no}: {msg}")   # noqa: E731

    board.key(224, devs)
    chrome.make_default(board, devs)
    _dismiss_native_list(board, devs)

    # 1~2. 커뮤니티 열고 로그인 확인
    chrome.open_url(board, devs, site.COMMUNITY)
    time.sleep(5.0)
    front = chrome.wait_front(board, devs)
    for d in devs:
        if d not in front:
            fail(d, "크롬이 앞에 없음")
    screens = close_popups(board, front, quiet=True)
    live = []
    for d in front:
        xml = screens.get(d.no)
        prof = screen.find(xml, rid=site.HOME_PROFILE)
        want = expect_for(d) if expect_for else ""
        if prof and want and prof.get("text", "") != want:
            res[d.no]["nick"] = prof.get("text", "")
            fail(d, f"다른 계정으로 로그인됨 ({prof.get('text', '')}, 기대 {want})")
        elif prof:
            res[d.no]["nick"] = prof.get("text", "")
            live.append(d)
        elif screen.find(xml, rid=site.HOME_LOGIN):
            fail(d, "로그인 안 됨")
        else:
            fail(d, "커뮤니티 화면을 못 읽음")
    if live:
        log(f"  [1] 로그인 확인: " + ", ".join(f"{d.no}({res[d.no]['nick']})" for d in live))

    # 3. 글쓰기 버튼
    hit, miss = screen.tap_found(board, live, screens=screens, desc=site.WRITE_BUTTON)
    for d in miss:
        fail(d, "글쓰기 버튼을 못 찾음")
    live = hit
    if live:
        log(f"  [2] 글쓰기 버튼: {[d.no for d in live]}")
        time.sleep(2.5)

    # 4. 게시판 설정
    screens = screen.dump(board, live)
    taps, ok = [], []
    for d in live:
        box = next((n for n in screen.nodes(screens.get(d.no))
                    if n.get("text") in CATEGORIES and n.get("clickable") == "true"
                    and n.get("class", "").endswith("View") and screen.centre(n)), None)
        if box:
            taps.append((d, *screen.centre(box)))
        else:
            fail(d, "게시판 칸을 못 찾음")
    board.tap(taps)
    time.sleep(2.0)
    live = [d for d, _x, _y in taps]
    screens = screen.dump(board, live)
    taps = []
    for d in live:
        pt = screen.point(screens.get(d.no), rid=site.CATEGORY_ITEM, text=category_for(d))
        if pt:
            taps.append((d, *pt))
        else:
            fail(d, f"게시판 목록에 '{category_for(d)}' 없음")
            board.key(4, [d])
    board.tap(taps)
    time.sleep(2.0)
    live = [d for d, _x, _y in taps]
    screens = screen.dump(board, live)
    for d in list(live):
        if not any(n.get("text") == category_for(d) and n.get("clickable") == "true"
                   for n in screen.nodes(screens.get(d.no))):
            fail(d, "게시판이 바뀌지 않음")
            live.remove(d)
    if live:
        log(f"  [3] 게시판 설정: " + ", ".join(f"{d.no}({category_for(d)})" for d in live))

    # 5. 내용 입력 — EditText 아래쪽은 등록하기 버튼과 겹쳐서 윗부분을 누릅니다.
    taps = []
    for d in live:
        n = screen.find(screens.get(d.no), cls=EDIT)
        r = screen.rect(n) if n else None
        if r:
            taps.append((d, (r[0] + r[2]) // 2, r[1] + max(20, (r[3] - r[1]) // 5)))
        else:
            fail(d, "내용 칸을 못 찾음")
    live = [d for d, _x, _y in taps]
    if live:
        with keyboard.adb_ime(board, live) as on:
            board.tap(taps)
            time.sleep(1.2)
            keyboard.clear(board, live, on)
            keyboard.type_text(board, live, text_for, on)
            time.sleep(2.0)
            screens = screen.dump(board, live)
            for d in list(live):
                n = screen.find(screens.get(d.no), cls=EDIT)
                got = n.get("text", "") if n else ""
                if _norm(got) != _norm(text_for(d)):
                    fail(d, f"내용이 다르게 들어감 ({len(got)}자 / 원본 {len(text_for(d))}자)")
                    live.remove(d)
        log(f"  [4] 내용 입력 확인: {[d.no for d in live]}")

    # 6. 등록하기 — 키보드를 원래대로 돌리면 화면 키보드가 올라와 화면이 줄어듭니다.
    #    입력할 때 읽은 위치로 누르면 빗나가므로(2026-10-08 83번) 키보드를 내리고 다시 읽음.
    if live:
        keyboard.hide(board, live)
        time.sleep(0.8)
        screens = screen.dump(board, live)
    taps = []
    for d in live:
        btn = screen.find(screens.get(d.no), text=site.SUBMIT_POST)
        if btn and btn.get("enabled") == "true":
            taps.append((d, *screen.centre(btn)))
        else:
            fail(d, "등록하기 버튼이 꺼져 있음")
    board.tap(taps)
    live = [d for d, _x, _y in taps]
    if live:
        log(f"  [5] 등록하기: {[d.no for d in live]}")
    pending, t0 = list(live), time.time()
    while pending and time.time() - t0 < 25:
        time.sleep(2.5)
        screens = screen.dump(board, pending)
        for d in list(pending):
            m = POST_URL.search(screen.url_of(screens.get(d.no)))
            if m:
                res[d.no].update(ok=True, url=f"{site.COMMUNITY}/{m.group(1)}")
                log(f"  {d.no}: 등록됨 {res[d.no]['url']}")
                pending.remove(d)
    for d in pending:
        fail(d, "등록 후 글 주소로 안 바뀜 (등록 여부 직접 확인 필요)")
    return res


# -- 지우기 ------------------------------------------------------------------------

def is_gone(xml) -> bool:
    """지금 화면이 '없는 글' 인가: 글 주소가 아니거나 '페이지를 찾을 수 없어요'."""
    return not POST_URL.search(screen.url_of(xml)) or site.NOT_FOUND_TEXT in (xml or "")


def delete(board, devs, url_for, log=print) -> dict[int, str]:
    """{번호: '삭제됨' | '이미 없음' | '실패: …'}."""
    res: dict[int, str] = {}
    board.key(224, devs)
    _dismiss_native_list(board, devs)
    for d in devs:
        chrome.open_url(board, [d], url_for(d))
    time.sleep(5.0)
    front = chrome.wait_front(board, devs)
    for d in devs:
        if d not in front:
            res[d.no] = "실패: 크롬이 앞에 없음"
    screens = close_popups(board, front, quiet=True)
    live = []
    for d in front:
        xml = screens.get(d.no)
        u = screen.url_of(xml)
        if "unni.app/community" not in u:
            res[d.no] = f"실패: 글 화면이 아님 ({u})"
        elif is_gone(xml):
            res[d.no] = "이미 없음"
        else:
            live.append(d)

    # 점 3개
    hit, miss = screen.tap_found(board, live, screens=screens, desc=site.POST_MORE)
    for d in miss:
        res[d.no] = "실패: 더보기 버튼 없음 (내 글이 아니거나 화면 못 읽음)"
    live = hit
    time.sleep(1.8)
    # 시트의 '삭제하기'
    hit, miss = screen.tap_found(board, live, text=site.DELETE)
    for d in miss:
        res[d.no] = "실패: 삭제하기 항목 없음 (내 글이 아닐 수 있음)"
        board.key(4, [d])
    live = hit
    time.sleep(1.8)
    # 확인창이 떴을 때만 그 안의 '삭제하기' (clickable 인 것 중 마지막 = 창 위쪽)
    screens = screen.dump(board, live)
    taps = []
    for d in live:
        xml = screens.get(d.no) or ""
        btns = [n for n in screen.nodes(xml) if n.get("text") == site.DELETE
                and n.get("clickable") == "true" and screen.centre(n)]
        if site.DELETE_CONFIRM_TEXT in xml and btns:
            taps.append((d, *screen.centre(btns[-1])))
        else:
            res[d.no] = "실패: 삭제 확인창이 안 뜸"
            board.key(4, [d])
    board.tap(taps)
    live = [d for d, _x, _y in taps]
    if live:
        log(f"  삭제 확인 누름: {[d.no for d in live]}")
        time.sleep(4.0)
        for d in live:
            chrome.open_url(board, [d], url_for(d))
        time.sleep(5.0)
        screens = close_popups(board, live, quiet=True)
        for d in live:
            res[d.no] = "삭제됨" if is_gone(screens.get(d.no)) else "실패: 지운 뒤에도 글이 열림"
    for d in devs:
        log(f"  {d.no}: {res.get(d.no)}")
    return res
