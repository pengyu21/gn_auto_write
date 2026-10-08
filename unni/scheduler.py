"""자동 실행 — 대시보드 안에서 도는 스케줄러.

규칙 (사용자가 정한 것)
    * 항상 **오늘 날짜** 의 행만 실행. 시간이 지난 행은 다시 시도하지 않고 건너뜀.
    * 'NN시' 행은 그 시간 안 무작위 분(0~40분)에 시작. 정한 시각은 run_plan.json 에
      남겨서 프로그램을 다시 켜도 같은 시각을 씁니다.
    * settings.json 의 auto_from ~ auto_until 기간에만 실행 (없으면 기간 제한 없음).
    * 5분마다 시트 '강언게시글로테이션' M1 에 마지막 실행 시각(생존 신호)을 적음.

속도
    * 미리 로그인: 쉬는 폰은 다음 차례 계정으로 미리 로그인해 둡니다. 작업 시각에는
      닉네임만 확인하고 바로 글을 씁니다 (계정 전환 70초 -> 몇 초).
      시작 10분 안쪽으로 남은 작업은 미리 로그인하지 않고 본 작업이 직접 합니다.

같은 폰에서 작업이 겹치지 않게 폰마다 한 번에 하나만 돌립니다.
"""
from __future__ import annotations

import json
import random
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from core.board import ROOT, Board, load_settings
from core.sheet import Sheet
from . import job, login, notify, schedule

PLAN = ROOT / "run_plan.json"
MAX_MINUTE = 40                 # 시간대 안에서 시작 분 범위 0~40 (끝나기 전에 마치도록)
PREP_LEAD = timedelta(minutes=10)
BEAT_EVERY = 300                # 생존 신호 간격(초)
SHEET_EVERY = 600               # 시트 다시 읽는 간격(초) — 실행 직전에는 따로 다시 읽음
MAX_PREP = 3                    # 미리 로그인 동시에 몇 대까지
BEAT_CELL = "M1"


