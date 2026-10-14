"""강언/바비톡 로테이션 대시보드 — 일정 보기, 로그인 점검, 자동 실행 (앱별 탭).

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
from collections import deque
import re
import sys
import threading
import traceback
from datetime import date, datetime

import webview

from core.board import ROOT, load_settings
from core.board import Board
from unni import job, login, schedule
from unni.login import run_state
from unni.remote import Remote
from unni.scheduler import Scheduler
from babitok import job as bjob, schedule as bschedule
from babitok.scheduler import BabiScheduler
from version import VERSION

UI = ROOT / "ui" / "dashboard.html"
STATE_FILE = ROOT / "login_state.json"
LOG_FILE = ROOT / "dashboard.log"          # 전체 로그 (공개 저장소 제외). 화면에는 최근 300줄만
LOG_BUFFER: deque = deque(maxlen=300)
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


def _tag(why: str) -> str:
    """긴 이유 -> 폰보드 칸에 들어갈 짧은 말."""
    for key, short in (("비밀번호 불일치", "비번 불일치"), ("로그인 화면에 머묾", "로그인 막힘"),
                       ("VPN", "VPN 문제"), ("경로 없음", "인터넷 없음"), ("Wi-Fi 연결 안 됨", "Wi-Fi 끊김"),
                       ("비행기", "비행기 모드"), ("바깥 접속", "인터넷 안 됨"), ("USB", "USB 끊김"),
                       ("못 읽음", "화면 못 읽음"), ("로그아웃 상태", "로그아웃")):
        if key in why:
            return short
    return "확인 필요" if why else ""


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


def babi_steps(j: bschedule.Job, state: str) -> list[dict]:
    """바비톡 세 단계: 로그인 확인 / 지난 글 삭제 / 새 글 업로드."""
    s = lambda k, st, n="": {"k": k, "s": st, "n": n}       # noqa: E731
    if state in ("성공", "완료"):
        return [s("로그인 확인", "ok"), s("지난 글 삭제", "ok", "지난 글 정리됨 (또는 없었음)"),
                s("새 글 업로드", "ok", "등록")]
    if state in ("실패", "보류"):
        why = j.status.split(":", 1)[1].strip() if ":" in j.status else j.status
        if "지난 글 삭제" in j.status:
            return [s("로그인 확인", "ok"), s("지난 글 삭제", "fail", why),
                    s("새 글 업로드", "hold", "지난 글이 남아 있어 보류")]
        if "로그인" in why or "게시판 선택" in why:
            return [s("로그인 확인", "fail", why), s("지난 글 삭제", "skip"), s("새 글 업로드", "skip")]
        return [s("로그인 확인", "ok"), s("지난 글 삭제", "ok"), s("새 글 업로드", "fail", why)]
    if state == "작업중":
        return [s("로그인 확인", "run"), s("지난 글 삭제", "wait"), s("새 글 업로드", "wait")]
    return [s("로그인 확인", "wait"), s("지난 글 삭제", "wait"), s("새 글 업로드", "wait")]


class Api:
    def __init__(self):
        self._window = None
        self._rows: list[schedule.Job] | None = None
        self._lock = threading.Lock()
        self._busy = False
        start = str(load_settings().get("rotation_start", "")).strip()
        self._start = date.fromisoformat(start) if start else None
        self._sched = Scheduler(log=self._log, on_change=self._changed)
        # 바비톡: 같은 폰보드를 쓰므로 두 스케줄러가 서로의 작업 중인 폰을 기다림
        self._brows: list[bschedule.Job] | None = None
        self._bbusy = False
        self._bsched = BabiScheduler(log=self._blog, on_change=self._changed, other=self._sched)
        self._sched.other = self._bsched

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

    def version(self) -> str:
        return VERSION

    def phones(self) -> dict:
        # 작업 중 로그인(unni/login._record_state)이 남긴 칸엔 짧은 말이 없어 여기서 붙임
        return {str(k): dict(v, tag=v.get("tag") or _tag(v.get("why", ""))) for k, v in load_state().items()}

    def reload(self, quiet: bool = False) -> int:
        self._rows = schedule.load_rows()
        sched = getattr(self, "_sched", None)
        if sched:
            sched.invalidate()                         # 스케줄러도 바뀐 시간대로 예정 시각을 다시 정하게
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
        working = sorted(n for n in nos if self._sched.occupied(n))
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
            self._explain(state, [n for n in nos if state[n]["state"] != "in"])
            save_state(state)
            self._changed()                            # 화면(PC·웹) 폰보드 바로 다시 그림
            bad = [n for n in nos if state[n]["state"] != "in"]
            for n in bad:
                self._log(f"  {n}번 {state[n].get('tag', '')}: {state[n].get('why', '')}")
            return {"ok": True}
        except Exception as exc:                       # noqa: BLE001 — 화면 로그로 보여 줌
            self._log(f"!! 로그인 점검 실패: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return {"ok": False}
        finally:
            self._busy = False

    # -- 내부 -------------------------------------------------------------------

    def _explain(self, state: dict, nos: list[int]):
        """로그인 안 된 폰마다 '왜' 를 붙입니다: why(긴 설명) + tag(칸에 보일 짧은 말)."""
        if not nos:
            return
        attempts = login.last_attempts()
        try:
            board = Board()
            devs = {d.no: d for d in board.select(nos)}
        except Exception:                              # noqa: BLE001
            board, devs = None, {}
        for no in nos:
            st = state[no]["state"]
            why = ""
            if st == "gone" or no not in devs:
                why = "USB/adb 연결 끊김 — 폰보드 연결·전원 확인"
            else:
                dev = devs[no]
                try:
                    off = bool(login.offline(board, [dev]))
                    if off:
                        why = "인터넷 안 됨 — " + login.net_reason(board, dev)
                except Exception:                      # noqa: BLE001
                    pass
                if not why:
                    last = attempts.get(str(no))
                    if st == "unknown":
                        why = "홈 화면을 못 읽음 — 크롬이 다른 창에 가려졌거나 멈춤 (화면 확인)"
                    elif last and str(last.get("result", "")).startswith("fail"):
                        why = (f"마지막 로그인 실패: {last['result'][5:].strip()} "
                               f"({last.get('at', '')}, {last.get('account', '')})")
                    else:
                        why = "로그아웃 상태 — 다음 작업 때 그 차례 계정으로 자동 로그인"
            state[no]["why"] = why
            state[no]["tag"] = _tag(why)

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
        excluded = self._sched.is_skipped(j) or "제외" in mark
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
                "note": "제외 (settings.json skip_boards / skip_accounts)" if excluded
                        else "시간이 지나 건너뜀" if skipped else ""}

    # -- 바비톡 (화면에서 babi_* 로 부름) -------------------------------------------------

    def babi_month(self, year: int, month: int) -> dict:
        rows = self._bload()
        today = date.today()
        days = []
        for n in range(1, calendar.monthrange(year, month)[1] + 1):
            d = date(year, month, n)
            jobs = bschedule.jobs_on(rows, d)
            plan, done = self._bsched.planned(d), self._bsched.done_keys(d)
            days.append({"day": n, "week": bschedule.week_of(d), "dn": bschedule.day_of(d),
                         "skip": jobs is None,
                         "jobs": [self._bjob(j, d, today, plan, done) for j in (jobs or [])]})
        return {"year": year, "month": month, "today": today.isoformat(),
                "parity": bschedule.parity_of(date(year, month, 1)),
                "offset": bschedule.first_offset(year, month), "days": days}

    def babi_phones(self) -> dict:
        return {k: dict(v, tag=v.get("tag") or _tag(v.get("why", ""))) for k, v in bjob.load_state().items()}

    def babi_reload(self, quiet: bool = False) -> int:
        self._brows = bschedule.load_rows()
        self._bsched.invalidate()
        if not quiet:
            self._blog(f"시트 '{bschedule.TAB}' {len(self._brows)}행 읽음")
        return len(self._brows)

    def babi_auto_status(self) -> dict:
        return self._bsched.status()

    def babi_set_auto(self, on: bool) -> dict:
        self._bsched.set_enabled(bool(on))
        return self._bsched.status()

    def babi_run_now(self, key: str) -> str:
        r = self._bsched.run_now(str(key))
        self._blog(f"지금 실행 {key}: {r}")
        return r

    def babi_check_login(self, panels) -> dict:
        """바비톡 로그인 점검 — 폰마다 커뮤니티 > 글쓰기 를 눌러 봄. 작업 중인 폰은 뺌. 동시에 8대."""
        nos = [int(n) for n in (panels or PHONES)]
        with self._lock:
            if self._bbusy:
                self._blog("로그인 점검이 이미 진행 중입니다.")
                return {"ok": False}
            self._bbusy = True
        try:
            held = [n for n in nos if self._bsched.hold(n, "점검")]
            skipped = sorted(set(nos) - set(held))
            if skipped:
                self._blog(f"작업 중이라 점검에서 뺌: {skipped}")
            self._blog(f"로그인 점검 시작: {len(held)}대")
            self._changed()
            sem = threading.Semaphore(8)

            def one(no):
                with sem:
                    try:
                        r = bjob.check_login(no, log=lambda m: None)
                    except Exception as exc:           # noqa: BLE001
                        r = {"state": "unknown", "nick": "", "why": f"{type(exc).__name__}: {exc}"}
                    finally:
                        self._bsched.release(no)
                    bjob.note_state(no, r)
                    self._blog(f"  {no}: " + ("로그인됨" if r["state"] == "in" else f"{r['state']} — {r['why']}"))
            ts = [threading.Thread(target=one, args=(n,), daemon=True) for n in held]
            for th in ts:
                th.start()
            for th in ts:
                th.join()
            st = bjob.load_state()
            bad = [n for n in held if st.get(str(n), {}).get("state") != "in"]
            self._blog(f"로그인 점검 끝: 로그인됨 {len(held) - len(bad)}대" + (f", 안 됨 {bad}" if bad else ""))
            self._changed()
            return {"ok": True}
        finally:
            self._bbusy = False

    def _bload(self) -> list[bschedule.Job]:
        if self._brows is None:
            self.babi_reload(quiet=True)
        return self._brows

    def _bjob(self, j: bschedule.Job, d: date, today: date, plan=None, done=None) -> dict:
        key = bschedule.key_of(j)
        state = j.state_on(d, today)
        busy = self._bsched.busy.get(j.board) if d == today else None
        if busy == "작업" and state in ("예정", "미실행"):
            state = "작업중"
        mark = (done or {}).get(key, "")
        skipped = mark.startswith("건너뜀")
        excluded = self._bsched.is_skipped(j)
        if state == "예정" and d == today and datetime.now().hour > j.hour:
            state, skipped = "미실행", True             # 자동 실행이 꺼져 있어도 지난 시간대는 지난 것으로
        if excluded and state in ("예정", "미실행"):
            state = "제외"
        elif skipped and state in ("예정", "미실행"):
            state = "미실행"
        mine = j.done_on(d)
        t = bschedule.parse_uploaded(j.uploaded)
        shown = f"{t:%Y-%m-%d} ({bschedule.day_of(t.date())}) {t:%H:%M}" if t else j.uploaded
        return {"row": j.row, "hour": j.hour, "board": j.board, "parity": j.parity, "surgery": j.surgery,
                "topic": j.topic, "title": j.title, "state": state, "status": j.status,
                "uploaded": shown if mine else "", "account": j.account if mine else "", "text": j.text,
                "steps": babi_steps(j, state), "key": key, "plan": (plan or {}).get(key, ""),
                "busy": busy or "",
                "note": "제외 (settings.json babi_skip_boards)" if excluded
                        else "시간이 지나 건너뜀" if skipped else ""}

    def _blog(self, line: str):
        self._log(f"[바비톡] {str(line).lstrip()}")

    def _changed(self):
        """스케줄러 상태가 바뀌면 화면에 알림 (작업 시작/끝, 미리 로그인). 웹앱에도 바로 보냄."""
        remote = getattr(self, "_remote", None)
        if remote:
            remote.poke()
        if self._window:
            try:
                self._window.evaluate_js("window.onAuto && onAuto()")
            except Exception:                          # noqa: BLE001
                pass

    def logs(self) -> list:
        """최근 로그 [(시각, 줄)…] — 화면이 처음 뜰 때 불러감."""
        return list(LOG_BUFFER)

    def snapshot(self) -> dict:
        """웹앱(시트)으로 보낼 지금 대시보드 값 — 화면이 쓰는 것과 똑같은 데이터.
        지난달·이번 달·다음 달 달력, 폰 상태, 자동 실행 상태, 최근 로그."""
        t = date.today()
        months, texts = {}, {}
        for k in (-1, 0, 1):
            y, m = t.year, t.month + k
            y, m = (y - 1, 12) if m < 1 else (y + 1, 1) if m > 12 else (y, m)
            mm = self.month(y, m)
            for dd in mm["days"]:                       # 같은 글이 달마다 반복되므로 글은 따로 한 번만
                for idx, j in enumerate(dd["jobs"]):
                    texts[j["key"]] = j.pop("text", "")
                    # 크기 줄이기: 빈 값은 빼고, 단계 이름(로그인/지난 글 삭제/새 글 업로드)은 웹앱이 채움
                    j["steps"] = [[s["s"], s["n"]] if s["n"] else [s["s"]] for s in j["steps"]]
                    dd["jobs"][idx] = {k: v for k, v in j.items() if v not in ("", None)}
            months[f"{y}-{m}"] = mm
        bmonths = {}
        for k in (-1, 0, 1):
            y, m = t.year, t.month + k
            y, m = (y - 1, 12) if m < 1 else (y + 1, 1) if m > 12 else (y, m)
            mm = self.babi_month(y, m)
            for dd in mm["days"]:
                for idx, j in enumerate(dd["jobs"]):
                    texts[j["key"]] = j.pop("text", "")
                    j["steps"] = [[s["s"], s["n"]] if s["n"] else [s["s"]] for s in j["steps"]]
                    dd["jobs"][idx] = {k: v for k, v in j.items() if v not in ("", None)}
            bmonths[f"{y}-{m}"] = mm
        return {"version": VERSION, "today": t.isoformat(), "months": months, "texts": texts,
                "phones": self.phones(), "auto": self._sched.status(),
                "babi": {"months": bmonths, "phones": self.babi_phones(), "auto": self._bsched.status()},
                "logs": list(LOG_BUFFER)[-150:]}

    def _log(self, line: str):
        # print 는 쓰지 않습니다 — run_state 가 print 를 이 함수로 돌려보내서 무한 반복됩니다.
        if sys.__stdout__:
            sys.__stdout__.write(f"{line}\n")
            sys.__stdout__.flush()
        at = datetime.now().strftime("%H:%M:%S")
        LOG_BUFFER.append((at, str(line)))
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:      # 파일에도 남김 (화면과 별개로 보관)
                fh.write(f"{datetime.now():%Y-%m-%d} {at}  {line}\n")
        except OSError:
            pass
        if self._window:
            try:
                self._window.evaluate_js(f"window.onLog && onLog({json.dumps(str(line))}, {json.dumps(at)})")
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
                                             "강언/바비톡 로테이션 대시보드", 0x40)
            return False
    except (AttributeError, OSError):
        pass
    return True


def main():
    if not UI.is_file():
        raise SystemExit(f"화면 파일이 없습니다: {UI}")
    if not _single_instance():
        return
    try:
        # 작업 표시줄에서 '파이썬' 이 아니라 이 프로그램으로 따로 묶이고, 창 아이콘(ui/dashboard.ico)이 보이게
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gangeon.babitalk.dashboard")
    except (AttributeError, OSError):
        pass
    api = Api()
    # 글 주소(target=_blank)는 대시보드 창이 아니라 PC 기본 브라우저로 엽니다.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window("강언/바비톡 로테이션 대시보드", url=str(UI), js_api=api,
                                   width=1440, height=900, min_size=(1100, 720),
                                   maximized=True, background_color="#EDF1F0")
    api._window = window
    api._sched.start()            # 꺼져 있으면 생존 신호(M1)만 적고 작업은 안 함
    api._bsched.start()           # 바비톡도 같은 방식 (처음엔 꺼짐)
    api._remote = Remote(api, api._log)
    api._remote.start()           # 웹앱 연동: 값 보내기 + 웹앱 명령 받기
    icon = ROOT / "ui" / "dashboard.ico"         # 바로가기 3개(바탕화면·시작 프로그램·폴더)도 같은 파일
    webview.start(icon=str(icon) if icon.is_file() else None)


if __name__ == "__main__":
    main()
