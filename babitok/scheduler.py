"""바비톡 자동 실행 — 강남언니 스케줄러(unni/scheduler.py)와 같은 규칙, 같은 폰보드.

    * 오늘 날짜의 이번 달(홀/짝) 줄만. 'NN시' 줄은 그 시간 0~40분 사이 무작위 시각에 시작.
      시간대가 지난 줄은 다시 시도하지 않고 건너뜀. 정한 시각은 run_plan_babi.json 에 보관.
    * 같은 폰을 강남언니 작업이 쓰고 있으면 끝날 때까지 기다림 (other.busy) — 강남언니 쪽도
      바비톡이 쓰는 폰은 기다림. 폰마다 한 번에 하나.
    * 5분마다 시트 '바비톡게시글로테이션' M1 에 생존 신호.
    * 처음 켜면 자동 실행은 꺼진 상태 — 대시보드 바비톡 탭에서 켬.
"""
from __future__ import annotations

import json
import random
import threading
import time
import traceback
from datetime import date, datetime
from typing import Callable, Optional

from core.board import ROOT, load_settings
from core.sheet import Sheet
from unni import notify
from . import job, schedule

PLAN = ROOT / "run_plan_babi.json"
MAX_MINUTE = 40
BEAT_EVERY = 300
SHEET_EVERY = 600
BEAT_CELL = "M1"