class Scheduler:
    def __init__(self, log: Callable[[str], None] = print, on_change: Callable[[], None] = lambda: None):
        self.log = log
        self.on_change = on_change
        self.busy: dict[int, str] = {}          # 폰 -> '작업' / '미리 로그인'
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rows: list[schedule.Job] = []
        self._rows_at = 0.0
        self._beat_at = 0.0
        self._plan = self._load()
        self._thread: Optional[threading.Thread] = None

    # -- 상태 ----------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._plan.get("enabled"))

    def set_enabled(self, on: bool):
        self._plan["enabled"] = bool(on)
        self._save()
        self.log(f"자동 실행 {'켜짐' if on else '꺼짐'}")
        self.on_change()

    def window(self) -> tuple[Optional[date], Optional[date]]:
        s = load_settings()
        f = str(s.get("auto_from", "")).strip()
        u = str(s.get("auto_until", "")).strip()
        return (date.fromisoformat(f) if f else None, date.fromisoformat(u) if u else None)

    def skipped_boards(self) -> set[int]:
        """settings.json 'skip_boards' — 자동 실행에서 뺄 폰 (예: 인터넷 안 되는 91번)."""
        return {int(n) for n in load_settings().get("skip_boards", [])}

    def in_window(self, d: date) -> bool:
        f, u = self.window()
        return (f is None or d >= f) and (u is None or d <= u)

    def planned(self, d: date) -> dict[str, str]:
        """{작업 이름: 'HH:MM'} — 그날 정해진 시작 시각."""
        return dict(self._plan.get("days", {}).get(d.isoformat(), {}).get("at", {}))

    def done_keys(self, d: date) -> dict[str, str]:
        return dict(self._plan.get("days", {}).get(d.isoformat(), {}).get("done", {}))

    def status(self) -> dict:
        f, u = self.window()
        today = date.today()
        return {"enabled": self.enabled,
                "from": f.isoformat() if f else None, "until": u.isoformat() if u else None,
                "today_in_window": self.in_window(today),
                "busy": {str(k): v for k, v in self.busy.items()},
                "planned": self.planned(today), "done": self.done_keys(today)}

    # -- 돌리기 ----------------------------------------------------------------------

    def start(self):
        if self._thread:
            return
        # 켜질 때 한 번: 재부팅·재실행을 알 수 있게
        notify.telegram_async(f"▶️ 대시보드 실행됨 — 자동 실행 {'켜짐' if self.enabled else '꺼짐'}")
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def run_now(self, key: str) -> str:
        """대시보드 '지금 실행'. 시간대·기간과 상관없이 바로 (폰이 쉬고 있을 때만)."""
        rows = self._load_rows(force=True)
        j = next((x for x in rows if job.key_of(x) == key), None)
        if not j:
            return "작업을 못 찾음"
        if j.board in self.busy:
            return f"{j.board}번이 이미 '{self.busy[j.board]}' 중"
        self._start_job(j, date.today(), manual=True)
        return "시작함"

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:                 # noqa: BLE001 — 한 번 실패해도 계속 돎
                self.log(f"!! 스케줄러 오류: {type(exc).__name__}: {exc}")
                traceback.print_exc()
            self._stop.wait(20)

    def _tick(self):
        now = datetime.now()
        self._heartbeat(now)
        if not self.enabled:
            return
        today = now.date()
        if not self.in_window(today):
            return
        rows = self._load_rows()
        jobs = schedule.jobs_on(rows, today) or []
        at = self._make_plan(today, jobs)
        done = self.done_keys(today)
        skip = self.skipped_boards()

        for j in jobs:
            k = job.key_of(j)
            if k in done or j.done_on(today):
                continue
            if j.board in skip:
                self._mark(today, k, "건너뜀(제외한 폰)")
                self.log(f"{j.board}번 {j.hour}시 작업 — 제외한 폰이라 건너뜀")
                continue
            start = datetime.combine(today, datetime.strptime(at[k], "%H:%M").time())
            if now.hour > j.hour:                    # 시간대가 지났으면 건너뜀 (재시도 없음)
                self._mark(today, k, "건너뜀(시간 지남)")
                self.log(f"{j.board}번 {j.hour}시 작업 — 시간이 지나 건너뜀")
                continue
            if now >= start and j.board not in self.busy:
                self._start_job(j, today)

        self._prepare(now, rows)

    # -- 작업 ------------------------------------------------------------------------

    def _start_job(self, j: schedule.Job, d: date, manual: bool = False):
        k = job.key_of(j)
        with self._lock:
            if j.board in self.busy:
                return
            self.busy[j.board] = "작업"
        if not manual:
            self._mark(d, k, "시작")
        self.on_change()

        where = f"{j.board}번 {j.week}주차 {j.day} {j.hour}시 (로테 {j.rotation}, {j.surgery})"

        def work():
            try:
                r = job.run_key(k, log=self.log)
                if not manual:
                    self._mark(d, k, "성공" if r.get("ok") else f"실패: {r.get('error', '')}")
                if not r.get("ok"):
                    notify.telegram_async(f"⚠️ 업로드 실패\n{where}\n이유: {r.get('error', '')}")
            except Exception as exc:                 # noqa: BLE001
                self.log(f"!! {j.board}번 작업 중 오류: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                if not manual:
                    self._mark(d, k, f"실패: {exc}")
                notify.telegram_async(f"⚠️ 작업 중 오류\n{where}\n{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self.busy.pop(j.board, None)
                self._rows_at = 0                    # 결과를 다시 읽게
                self.on_change()
        threading.Thread(target=work, daemon=True, name=f"job-{j.board}").start()

    # -- 미리 로그인 ------------------------------------------------------------------

    def _prepare(self, now: datetime, rows):
        """오늘·내일(기간 안) 남은 작업 중 폰별 가장 가까운 것의 계정으로 미리 로그인."""
        upcoming: dict[int, tuple[datetime, schedule.Job]] = {}
        for offset in (0, 1):
            d = now.date() + timedelta(days=offset)
            if not self.in_window(d):
                continue
            jobs = schedule.jobs_on(rows, d) or []
            at = self._make_plan(d, jobs)
            done = self.done_keys(d)
            skip = self.skipped_boards()
            for j in jobs:
                k = job.key_of(j)
                if k in done or j.done_on(d) or j.board in skip:
                    continue
                start = datetime.combine(d, datetime.strptime(at[k], "%H:%M").time())
                if start - now < PREP_LEAD:
                    continue
                if j.board not in upcoming or start < upcoming[j.board][0]:
                    upcoming[j.board] = (start, j)
        prepped = self._plan.setdefault("prepped", {})
        running = sum(1 for v in self.busy.values() if v == "미리 로그인")
        for no, (start, j) in sorted(upcoming.items(), key=lambda kv: kv[1][0]):
            tag = f"{start:%Y-%m-%d %H:%M}"
            if prepped.get(str(no)) == tag or no in self.busy or running >= MAX_PREP:
                continue
            running += 1
            self._start_prep(j, tag)

    def _start_prep(self, j: schedule.Job, tag: str):
        with self._lock:
            if j.board in self.busy:
                return
            self.busy[j.board] = "미리 로그인"
        self.on_change()

        def work():
            try:
                account = login.load_accounts(j.rotation).get(j.board)
                if not account:
                    return
                board = Board()
                devs = board.select([j.board])
                if not devs or login.offline(board, devs):
                    self.log(f"  {j.board}번 미리 로그인 건너뜀 (연결/인터넷 없음)")
                    return
                self.log(f"{j.board}번 미리 로그인 → 로테 {j.rotation} ({tag} 작업용)")
                r = login.switch(board, devs[0], account, log=self.log)
                if r.startswith(("ok", "skip")):
                    self._plan.setdefault("prepped", {})[str(j.board)] = tag
                    self._save()
                else:
                    self.log(f"  {j.board}번 미리 로그인 실패: {r} — 작업 시각에 다시 시도")
            except Exception as exc:                 # noqa: BLE001
                self.log(f"!! {j.board}번 미리 로그인 오류: {exc}")
            finally:
                with self._lock:
                    self.busy.pop(j.board, None)
                self.on_change()
        threading.Thread(target=work, daemon=True, name=f"prep-{j.board}").start()

    # -- 계획 / 기록 ------------------------------------------------------------------

    def _make_plan(self, d: date, jobs) -> dict[str, str]:
        day = self._plan.setdefault("days", {}).setdefault(d.isoformat(), {})
        at = day.setdefault("at", {})
        changed = False
        for j in jobs:
            k = job.key_of(j)
            # 없거나, 정해 둔 시각이 그 행 시간대와 다르면(배정이 바뀐 경우) 새로 정함
            if k not in at or not at[k].startswith(f"{j.hour:02d}:"):
                at[k] = f"{j.hour:02d}:{random.randint(0, MAX_MINUTE):02d}"
                changed = True
        # 시트에서 사라진 작업의 계획은 지움
        live = {job.key_of(j) for j in jobs}
        for k in [k for k in at if k not in live]:
            del at[k]
            changed = True
        if changed:
            self._save()
            self.log(f"{d:%m/%d} 시작 시각 정함: " + ", ".join(
                f"{j.board}번 {at[job.key_of(j)]}" for j in sorted(jobs, key=lambda x: at[job.key_of(x)])))
            self.on_change()
        return at

    def _mark(self, d: date, key: str, what: str):
        self._plan.setdefault("days", {}).setdefault(d.isoformat(), {}).setdefault("done", {})[key] = what
        self._save()

    def _heartbeat(self, now: datetime):
        if time.time() - self._beat_at < BEAT_EVERY:
            return
        self._beat_at = time.time()
        try:
            Sheet().write(schedule.TAB, BEAT_CELL, [[f"{now:%Y-%m-%d %H:%M}"]], text=True)
        except Exception as exc:                     # noqa: BLE001
            self.log(f"!! 생존 신호(M1) 기록 실패: {exc}")

    def _load_rows(self, force: bool = False):
        if force or not self._rows or time.time() - self._rows_at > SHEET_EVERY:
            self._rows = schedule.load_rows()
            self._rows_at = time.time()
        return self._rows

    def _load(self) -> dict:
        try:
            data = json.loads(PLAN.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        # 지난 날짜 기록은 7일만 남김
        cut = (date.today() - timedelta(days=7)).isoformat()
        data["days"] = {k: v for k, v in data.get("days", {}).items() if k >= cut}
        return data

    def _save(self):
        with self._lock:
            PLAN.write_text(json.dumps(self._plan, ensure_ascii=False, indent=1), encoding="utf-8")
