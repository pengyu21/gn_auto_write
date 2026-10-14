"""시트 '바비톡게시글로테이션' 읽기 — 홀/짝 달 로테이션.

    A 주차 | B 홀/짝 달 | C 요일 | D 작업시간 | E 폰보드 | F 수술부위 | G 제목 | H 게시글 | I 주제
    J 작업 여부 | K 최종 업로드 날짜 | L 업로드 계정          (열은 머리글 이름으로 찾음)

규칙 (2026-10-14 사용자 결정)
    * 짝수 달(10·12월…)은 '짝' 줄, 홀수 달은 '홀' 줄만. 주차·요일은 강남언니와 같은 일요일 시작.
    * 폰당 계정 1개. 새 글을 쓸 때마다 그 계정의 이전 글(시트 제목이 같은 글)을 지움.
    * 같은 줄은 2달 뒤에 다시 돌아옴 — 그 사이에 올라간 기록이면 그날 작업은 된 것.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from core.sheet import Sheet
from unni.schedule import (FAIL, RUNNING, SUCCESS, day_of, first_offset, parse_uploaded,  # noqa: F401
                           sheet_serial, week_of)

TAB = "바비톡게시글로테이션"
COLUMNS = {
    "week": ["주차"], "parity": ["홀/짝 달", "홀/짝"], "day": ["요일"], "time": ["작업시간"],
    "board": ["폰보드"], "surgery": ["수술부위"], "title": ["제목"], "text": ["게시글"], "topic": ["주제"],
    "status": ["작업 여부"], "uploaded": ["최종 업로드 날짜"], "account": ["업로드 계정"],
}
STEPS = ["로그인 확인", "지난 글 삭제", "새 글 업로드"]


@dataclass
class Job:
    row: int
    week: int
    parity: str
    day: str
    hour: int
    board: int
    surgery: str
    title: str
    text: str
    topic: str
    status: str
    uploaded: str
    account: str

    def done_on(self, d: date) -> bool:
        """그날 차례의 업로드 기록 — 그날부터 이 줄의 다음 차례(2달 뒤) 전까지 올라갔으면 됨."""
        t = parse_uploaded(self.uploaded)
        return bool(t) and d <= t.date() < next_turn(self.week, self.parity, self.day, d)

    def state_on(self, d: date, today: Optional[date] = None) -> str:
        today = today or date.today()
        if self.done_on(d) or (d == today and self.status.startswith((RUNNING, FAIL, "보류"))):
            return self.status.split(":")[0].strip() or SUCCESS
        return "미실행" if d < today else "예정"


def parity_of(d: date) -> str:
    return "짝" if d.month % 2 == 0 else "홀"


def key_of(j: Job) -> str:
    return f"b{j.week}-{j.parity}-{j.day}-{j.hour}-{j.board}"


@functools.lru_cache(maxsize=4096)
def next_turn(week: int, parity: str, day: str, d: date) -> date:
    for k in range(1, 130):
        x = d + timedelta(days=k)
        if parity_of(x) == parity and week_of(x) == week and day_of(x) == day:
            return x
    return d + timedelta(days=130)


def columns(header: list[str]) -> dict[str, int]:
    found = {}
    for key, names in COLUMNS.items():
        for i, h in enumerate(header):
            if str(h).strip() in names:
                found[key] = i
                break
    missing = [COLUMNS[k][0] for k in COLUMNS if k not in found]
    if missing:
        raise RuntimeError(f"시트 '{TAB}' 머리글에 없는 열: {', '.join(missing)}")
    return found


def col_letter(header: list[str], key: str) -> str:
    return chr(65 + columns(header)[key])


def load_rows(sheet: Optional[Sheet] = None, values=None) -> list[Job]:
    v = values if values is not None else (sheet or Sheet()).read(TAB)
    if not v:
        return []
    c = columns(v[0])
    out = []
    for i, r in enumerate(v[1:], start=2):
        r = list(r) + [""] * (len(v[0]) - len(r))
        g = lambda k: str(r[c[k]]).strip()          # noqa: E731
        try:
            week, board = int(g("week")), int(g("board"))
            hour = int(re.sub(r"\D", "", g("time")))
        except ValueError:
            continue
        out.append(Job(row=i, week=week, parity=g("parity"), day=g("day"), hour=hour, board=board,
                       surgery=g("surgery"), title=g("title"), text=str(r[c["text"]]), topic=g("topic"),
                       status=g("status"), uploaded=g("uploaded"), account=g("account")))
    return out


def jobs_on(rows: list[Job], d: date) -> Optional[list[Job]]:
    """그 날짜의 작업 (시각, 폰 순). 6주차면 None."""
    w = week_of(d)
    if w > 5:
        return None
    par, dn = parity_of(d), day_of(d)
    return sorted((j for j in rows if j.week == w and j.day == dn and j.parity == par),
                  key=lambda j: (j.hour, j.board))


def previous_title(rows: list[Job], j: Job) -> str:
    """이 폰이 지난번에 올린 글의 제목 — 시트에서 '성공' 이고 업로드 시각이 가장 늦은 다른 줄."""
    best = None
    for x in rows:
        if x.board != j.board or x.row == j.row or not x.status.startswith(SUCCESS):
            continue
        t = parse_uploaded(x.uploaded)
        if t and (best is None or t > best[0]):
            best = (t, x.title)
    return best[1] if best else ""