class BabiScheduler:
    def __init__(self, log: Callable[[str], None] = print, on_change: Callable[[], None] = lambda: None,
                 other=None):
        self.log = log
        self.on_change = on_change
        self.other = other                       # 강남언니 Scheduler (같은 폰 겹침 방지)
        self.busy: dict[int, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rows: list[schedule.Job] = []
        self._header: list[str] = []
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

    def window(self):
        s = load_settings()
        f = str(s.get("babi_auto_from", "")).strip()
        u = str(s.get("babi_auto_until", "")).strip()
        return (date.fromisoformat(f) if f else None, date.fromisoformat(u) if u else None)

    def in_window(self, d: date) -> bool:
        f, u = self.window()
        return (f is None or d >= f) and (u is None or d <= u)

    def skipped_boards(self) -> set[int]:
        return {int(n) for n in load_settings().get("babi_skip_boards", [])}

    def is_skipped(self, j) -> bool:
        return j.board in self.skipped_boards()

    def occupied(self, no: int) -> bool:
        return no in self.busy or bool(self.other and no in self.other.busy)

    def planned(self, d: date) -> dict[str, str]:
        return dict(self._plan.get("days", {}).get(d.isoformat(), {}).get("at", {}))

    def done_keys(self, d: date) -> dict[str, str]:
        return dict(self._plan.get("days", {}).get(d.isoformat(), {}).get("done", {}))

    def status(self) -> dict:
        f, u = self.window()
        today = date.today()
        return {"enabled": self.enabled, "from": f.isoformat() if f else None,
                "until": u.isoformat() if u else None, "today_in_window": self.in_window(today),
                "busy": {str(k): v for k, v in self.busy.items()},
                "planned": self.planned(today), "done": self.done_keys(today),
                "parity": schedule.parity_of(today), "count": self._count(today)}

    def _count(self, d: date) -> int:
        """오늘 건수 (탭 옆 숫자) — 자동 실행이 꺼져 있어도 시트 기준으로."""
        try:
            return len(schedule.jobs_on(self.rows(), d) or [])
        except Exception:                            # noqa: BLE001
            return 0

    def invalidate(self):
        self._rows_at = 0

    # -- 돌리기 ----------------------------------------------------------------------
    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="babi-scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def run_now(self, key: str) -> str:
        rows = self.rows(force=True)
        j = next((x for x in rows if schedule.key_of(x) == key), None)
        if not j:
            return "작업을 못 찾음"
        if self.occupied(j.board):
            return f"{j.board}번이 다른 작업 중"
        self._start_job(j, date.today(), manual=True)
        return "시작함"

    def hold(self, no: int, what: str) -> bool:
        """로그인 점검처럼 화면을 쓰는 일을 할 때 폰을 잡아 둠."""
        with self._lock:
            if self.occupied(no):
                return False
            self.busy[no] = what
        return True

    def release(self, no: int):
        with self._lock:
            self.busy.pop(no, None)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:                 # noqa: BLE001
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
        jobs = schedule.jobs_on(self.rows(), today) or []
        at = self._make_plan(today, jobs)
        done = self.done_keys(today)
        for j in jobs:
            k = schedule.key_of(j)
            if k in done or j.done_on(today):
                continue
            if j.status.startswith(schedule.RUNNING) and j.board not in self.busy:
                continue
            if self.is_skipped(j):
                self._mark(today, k, "건너뜀(제외)")
                continue
            start = datetime.combine(today, datetime.strptime(at[k], "%H:%M").time())
            if now.hour > j.hour:
                self._mark(today, k, "건너뜀(시간 지남)")
                self.log(f"{j.board}번 {j.hour}시 작업 — 시간이 지나 건너뜀")
                try:
                    job.mark(Sheet(), self._header, j.row,
                             "건너뜀: 시간 지남 (그 시간에 프로그램이 꺼져 있었거나 폰이 다른 작업 중)")
                except Exception:                    # noqa: BLE001
                    pass
                continue
            if now >= start and not self.occupied(j.board):
                self._start_job(j, today)

    def _start_job(self, j, d: date, manual: bool = False):
        k = schedule.key_of(j)
        with self._lock:
            if self.occupied(j.board):
                return
            self.busy[j.board] = "작업"
        if not manual:
            self._mark(d, k, "시작")
        self.on_change()
        where = f"{d:%m/%d}({schedule.day_of(d)}) {j.board}번 {j.parity} {j.week}주차 {j.day} {j.hour}시 · {j.surgery} [{j.topic}]"

        def work():
            try:
                r = job.run_key(k, log=self.log)
                if not manual:
                    self._mark(d, k, "성공" if r.get("ok") else f"실패: {r.get('error', '')}")
                if r.get("ok"):
                    self._notify_success(j, d, r)
                else:
                    notify.both_async("⚠️ 바비톡 업로드 실패", f"{where}\n이유: {r.get('error', '')}")
            except Exception as exc:                 # noqa: BLE001
                self.log(f"!! {j.board}번 작업 중 오류: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                if not manual:
                    self._mark(d, k, f"실패: {exc}")
                notify.both_async("⚠️ 바비톡 작업 중 오류", f"{where}\n{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self.busy.pop(j.board, None)
                self._rows_at = 0
                self.on_change()
        threading.Thread(target=work, daemon=True, name=f"babi-{j.board}").start()

    def _notify_success(self, j, d: date, r: dict):
        try:
            today = schedule.jobs_on(self.rows(force=True), d) or []
            total, nth = len(today), sum(1 for x in today if x.done_on(d))
        except Exception:                            # noqa: BLE001
            total, nth = 0, 0
        title = f"✅ 바비톡 업로드 완료 — 오늘 {total}건 중 {nth}번째" if total else "✅ 바비톡 업로드 완료"
        body = (f"{d:%m/%d}({schedule.day_of(d)}) {j.parity} {j.week}주차 {j.day} {j.hour}시 · {datetime.now():%H:%M} 업로드\n"
                f"{j.board}번 · {j.surgery} [{j.topic}]\n제목: {j.title}\n"
                f"계정: {r.get('nick', '')}" + (f"\n지난 글 삭제: {r['deleted']}" if r.get("deleted") else ""))
        notify.both_async(title, body)

    # -- 계획·기록 ----------------------------------------------------------------------
    def rows(self, force: bool = False):
        if force or not self._rows or time.time() - self._rows_at > SHEET_EVERY:
            v = Sheet().read(schedule.TAB)
            self._header = v[0] if v else []
            self._rows = schedule.load_rows(values=v)
            self._rows_at = time.time()
        return self._rows

    def _make_plan(self, d: date, jobs) -> dict[str, str]:
        day = self._plan.setdefault("days", {}).setdefault(d.isoformat(), {})
        at = day.setdefault("at", {})
        changed = False
        for j in jobs:
            k = schedule.key_of(j)
            if k not in at or not at[k].startswith(f"{j.hour:02d}:"):
                at[k] = f"{j.hour:02d}:{random.randint(0, MAX_MINUTE):02d}"
                changed = True
        live = {schedule.key_of(j) for j in jobs}
        for k in [k for k in at if k not in live]:
            del at[k]
            changed = True
        if changed:
            self._save()
            self.log(f"{d:%m/%d} 시작 시각 정함: " + ", ".join(
                f"{j.board}번 {at[schedule.key_of(j)]}" for j in sorted(jobs, key=lambda x: at[schedule.key_of(x)])))
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

    def _load(self) -> dict:
        try:
            p = json.loads(PLAN.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            p = {"enabled": False, "days": {}}
        keep = sorted(p.get("days", {}))[-14:]
        p["days"] = {k: p["days"][k] for k in keep}
        return p

    def _save(self):
        try:
            PLAN.write_text(json.dumps(self._plan, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
