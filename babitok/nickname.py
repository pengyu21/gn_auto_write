"""바비톡 닉네임 바꾸기 (매달 말일 밤 12시, 2026-10-16 요청).

    MY 바비톡 → 오른쪽 위 사람 아이콘 → 프로필 편집 → 닉네임 줄 '변경' → '변경할 닉네임' 칸에 입력 → '변경 완료'
    '이미 존재하는 닉네임입니다.' 같은 안내(text_guide)가 뜨면 뒤에 1~10 을 붙여 될 때까지.

새 닉네임은 40대가 서로 겹치지 않게 랜덤으로 뽑음 (지금 쓰는 닉네임·지난 닉네임과도 안 겹치게).
화면 요소는 60번 실측 (2026-10-16).
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime

from core import keyboard, screen
from core.board import ROOT
from .app import App, _box, _nodes

HISTORY = ROOT / "babi_nicks.json"       # 폰별 닉네임 바꾼 기록 (공개 저장소 제외)
SUFFIX_MAX = 10

# 커뮤니티 닉네임처럼 보이게: [꾸밈말][이름말] 조합 (3~8자). 숫자·특수문자 없이 시작하고, 막히면 뒤에 1~10.
_A = ("말랑", "포근", "졸린", "새콤", "달콤", "몽글", "보송", "느긋", "반짝", "산뜻", "소심한", "용감한", "배고픈", "수줍은",
      "엉뚱한", "다정한", "씩씩한", "초록", "하늘", "노을", "새벽", "봄날", "여름", "가을", "겨울", "오늘도", "내일은",
      "작은", "동글", "꼬마", "행복한", "느린", "바쁜", "조용한", "상큼", "따뜻한", "말간", "빛나는", "꿈꾸는", "웃는")
_B = ("복숭아", "고양이", "강아지", "토끼", "다람쥐", "곰돌이", "펭귄", "수달", "판다", "여우", "햄찌", "참새", "구름",
      "별빛", "달님", "바다", "마카롱", "푸딩", "젤리", "라떼", "쿠키", "모찌", "호두", "자두", "귤", "레몬", "딸기",
      "감자", "고구마", "옥수수", "콩떡", "만두", "소나무", "민들레", "해바라기", "튤립", "산책러", "기록자", "여행자", "집순이")


def load_history() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_history(no: int, old: str, new: str):
    h = load_history()
    h.setdefault(str(no), []).append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "from": old, "to": new})
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")


def generate(nos: list[int], taken: set[str], seed=None) -> dict[int, str]:
    """폰마다 서로 다른 새 닉네임. taken(지금·지난 닉네임)과도 겹치지 않게."""
    rng = random.Random(seed)
    used = {t.strip() for t in taken if t}
    out = {}
    for no in nos:
        for _ in range(500):
            name = rng.choice(_A) + rng.choice(_B)
            if 3 <= len(name) <= 8 and name not in used:
                break
        used.add(name)
        out[no] = name
    return out


def _person_icon(xml):
    """MY 바비톡 오른쪽 위 두 버튼(사람·설정) 중 왼쪽 = 사람 아이콘."""
    top = [n for n in _nodes(xml) if n.get("clickable") == "true" and _box(n)[3] < 300 and _box(n)[0] > 700]
    return min(top, key=lambda n: _box(n)[0]) if len(top) >= 2 else None


def _nick_change_button(xml):
    """'닉네임' 제목 아래 줄의 '변경' 버튼 (이메일·휴대폰 줄에도 같은 이름 버튼이 있어 위치로 고름)."""
    titles = [n for n in _nodes(xml) if n.get("resource-id", "").endswith("text_title")]
    nick = next((t for t in titles if t.get("text") == "닉네임"), None)
    if not nick:
        return None
    below = [t for t in titles if _box(t)[1] > _box(nick)[1]]
    limit = min((_box(t)[1] for t in below), default=10 ** 6)
    btns = [n for n in _nodes(xml) if n.get("resource-id", "").endswith("button_text") and n.get("text") == "변경"
            and _box(nick)[1] < _box(n)[1] < limit]
    return btns[0] if btns else None


def _new_input(xml):
    """'변경할 닉네임' 제목 바로 아래 입력 칸."""
    nodes = list(_nodes(xml))
    for i, n in enumerate(nodes):
        if n.get("text") == "변경할 닉네임":
            return next((m for m in nodes[i + 1:] if m.get("class", "").endswith("EditText")), None)
    return None


def _current_nick(app: App) -> str:
    n = app.find(app.dump(), rid="com.sleet.beautyplastic:id/mypage_name_text")
    return n.get("text", "") if n else ""


def change(app: App, base: str, log=print) -> tuple[str, str, str]:
    """닉네임 바꾸기 → ('ok', 이전, 새) / ('fail: 이유', 이전, '')."""
    if not app.tab("MY 바비톡"):
        return "fail: MY 바비톡 탭을 못 찾음", "", ""
    icon = _person_icon(app.dump())
    if not icon:
        return "fail: 사람 아이콘을 못 찾음", "", ""
    app.tap(icon, 3.0)
    old = _current_nick(app)
    if not app.tap_text("프로필 편집", 3.5):
        return "fail: '프로필 편집' 을 못 찾음", old, ""
    btn = _nick_change_button(app.dump())
    if not btn:
        return "fail: 닉네임 '변경' 버튼을 못 찾음", old, ""
    app.tap(btn, 2.5)
    tried = []
    with keyboard.adb_ime(app.b, app.devs) as on:
        for cand in [base] + [f"{base}{i}" for i in range(1, SUFFIX_MAX + 1)]:
            xml = app.dump()
            box = _new_input(xml)
            if not box:
                return "fail: '변경할 닉네임' 칸을 못 찾음", old, ""
            app.tap(box, 1.0)
            keyboard.clear(app.b, app.devs, on)
            keyboard.type_text(app.b, app.devs, lambda d: cand, on)
            time.sleep(1.2)
            keyboard.hide(app.b, app.devs)
            time.sleep(1.0)
            done = app.find(app.dump(), text="변경 완료")
            if not done:
                return "fail: '변경 완료' 버튼을 못 찾음", old, ""
            app.tap(done, 3.0)
            xml = app.dump()
            guide = next((n.get("text", "") for n in _nodes(xml)
                          if n.get("resource-id", "").endswith("text_guide") and n.get("text")), "")
            if guide:
                tried.append(f"{cand}({guide})")
                log(f"  {app.dev.no}: '{cand}' 안 됨 — {guide}")
                continue
            # 안내가 없으면 바뀐 것: 닉네임 칸이 새 이름인지 확인
            edits = [n.get("text", "") for n in _nodes(xml) if n.get("class", "").endswith("EditText")]
            if cand in edits[:1] or not app.find(xml, text="변경할 닉네임"):
                return "ok", old, cand
            tried.append(f"{cand}(확인 안 됨)")
    return f"fail: 다 막힘 — {', '.join(tried[-3:])}", old, ""


def run(nos, names: dict[int, str], log=print, board_factory=None) -> dict[int, tuple]:
    """여러 폰 바꾸기 (호출하는 쪽에서 폰을 잡아 둔 상태). {폰: (결과, 이전, 새)}"""
    from core.board import Board
    out = {}
    for no in nos:
        b = (board_factory or Board)()
        devs = b.select([no])
        if not devs:
            out[no] = ("fail: 폰 연결 안 됨", "", "")
            continue
        app = App(b, devs[0], log=log)
        try:
            app.launch()
            r = change(app, names[no], log=log)
        except Exception as e:                        # noqa: BLE001
            r = (f"fail: {type(e).__name__}: {e}", "", "")
        try:
            app.tab("홈")
        except Exception:                              # noqa: BLE001
            pass
        out[no] = r
        if r[0] == "ok":
            save_history(no, r[1], r[2])
            log(f"  {no}: 닉네임 {r[1]} → {r[2]}")
        else:
            log(f"!! {no}: 닉네임 변경 실패 — {r[0][5:].strip()}")
    return out
