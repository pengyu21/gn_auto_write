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
# 팝업은 쓸 일이 없으니 보이면 전부 닫음 (2026-10-19 요청). '확인'·'삭제' 처럼 무언가 실행하는 말은 넣지 않음.
POPUP_CLOSE = ("오늘 안보기", "오늘 하루 보지 않기", "오늘 그만 보기", "다시 보지 않기", "다시 보지않기",
               "닫기", "×", "X", "시트 닫기", "로그인 바텀 시트 닫기", "나중에", "나중에 하기", "다음에 하기",
               "다음에", "괜찮아요", "취소", "허용 안함", "허용 안 함", "Don't allow", "Close", "Not now", "Cancel")
SYSTEM_PKGS = ("com.android.systemui",)            # 덤프에 섞여 나와도 팝업 아님
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
            nr = n.get("resource-id", "")
            if rid is not None and nr != rid and not nr.endswith("/" + rid) and nr != rid.split("/")[-1]:
                continue                                # 로그인 화면은 앱 이름 없는 짧은 id (input_login_email)
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

    def foreign_screen(self, xml) -> str:
        """바비톡이 아닌 앱·시스템 창(권한 창, 다른 앱 광고 등)이 맨 앞이면 그 패키지 이름."""
        pkgs = {n.get("package", "") for n in _nodes(xml)} - {"", *SYSTEM_PKGS}
        return "" if not pkgs or site.PKG in pkgs else sorted(pkgs)[0]

    def close_popups(self, rounds=5) -> int:
        """떠 있는 팝업을 모두 닫음 (이벤트 배너·바텀 시트·안내 창·권한 창·다른 앱 화면). 닫은 개수."""
        closed = 0
        for _ in range(rounds):
            xml = self.dump()
            if self.dismiss_google(xml):
                closed += 1
                continue
            if self.verify_screen(xml):                 # 지난번 본인인증 창이 맨 앞에 남아 있으면 닫고 시작
                self.log(f"  {self.dev.no}: 본인인증 창이 떠 있어 '다음에 하기' 로 닫음")
                self.close_verify()
                closed += 1
                continue
            hit, word = None, ""
            for word in POPUP_CLOSE:
                hit = self.find(xml, text=word) or self.find(xml, desc=word)
                if hit:
                    break
            if hit:
                self.log(f"  {self.dev.no}: 팝업 닫음 ({word})")
                self.tap(hit, 2.0)                      # 닫히는 동안 잠깐 기다림 (바로 다음 버튼을 못 찾던 문제)
                closed += 1
                continue
            other = self.foreign_screen(xml)
            if other:                                   # 닫기 버튼 없는 다른 앱 화면 → 홈으로 내보내고 바비톡 다시
                self.log(f"  {self.dev.no}: 다른 앱 화면({other}) — 홈 버튼으로 닫고 바비톡 다시 띄움")
                self.b.key(3, self.devs)
                time.sleep(2)
                self.b.shell(f"am start -n {site.MAIN}", self.devs)
                time.sleep(5)
                closed += 1
                continue
            break
        if closed:
            time.sleep(1.0)
        return closed

    def open_write(self) -> str:
        """커뮤니티 > 글쓰기. 팝업 때문에 못 찾으면 팝업 닫고 3번까지 다시 → 'ok' / 'verify' / 'fail: …'."""
        for attempt in range(3):
            if not self.tab("커뮤니티"):
                if attempt == 2:
                    return "fail: 커뮤니티 탭을 못 찾음"
                self.close_popups()
                continue
            self.close_popups()
            if self.tap_text(site.WRITE_BUTTON, 3.0):
                xml = self.dump()
                if self.verify_screen(xml):
                    self.close_verify()
                    return "verify"
                if self.find(xml, text=site.BOARD_TITLE):
                    return "ok"
                if self.login_screen(xml) or self.find(xml, desc="로그인 바텀 시트 닫기") \
                        or self.find(xml, desc="이메일 로그인"):
                    return "fail: 게시판 선택 창이 안 뜸 (로그인 안 됨?)"   # 로그인 창은 팝업 아님 — 닫지 않음
                if not self.close_popups():             # 게시판 선택 창 대신 다른 창 — 팝업이면 닫고 다시
                    return "fail: 게시판 선택 창이 안 뜸 (로그인 안 됨?)"
            else:
                self.log(f"  {self.dev.no}: 글쓰기 버튼이 안 보임 — 팝업 닫고 다시 ({attempt + 1}/3)")
                if not self.close_popups():
                    self.b.key(4, self.devs)            # 알 수 없는 창 위면 한 번 뒤로
                    time.sleep(1.5)
        return "fail: 글쓰기 버튼을 못 찾음"

    def tab(self, name: str):
        """아래 탭. 글자 노드엔 위치가 없어, 탭 줄의 클릭 칸 5개를 왼쪽부터 순서대로 대응."""
        i = site.TABS.index(name)
        for attempt in range(4):
            if attempt:
                time.sleep(1.5)                         # 창이 닫히는 중이면 잠깐 기다렸다 다시 봄
            if not self.in_front():                     # '뒤로' 때문에 앱이 빠져나갔으면 다시 띄움
                self.b.shell(f"am start -n {site.MAIN}", self.devs)
                time.sleep(5)
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
            if attempt >= 1:                            # 처음 한 번은 기다리기만, 그래도 없으면 다른 화면 위라 보고 뒤로
                self.b.key(4, self.devs)
                time.sleep(1.5)
        return False

    # -- 계정 바꾸기 (로그아웃 → 이메일 로그인) — 2026-10-19 75번 실측 ---------------------------
    def login_screen(self, xml=None) -> bool:
        """로그아웃 상태의 시작 화면('이메일로 시작하기') 이나 이메일 입력 화면인가."""
        xml = xml if xml is not None else self.dump()
        return bool(self.find(xml, text="이메일로 시작하기") or self.find(xml, rid=f"{site.PKG}:id/input_login_email"))

    def current_account(self) -> str:
        """MY 바비톡 > 사람 아이콘 > 마이페이지의 가입 아이디(메일). 로그아웃이면 ''."""
        if not self.in_front():
            self.b.shell(f"am start -n {site.MAIN}", self.devs)
            time.sleep(5)
        if self.login_screen():                         # 로그아웃 상태 — 탭이 없어 '뒤로' 를 누르면 앱이 꺼짐
            return ""
        if not self.tab("MY 바비톡"):
            return ""
        top = [n for n in _nodes(self.dump()) if n.get("clickable") == "true" and _box(n)[3] < 300 and _box(n)[0] > 700]
        if len(top) < 2:
            return ""
        self.tap(min(top, key=lambda n: _box(n)[0]), 3.0)              # 사람 아이콘
        n = self.find(self.dump(), rid=f"{site.PKG}:id/mypage_join_type")
        acc = n.get("text", "") if n else ""
        self.tab("홈")
        return acc

    def logout(self) -> str:
        if not self.tab("MY 바비톡"):
            return "fail: MY 바비톡 탭을 못 찾음"
        top = [n for n in _nodes(self.dump()) if n.get("clickable") == "true" and _box(n)[3] < 300 and _box(n)[0] > 700]
        if len(top) < 2:
            return "fail: 설정 버튼을 못 찾음"
        self.tap(max(top, key=lambda n: _box(n)[0]), 3.0)              # 설정(톱니)
        for _ in range(5):                                              # 맨 아래 '계정' 칸까지 내림
            if self.find(self.dump(), text="로그아웃"):
                break
            self.b.shell("input swipe 540 1500 540 400 400", self.devs)
            time.sleep(1.5)
        n = self.find(self.dump(), text="로그아웃")                    # 바로 아래 '회원탈퇴' 는 BAN 으로 막힘
        if not n:
            return "fail: '로그아웃' 을 못 찾음"
        self.tap(n, 2.5)
        yes = self.find(self.dump(), rid=site.YES)
        if not yes:
            return "fail: 로그아웃 확인 창이 안 뜸"
        self.tap(yes, 5.0)
        return "ok"

    def login_email(self, email: str, pw: str) -> str:
        """로그인 화면 → '이메일로 시작하기' → 이메일·비밀번호 → 로그인. 'ok' / 'fail: …'."""
        if not self.in_front():
            self.b.shell(f"am start -n {site.MAIN}", self.devs)
            time.sleep(5)
        email_rid = f"{site.PKG}:id/input_login_email"
        for _ in range(4):                              # 시작 화면이면 '이메일로 시작하기', 입력 화면이 뜰 때까지
            xml = self.dump()
            if self.find(xml, rid=email_rid):
                break
            n = self.find(xml, text="이메일로 시작하기")
            if n:
                self.tap(n, 3.0)
            else:
                time.sleep(2.0)
        else:
            return "fail: 이메일 로그인 화면이 안 뜸 (로그아웃 안 됨?)"
        with keyboard.adb_ime(self.b, self.devs) as on:
            for rid, value in (("input_login_email", email), ("input_login_password", pw)):
                box = None
                for _ in range(3):
                    box = self.find(self.dump(), rid=f"{site.PKG}:id/{rid}")
                    if box:
                        break
                    time.sleep(1.5)
                if not box:
                    return f"fail: {rid} 칸을 못 찾음"
                self.tap(box, 1.0)
                keyboard.clear(self.b, self.devs, on)
                keyboard.type_text(self.b, self.devs, lambda d: value, on)
                time.sleep(1.0)
            keyboard.hide(self.b, self.devs)
            time.sleep(1.0)
        btn = self.find(self.dump(), rid=f"{site.PKG}:id/button_login") or self.find(self.dump(), text="로그인")
        if not btn:
            return "fail: 로그인 버튼을 못 찾음"
        self.tap(btn, 6.0)
        xml = self.dump()
        if self.find(xml, rid=f"{site.PKG}:id/input_login_email"):     # 아직 로그인 화면 = 실패
            msg = next((n.get("text", "") for n in _nodes(xml) if n.get("text") and
                        any(w in n.get("text", "") for w in ("일치", "확인", "잘못", "없는", "오류", "실패"))), "")
            return f"fail: 로그인 안 됨{(' — ' + msg) if msg else ''}"
        self.close_popups()
        return "ok"

    def switch_account(self, email: str, pw: str) -> str:
        """지금 계정이 email 이면 그대로, 아니면 로그아웃 후 email 로 로그인. 'ok'/'skip'/'fail: …'."""
        now = self.current_account()
        if now and now.split("@")[0].lower() == email.split("@")[0].lower():
            return "skip: 이미 이 계정"
        if now or not self.login_screen():
            r = self.logout()
            if r != "ok":
                return r
        r = self.login_email(email, pw)
        if r != "ok":
            return r
        got = self.current_account()
        if got.split("@")[0].lower() != email.split("@")[0].lower():
            return f"fail: 로그인 뒤 계정이 다름 ({got[:3]}***)"
        return "ok"

    # -- 본인인증 ---------------------------------------------------------------------
    def verify_screen(self, xml) -> bool:
        return bool(self.find(xml, rid=site.VERIFY_TITLE) or self.find(xml, text=site.VERIFY_TEXT))

    def close_verify(self):
        n = self.find(self.dump(), rid=site.VERIFY_LATER) or self.find(self.dump(), text="다음에 하기")
        if n:
            self.tap(n, 2.0)
        else:
            self.b.key(4, self.devs)
            time.sleep(1.5)

    def can_write(self) -> str:
        """커뮤니티 > 글쓰기 를 눌러 봄: 'ok'(게시판 선택 창 — 닫고 돌아옴) / 'verify'(본인인증 창) / 'fail: …'.
        지난 글을 지우기 전에 확인 — 지운 뒤에 본인인증 창이 뜨면 지난 글만 사라지고 새 글은 못 올림."""
        r = self.open_write()
        if r != "ok":
            return r
        n = self.find(self.dump(), desc="닫기")
        if n:
            self.tap(n, 1.5)
        else:
            self.b.key(4, self.devs)
            time.sleep(1.5)
        return "ok"

    # -- 글쓰기 -----------------------------------------------------------------------
    def write(self, topic: str, title: str, body: str) -> str:
        if topic not in site.TOPICS:
            return f"fail: 주제 '{topic}' 가 앱 주제에 없음"
        if len(title) > 20:
            return f"fail: 제목 {len(title)}자 (20자 이내)"
        r = self.open_write()
        if r != "ok":
            return r
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
        if self.verify_screen(xml):                     # 작성 완료 때 뜨는 경우도 대비
            self.close_verify()
            return "verify"
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
                before = sum(1 for m in _nodes(xml) if _visible(m) and m.get("text") == title)
                self.tap(n, 3.5)                        # 같은 제목이 여러 개면 맨 위(가장 최근) 글
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
                after = sum(1 for m in _nodes(self.dump()) if _visible(m) and m.get("text") == title)
                if after >= before:                     # 같은 제목 글이 하나 더 있으면 그건 남는 게 맞음
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
