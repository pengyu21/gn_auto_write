"""강언 로테이션 대시보드 — 1단계: 일정 보기 + 로그인 점검.

    python dashboard.py

화면은 ui/dashboard.html (HTML), 이 파일은 그 화면에 데이터를 넣고 버튼 동작을
맡습니다. pywebview 가 윈도우 기본 엣지 엔진으로 일반 프로그램 창을 띄웁니다
(인터넷에 올리는 페이지가 아님).

    pip install pywebview

화면 -> 파이썬 호출 (Api 메서드, JS 에서 pywebview.api.<이름>):
    month(y, m)        그 달 날짜별 작업
    phones()           마지막 로그인 점검 결과 (login_state.json)
    reload()           시트 다시 읽기
    check_login(nos)   로그인 점검 — 진행 로그는 화면의 onLog() 로 흘려보냄

글쓰기·삭제·자동 실행은 아직 없습니다 (2·3단계).
"""
from __future__ import annotations

import calendar
import json
import re
import sys
import threading
import traceback
from datetime import date, datetime

import webview

from core.board import ROOT, load_settings
from unni import job, schedule
from unni.login import run_state
from unni.scheduler import Scheduler

UI = ROOT / "ui" / "dashboard.html"
STATE_FILE = ROOT / "login_state.json"
PHONES = list(range(60, 100))


def load_state() -> dict[int, dict]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[int, dict]):
    STATE_FILE.write_text(json.dumps({str(k): v for k, v in sorted(state.items())},
                                     ensure_ascii=False, indent=1), encoding="utf-8")


def steps_of(j: schedule.Job, state: str) -> list[dict]:
    """로그인 / 지난 글 삭제 / 새 글 업로드 세 단계. 2단계에서 I열에 단계별
    결과를 남기면 여기를 그 값으로 바꿉니다. 지금은 I·K·J 로 짐작합니다."""
    s = lambda k, st, n="": {"k": k, "s": st, "n": n}       # noqa: E731
    post = re.search(r"/community/(\d+)", j.url or "")
    if state in ("성공", "완료"):
        # 지난 글을 못 지우면 새 글을 올리지 않으므로, 성공이면 지난 글은 정리된 것.
        dele = s("지난 글 삭제", "ok", "지난 글 정리됨 (또는 없었음)")
        return [s("로그인", "ok", f"로테 {j.rotation} 계정"), dele,
                s("새 글 업로드", "ok", f"#{post.group(1)}" if post else "등록")]
    if state in ("실패", "보류"):
        if "지난 글 삭제 실패" in j.status:
            return [s("로그인", "ok"), s("지난 글 삭제", "fail", "삭제 실패"),
                    s("새 글 업로드", "hold", "지난 글이 남아 있어 보류")]
        why = j.status.split(":", 1)[1].strip() if ":" in j.status else j.status
        return [s("로그인", "fail", why), s("지난 글 삭제", "skip", "실행 안 함"),
                s("새 글 업로드", "skip", "실행 안 함")]
    if state == "작업중":
        return [s("로그인", "run"), s("지난 글 삭제", "wait"), s("새 글 업로드", "wait")]
    old = f"#{post.group(1)} 삭제 예정" if post else ""
    return [s("로그인", "wait"), s("지난 글 삭제", "wait", old), s("새 글 업로드", "wait")]


