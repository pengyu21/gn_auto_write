"""웹앱(구글 Apps Script) 연동 — PC 대시보드 값을 시트로 보내고, 웹앱 버튼 명령을 받아 실행.

    PC 대시보드 ──(바뀌면 1분마다, 적어도 5분마다)──▶ 시트 '강언대시보드' 탭 A열
    PC 대시보드 ◀──(30초마다 확인)───────────────── 시트 '강언대시보드명령' 탭

'강언대시보드' 탭: A1 = {"at": 보낸 시각, "n": 조각 수}, A2… = 대시보드 값(JSON)을 4만 자씩
나눈 조각 (시트 칸 한 개에 5만 자까지만 들어가서). 웹앱(appsscript/Dash.gs)이 이어 붙여 읽음.

'강언대시보드명령' 탭: A 시각 | B 명령 | C 인자 | D 보낸 사람 | E 처리
    auto on|off            자동 실행 켜기/끄기
    run_now <작업 이름>     지금 실행 (예: 3-월-17-76)
    check_login <폰,…>     로그인 점검
    reload                 시트 다시 읽기
10분 넘게 처리 안 된 명령은 '만료' 로 버림 — PC 가 꺼져 있던 사이의 '지금 실행' 이 늦게
실행되어 엉뚱한 때 글이 올라가지 않게.

탭이 없으면(웹앱 쪽 setupDash 를 아직 안 돌림) 조용히 기다립니다.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime

from core.sheet import Sheet

SNAP_TAB = "강언대시보드"
CMD_TAB = "강언대시보드명령"
CHUNK = 40000
PUSH_MIN = 60          # 바뀌었어도 이보다 자주는 안 보냄(초)
PUSH_MAX = 300         # 안 바뀌어도 이만큼 지나면 보냄(웹앱에서 'PC 살아 있음' 확인용)
CMD_EVERY = 30
CMD_EXPIRE_MIN = 10


class Remote:
    def __init__(self, api, log):
        self.api = api
        self.log = log
        self._last_hash = ""
        self._last_push = 0.0
        self._last_reload = time.time()
        self._warned = set()
        self._urgent = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="remote").start()

    def poke(self):
        """작업 시작/끝처럼 바로 알려야 할 때 — 다음 바퀴에 바로 보냄."""
        self._urgent.set()

    # -- 돌기 --------------------------------------------------------------------

    def _loop(self):
        time.sleep(15)
        while True:
            for step in (self._commands, self._push):
                try:
                    step()
                except Exception as exc:                 # noqa: BLE001 — 웹앱 연동 실패가 작업을 막으면 안 됨
                    key = f"{step.__name__}:{type(exc).__name__}:{str(exc)[:40]}"
                    if key not in self._warned:
                        self._warned.add(key)
                        self.log(f"!! 웹앱 연동 ({step.__name__}): {exc}")
            self._urgent.wait(CMD_EVERY)
            self._urgent.clear()

    def _push(self):
        if time.time() - self._last_reload > 300:          # 시트 내용도 5분마다 새로
            self.api.reload(quiet=True)
            self._last_reload = time.time()
        snap = self.api.snapshot()
        body = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
        h = hashlib.md5(body.encode()).hexdigest()
        since = time.time() - self._last_push
        if h == self._last_hash and since < PUSH_MAX:
            return
        if h != self._last_hash and since < PUSH_MIN and not self._urgent.is_set():
            return
        snap["sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
        chunks = [body[i:i + CHUNK] for i in range(0, len(body), CHUNK)]
        meta = json.dumps({"at": snap["sent_at"], "n": len(chunks), "size": len(body)})
        Sheet().write(SNAP_TAB, "A1", [[meta]] + [[c] for c in chunks], text=True)
        self._last_hash, self._last_push = h, time.time()

    def _commands(self):
        rows = Sheet().read(CMD_TAB)
        now = datetime.now()
        for i, r in enumerate(rows[1:], start=2):
            r = (r + [""] * 5)[:5]
            at, cmd, arg, who, done = (str(x).strip() for x in r)
            if not cmd or done:
                continue
            try:
                when = datetime.strptime(at[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                when = now
            if (now - when).total_seconds() > CMD_EXPIRE_MIN * 60:
                result = f"만료 (보낸 지 {CMD_EXPIRE_MIN}분 넘음 — 실행 안 함)"
            else:
                result = self._run(cmd, arg)
                self.log(f"웹앱 명령 [{cmd} {arg}] ({who or '?'}): {result}")
            Sheet().write(CMD_TAB, f"E{i}", [[f"{now:%H:%M:%S} {result}"]], text=True)
            self.poke()

    def _run(self, cmd: str, arg: str) -> str:
        if cmd == "auto":
            st = self.api.set_auto(arg == "on")
            return "자동 실행 " + ("켜짐" if st.get("enabled") else "꺼짐")
        if cmd == "run_now":
            return self.api.run_now(arg)
        if cmd == "check_login":
            nos = [int(x) for x in arg.replace(" ", "").split(",") if x.isdigit()]
            threading.Thread(target=self.api.check_login, args=(nos or None,), daemon=True).start()
            return f"로그인 점검 시작 ({len(nos) or 40}대)"
        if cmd == "reload":
            n = self.api.reload(quiet=True)
            return f"시트 다시 읽음 ({n}행)"
        # 바비톡 탭 버튼
        if cmd == "babi_auto":
            st = self.api.babi_set_auto(arg == "on")
            return "바비톡 자동 실행 " + ("켜짐" if st.get("enabled") else "꺼짐")
        if cmd == "babi_run_now":
            return self.api.babi_run_now(arg)
        if cmd == "babi_check_login":
            nos = [int(x) for x in arg.replace(" ", "").split(",") if x.isdigit()]
            threading.Thread(target=self.api.babi_check_login, args=(nos or None,), daemon=True).start()
            return f"바비톡 로그인 점검 시작 ({len(nos) or 40}대)"
        if cmd == "babi_reload":
            n = self.api.babi_reload(quiet=True)
            return f"바비톡 시트 다시 읽음 ({n}행)"
        return "모르는 명령"
