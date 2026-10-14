"""바비톡 앱 한 대 조작: 띄우기, 팝업 닫기, 아래 탭, 글쓰기, 내가 쓴 글에서 제목으로 찾아 삭제.

모두 화면을 덤프해 글자·id 로 찾아 누릅니다 (좌표 짐작 없음). 아래 탭만 글자 노드에
위치가 없어 '같은 줄 클릭 칸의 순서' 로 누릅니다 (site.py 참고).
실패하면 'fail: 이유' 를 돌려줍니다.
"""
from __future__ import annotations

import re
import time

from core import keyboard, screen
from core.board import Board
from . import site

BAN = ("탈퇴", "계정 삭제", "회원탈퇴")          # 문구가 들어간 요소는 절대 누르지 않음
POPUP_CLOSE = ("오늘 안보기", "닫기", "×")       # 홈 이벤트 배너
GOOGLE_WORDS = ("Google 계정", "Google 계정으로 로그인", "계정 선택", "accounts.google.com")


def _nodes(xml):
    return screen.nodes(xml or "")


def _box(n):
    a = list(map(int, re.findall(r"\d+", n.get("bounds", ""))))
    return a if len(a) == 4 else [0, 0, 0, 0]


def _centre(n):
    a = _box(n)
    return (a[0] + a[2]) // 2, (a[1] + a[3]) // 2


def _visible(n):
    a = _box(n)
    return a[2] > a[0] and a[3] > a[1]