class Api:
    def __init__(self):
        self._window = None
        self._rows: list[schedule.Job] | None = None
        self._lock = threading.Lock()
        self._busy = False
        start = str(load_settings().get("rotation_start", "")).strip()
        self._start = date.fromisoformat(start) if start else None
        self._sched = Scheduler(log=self._log, on_change=self._changed)

    # -- 화면에서 부르는 것 --------------------------------------------------------

    def month(self, year: int, month: int) -> dict:
        rows = self._load()
        today = date.today()
        days = []
        for n in range(1, calendar.monthrange(year, month)[1] + 1):
            d = date(year, month, n)
            jobs = schedule.jobs_on(rows, d)
            plan = self._sched.planned(d)
            done = self._sched.done_keys(d)
            days.append({
                "day": n, "week": schedule.week_of(d), "dn": schedule.day_of(d),
                "skip": jobs is None,
                "jobs": [self._job(j, d, today, plan, done) for j in (jobs or [])],
            })
        return {"year": year, "month": month, "today": today.isoformat(),
                "start": self._start.isoformat() if self._start else None,
                "offset": schedule.first_offset(year, month), "days": days}

    def phones(self) -> dict:
        return {str(k): v for k, v in load_state().items()}

    def reload(self, quiet: bool = False) -> int:
        self._rows = schedule.load_rows()
        if not quiet:
            self._log(f"시트 '{schedule.TAB}' {len(self._rows)}행 읽음")
        return len(self._rows)

    def auto_status(self) -> dict:
        return self._sched.status()

    def set_auto(self, on: bool) -> dict:
        self._sched.set_enabled(bool(on))
        return self._sched.status()

    def run_now(self, key: str) -> str:
        r = self._sched.run_now(str(key))
        self._log(f"지금 실행 {key}: {r}")
        return r

    def check_login(self, panels) -> dict:
        nos = [int(n) for n in (panels or PHONES)]
        working = sorted(n for n in nos if n in self._sched.busy)
        if working:
            # 작업 중인 폰은 화면을 건드리면 안 됩니다.
            self._log(f"작업 중이라 점검에서 뺌: {working}")
            nos = [n for n in nos if n not in working]
            if not nos:
                return {"ok": False}
        with self._lock:
            if self._busy:
                self._log("다른 작업이 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
                return {"ok": False}
            self._busy = True
        try:
            self._log(f"로그인 점검 시작: {len(nos)}대 (홈 화면만 열어 확인합니다)")
            res = run_state(nos, log=self._log)
            at = datetime.now().strftime("%Y-%m-%d %H:%M")
            state = load_state()
            for no in nos:
                if no in res:
                    s, nick = res[no]
                    st = "in" if s is True else "out" if s is False else "unknown"
                else:
                    st, nick = "gone", ""
                state[no] = {"state": st, "nick": nick, "at": at}
            save_state(state)
            return {"ok": True}
        except Exception as exc:                       # noqa: BLE001 — 화면 로그로 보여 줌
            self._log(f"!! 로그인 점검 실패: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return {"ok": False}
        finally:
            self._busy = False

    # -- 내부 -------------------------------------------------------------------

    def _load(self) -> list[schedule.Job]:
        if self._rows is None:
            self.reload()
        return self._rows

    def _job(self, j: schedule.Job, d: date, today: date, plan=None, done=None) -> dict:
        key = job.key_of(j)
        state = j.state_on(d, today)
        if state == "미실행" and (self._start is None or d < self._start):
            state = "기록 없음"
        busy = self._sched.busy.get(j.board) if d == today else None
        if busy == "작업" and state in ("예정", "미실행"):
            state = "작업중"
        mark = (done or {}).get(key, "")
        excluded = j.board in self._sched.skipped_boards() or "제외" in mark
        skipped = mark.startswith("건너뜀")
        if excluded and state in ("예정", "미실행"):
            state = "제외"
        elif skipped and state in ("예정", "미실행"):
            state = "미실행"
        mine = j.done_on(d)
        t = schedule.parse_uploaded(j.uploaded)
        shown = f"{t:%Y-%m-%d} ({schedule.day_of(t.date())}) {t:%H:%M}" if t else j.uploaded
        return {"row": j.row, "hour": j.hour, "board": j.board, "rot": j.rotation,
                "surgery": j.surgery, "category": j.category, "state": state,
                "status": j.status, "deleted": j.deleted if mine else "",
                "uploaded": shown if mine else "", "url": j.url, "account": j.account,
                "text": j.text, "steps": steps_of(j, state),
                "key": key, "plan": (plan or {}).get(key, ""), "busy": busy or "",
                "note": "제외한 폰 (settings.json skip_boards)" if excluded
                        else "시간이 지나 건너뜀" if skipped else ""}

    def _changed(self):
        """스케줄러 상태가 바뀌면 화면에 알림 (작업 시작/끝, 미리 로그인)."""
        if self._window:
            try:
                self._window.evaluate_js("window.onAuto && onAuto()")
            except Exception:                          # noqa: BLE001
                pass

    def _log(self, line: str):
        # print 는 쓰지 않습니다 — run_state 가 print 를 이 함수로 돌려보내서 무한 반복됩니다.
        if sys.__stdout__:
            sys.__stdout__.write(f"{line}\n")
            sys.__stdout__.flush()
        if self._window:
            try:
                self._window.evaluate_js(f"window.onLog && onLog({json.dumps(str(line))})")
            except Exception:                          # noqa: BLE001 — 창이 닫히는 중
                pass


def _single_instance() -> bool:
    """대시보드는 한 개만. 두 개가 같이 돌면 같은 글이 두 번 올라갈 수 있습니다."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _single_instance.handle = k32.CreateMutexW(None, False, "Local\\gangeon_rotation_dashboard")
        if k32.GetLastError() == 183:                  # ERROR_ALREADY_EXISTS
            ctypes.windll.user32.MessageBoxW(None, "대시보드가 이미 실행 중입니다.\n작업 표시줄에서 기존 창을 찾아 주세요.",
                                             "강언 로테이션 대시보드", 0x40)
            return False
    except (AttributeError, OSError):
        pass
    return True


def main():
    if not UI.is_file():
        raise SystemExit(f"화면 파일이 없습니다: {UI}")
    if not _single_instance():
        return
    api = Api()
    # 글 주소(target=_blank)는 대시보드 창이 아니라 PC 기본 브라우저로 엽니다.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window("강언 로테이션 대시보드", url=str(UI), js_api=api,
                                   width=1440, height=900, min_size=(1100, 720),
                                   maximized=True, background_color="#EDF1F0")
    api._window = window
    api._sched.start()            # 꺼져 있으면 생존 신호(M1)만 적고 작업은 안 함
    webview.start()


if __name__ == "__main__":
    main()
