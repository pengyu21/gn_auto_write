"""'강언게시글로테이션' 시트 일정 — 달력 날짜 <-> 시트의 주차/요일.

주차는 그 달 달력을 **일요일 시작**으로 나눈 줄 번호입니다. 1일이 금·토요일이면
30·31일이 6주차로 넘어가는데, 시트에는 1~5주차만 있어서 그날은 작업이 없습니다
(하루 이틀 빠지는 것은 감수하기로 함).

시트 행은 매달 다시 쓰입니다. 그래서 '이번 달에 했는가' 는 I열(작업 여부)이
아니라 L열(최종 업로드 날짜)이 그 날짜인지로 봅니다.

    rows = load_rows()
    jobs = jobs_on(rows, date.today())     # None = 6주차라 작업 없음
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from core.sheet import Sheet

TAB = "강언게시글로테이션"
DAYS = "일월화수목금토"          # 일요일 시작

# 필드 -> 열 이름 후보. 열 순서·이름이 조금 바뀌어도 머리글로 찾습니다.
COLUMNS = {
    "week": ["주차"], "day": ["요일"], "hour": ["작업시간"], "rotation": ["로테이션"],
    "board": ["폰보드"], "surgery": ["수술부위"], "text": ["게시글"], "category": ["게시판"],
    "status": ["작업 여부"], "url": ["게시글 URL", "URL"], "deleted": ["삭제 유무"],
    "uploaded": ["최종 업로드 날짜"], "account": ["업로드 계정"],
}
OPTIONAL = {"account", "deleted"}

# I열(작업 여부)에 쓰는 값
SUCCESS, FAIL, RUNNING, WAITING = "성공", "실패", "작업중", "대기"


@dataclass
class Job:
    row: int            # 시트 행 번호 (머리글 = 1)
    week: int
    day: str            # '월' ...
    hour: int
    rotation: int
    board: int
    surgery: str
    text: str
    category: str
    status: str         # I 작업 여부
    url: str            # J 게시글 URL
    deleted: str        # K 삭제 유무
    uploaded: str       # L 최종 업로드 날짜 'YYYY-MM-DD (요일)'
    account: str = ""   # M 업로드 계정

    def done_on(self, d: date) -> bool:
        """그 날짜에 업로드 기록이 있는가."""
        t = parse_uploaded(self.uploaded)
        return bool(t) and t.date() == d

    def state_on(self, d: date, today: Optional[date] = None) -> str:
        """그 날짜 기준 표시 상태: I열 값 / '미실행' / '예정'."""
        today = today or date.today()
        if self.done_on(d) or (d == today and self.status.startswith((RUNNING, FAIL, "보류"))):
            # I열은 '실패: 이유' 처럼 이유가 붙을 수 있어 앞 낱말만 상태로 씁니다.
            return (self.status.split(":")[0].strip() or SUCCESS)
        return "미실행" if d < today else "예정"


# L열(최종 업로드)은 시트 날짜 값(숫자)으로 씁니다. 글자로 쓰면 열에 날짜 서식을
# 줘도 바뀌지 않습니다(2026-10-07 확인). 보이는 모양은 열 서식
# 'yyyy-mm-dd (ddd) hh:mm' -> '2026-10-07 (수) 17:31'.
_EPOCH = datetime(1899, 12, 30)


def sheet_serial(t: datetime) -> float:
    """datetime -> 시트 날짜 숫자 (1899-12-30 부터 센 날수)."""
    return round((t - _EPOCH).total_seconds() / 86400, 8)


def parse_uploaded(v: str) -> Optional[datetime]:
    """L열 값 -> datetime. 날짜 서식이면 'yyyy-MM-dd HH:mm', 서식이 없으면 숫자,
    예전 글자 기록이면 '2026-10-07 (수)' / '2026-10-07 (수) 17:31'."""
    v = (v or "").strip()
    if not v:
        return None
    try:
        return _EPOCH + timedelta(days=float(v))
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s*\(.\))?(?:\s+(\d{1,2}):(\d{2}))?", v)
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))


def load_rows(sheet: Optional[Sheet] = None, values=None) -> list[Job]:
    """시트 행 -> Job. 이미 읽은 values 를 주면 다시 읽지 않습니다."""
    values = values if values is not None else (sheet or Sheet()).read(TAB)
    idx = columns(values[0])
    jobs = []
    for n, raw in enumerate(values[1:], start=2):
        cell = lambda f: (raw[idx[f]] if idx.get(f, 99) < len(raw) else "").strip()   # noqa: E731
        if not cell("week") or not cell("board"):
            continue
        jobs.append(Job(
            row=n, week=int(cell("week")), day=cell("day"),
            hour=int(cell("hour").rstrip("시") or 0), rotation=int(cell("rotation") or 0),
            board=int(cell("board")), surgery=cell("surgery"), text=raw[idx["text"]] if idx["text"] < len(raw) else "",
            category=cell("category"), status=cell("status"), url=cell("url"),
            deleted=cell("deleted"), uploaded=cell("uploaded"), account=cell("account")))
    return jobs


def columns(header) -> dict[str, int]:
    """필드 -> 0부터 센 열 번호."""
    head = [h.strip() for h in header]
    idx = {}
    for field, names in COLUMNS.items():
        hit = next((head.index(n) for n in names if n in head), None)
        if hit is None:
            if field in OPTIONAL:
                continue
            raise ValueError(f"'{TAB}' 탭에 '{names[0]}' 열이 없습니다")
        idx[field] = hit
    return idx


def col_letter(i: int) -> str:
    """0 -> 'A'."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def first_offset(year: int, month: int) -> int:
    """1일 앞의 빈칸 수 (일요일=0)."""
    return (calendar.weekday(year, month, 1) + 1) % 7


def week_of(d: date) -> int:
    return (d.day - 1 + first_offset(d.year, d.month)) // 7 + 1


def day_of(d: date) -> str:
    return DAYS[(d.weekday() + 1) % 7]


def jobs_on(rows: list[Job], d: date) -> Optional[list[Job]]:
    """그 날짜의 작업 (시각, 폰 순). 6주차면 None."""
    w = week_of(d)
    if w > 5:
        return None
    dn = day_of(d)
    return sorted((j for j in rows if j.week == w and j.day == dn),
                  key=lambda j: (j.hour, j.board))