class App:
    def __init__(self, board: Board, dev, log=print):
        self.b, self.dev, self.devs, self.log = board, dev, [dev], log

    # -- 기본 ---------------------------------------------------------------------
    def dump(self) -> str:
        return screen.dump(self.b, self.devs).get(self.dev.no) or ""

    def find(self, xml, text=None, desc=None, rid=None, contains=None):
        for n in _nodes(xml):
            if not _visible(n):
                continue
            if text is not None and n.get("text") != text:
                continue
            if desc is not None and n.get("content-desc") != desc:
                continue
            if rid is not None and n.get("resource-id") != rid:
                continue
            if contains is not None and contains not in (n.get("text", "") + n.get("content-desc", "")):
                continue
            return n
        return None

    def tap(self, n, wait=2.0):
        label = n.get("text", "") + n.get("content-desc", "")
        if any(w in label for w in BAN):
            raise RuntimeError(f"금지 문구 요소: {label}")
        self.b.tap([(self.dev, *_centre(n))])
        time.sleep(wait)

    def tap_text(self, text, wait=2.0, tries=3, **kw) -> bool:
        for _ in range(tries):
            xml = self.dump()
            if self.dismiss_google(xml):                # 단계 사이에 구글 창이 끼어들면 닫고 다시
                xml = self.dump()
            n = self.find(xml, text=text, **kw)
            if n:
                self.tap(n, wait)
                return True
            time.sleep(1.5)
        return False

    # -- 앱 -----------------------------------------------------------------------
    def launch(self):
        self.b.key(224, self.devs)
        self.b.shell(f"am start -n {site.MAIN}", self.devs)
        time.sleep(6)
        self.close_popups()

    def in_front(self) -> bool:
        out = self.b.shell("dumpsys activity activities | grep -m1 -E 'topResumedActivity|mResumedActivity'",
                           self.devs)[0].stdout
        return site.PKG in out

    def google_popup(self, xml) -> bool:
        """다른 기기 로그인 때문에 가끔 뜨는 구글 로그인 창(구글 서비스 화면)인가."""
        if 'package="com.google.android.gms"' in xml or 'package="com.google.android.gsf' in xml:
            return True
        return any(w in xml for w in GOOGLE_WORDS) and site.PKG not in xml

    def dismiss_google(self, xml=None) -> bool:
        """구글 로그인 창이면 홈 버튼으로 내보내고 바비톡을 다시 띄움 (사용자 요청 2026-10-14)."""
        xml = xml if xml is not None else self.dump()
        if not self.google_popup(xml):
            return False
        self.log(f"  {self.dev.no}: 구글 로그인 창 — 홈 버튼으로 닫고 바비톡 다시 띄움")
        self.b.key(3, self.devs)                        # HOME
        time.sleep(2)
        self.b.shell(f"am start -n {site.MAIN}", self.devs)
        time.sleep(5)
        return True

    def close_popups(self, rounds=3):
        for _ in range(rounds):
            xml = self.dump()
            if self.dismiss_google(xml):
                continue
            hit = None
            for word in POPUP_CLOSE:
                hit = self.find(xml, text=word) or self.find(xml, desc=word)
                if hit:
                    break
            if not hit:
                return
            self.log(f"  {self.dev.no}: 팝업 닫음 ({word})")
            self.tap(hit, 1.5)

    def tab(self, name: str):
        """아래 탭. 글자 노드엔 위치가 없어, 탭 줄의 클릭 칸 5개를 왼쪽부터 순서대로 대응."""
        i = site.TABS.index(name)
        for _ in range(3):
            xml = self.dump()
            labels = [n for n in _nodes(xml) if n.get("text") in site.TABS]
            if len(labels) >= 5:
                rows = {}
                for n in _nodes(xml):
                    a = _box(n)
                    if _visible(n) and a[1] > 1400 and (a[2] - a[0]) < 260 and (a[3] - a[1]) > 50:
                        rows.setdefault((a[1], a[3]), {})[a[0]] = n
                for cells in rows.values():
                    if len(cells) == 5:                 # 5칸짜리 줄 = 아래 탭
                        n = cells[sorted(cells)[i]]
                        self.tap(n, 3.0)
                        return True
            self.b.key(4, self.devs)                    # 다른 화면 위면 한 번 뒤로
            time.sleep(1.5)
        return False

    # -- 글쓰기 -----------------------------------------------------------------------
    def write(self, topic: str, title: str, body: str) -> str:
        if topic not in site.TOPICS:
            return f"fail: 주제 '{topic}' 가 앱 주제에 없음"
        if len(title) > 20:
            return f"fail: 제목 {len(title)}자 (20자 이내)"
        if not self.tab("커뮤니티"):
            return "fail: 커뮤니티 탭을 못 찾음"
        self.close_popups()
        if not self.tap_text(site.WRITE_BUTTON, 3.0):
            return "fail: 글쓰기 버튼을 못 찾음"
        xml = self.dump()
        if not self.find(xml, text=site.BOARD_TITLE):
            return "fail: 게시판 선택 창이 안 뜸 (로그인 안 됨?)"
        if not self.tap_text(site.BOARD_SURGERY, 3.0):
            return "fail: '성형' 게시판을 못 찾음"
        if not self.tap_text(topic, 1.5):
            return f"fail: 주제 칩 '{topic}' 을 못 찾음"
        with keyboard.adb_ime(self.b, self.devs) as on:
            if not self.tap_text(site.TITLE_HINT, 1.5):
                return "fail: 제목 칸을 못 찾음"
            keyboard.type_text(self.b, self.devs, lambda d: title, on)
            time.sleep(1.5)
            keyboard.hide(self.b, self.devs)
            time.sleep(1)
            if not self.tap_text(site.BODY_HINT, 1.5):
                return "fail: 내용 칸을 못 찾음"
            keyboard.type_text(self.b, self.devs, lambda d: body, on)
            time.sleep(2)
            keyboard.hide(self.b, self.devs)
            time.sleep(1.5)
        # 입력 확인: 제목 칸 글자가 그대로인지, 내용이 들어갔는지
        xml = self.dump()
        edits = [n for n in _nodes(xml) if n.get("class", "").endswith("EditText")]
        got = [n.get("text", "") for n in edits]
        if not got or got[0] != title:
            return f"fail: 제목 입력 확인 실패 ({got[:1]})"
        if len(got) < 2 or _norm(got[1])[:30] != _norm(body)[:30]:
            return "fail: 내용 입력 확인 실패"
        if not self.tap_text(site.SUBMIT, 5.0):
            return "fail: 작성 완료 버튼을 못 찾음"
        xml = self.dump()
        if not self.find(xml, text=site.UPLOADED_TITLE):
            return "fail: '게시글이 업로드 되었어요' 가 안 뜸"
        n = self.find(xml, rid=site.NO)                 # 글 보기 말고 '아니오'
        if n:
            self.tap(n, 2.0)
        return "ok"

    # -- 내가 쓴 글에서 찾아 삭제 ---------------------------------------------------------
    def open_my_posts(self) -> str:
        if not self.tab("MY 바비톡"):
            return "fail: MY 바비톡 탭을 못 찾음"
        self.close_popups()
        if not self.tap_text(site.MY_POSTS, 3.5):       # 옆 숫자는 계정마다 달라 글자만 봄
            return "fail: '내가쓴글' 을 못 찾음"
        n = self.find(self.dump(), desc=site.MY_POSTS_COMMUNITY)
        if not n:
            return "fail: '커뮤니티' 탭을 못 찾음"
        self.tap(n, 3.5)
        return "ok"

    def delete_post(self, title: str, scrolls: int = 8) -> str:
        """내가 쓴 글 > 커뮤니티 에서 제목이 정확히 같은 글을 찾아 삭제. 'ok' / 'none' / 'fail: …'."""
        r = self.open_my_posts()
        if r != "ok":
            return r
        for i in range(scrolls + 1):
            xml = self.dump()
            if self.find(xml, text=site.NO_POSTS):
                return "none"
            n = self.find(xml, text=title)
            if n:
                self.tap(n, 3.5)
                xml = self.dump()
                if not self.find(xml, text=title):
                    return "fail: 글이 안 열림"
                trash = _trash_button(xml)
                if not trash:
                    return "fail: 휴지통 버튼을 못 찾음"
                self.tap(trash, 2.5)
                xml = self.dump()
                if not self.find(xml, text=site.DELETE_TITLE):
                    return "fail: 삭제 확인 창이 안 뜸"
                self.tap(self.find(xml, rid=site.YES), 3.5)
                if self.find(self.dump(), text=title):
                    return "fail: 삭제 후에도 목록에 남아 있음"
                return "ok"
            if i < scrolls:
                self.b.shell("input swipe 540 1500 540 600 500", self.devs)
                time.sleep(2)
        return "none"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _trash_button(xml):
    """글 보기 화면 오른쪽 위 두 버튼(공유·휴지통) 중 오른쪽. 둘 다 desc 'None' 이라 위치로 구분."""
    top = [n for n in _nodes(xml) if n.get("clickable") == "true" and _visible(n)
           and _box(n)[3] < 300 and _box(n)[0] > 700]
    return max(top, key=lambda n: _box(n)[0]) if len(top) >= 2 else None
