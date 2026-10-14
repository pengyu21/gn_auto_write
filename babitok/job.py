"""바비톡 한 건 실행: 앱 띄우기 → 이 계정의 지난 글 삭제 → 새 글 → 내가 쓴 글에서 확인 → 시트 J·K·L.

지난 글 = 이 폰이 시트에서 마지막으로 '성공' 한 줄의 제목과 **똑같은 제목**의 글.
계정이 원래 직접 쓴 글은 제목이 달라 건드리지 않습니다.
    * 삭제 중 오류(창이 안 뜸 등)  → 새 글 보류, '실패: 지난 글 삭제 실패 — …'
    * 목록에서 못 찾음(이미 지워짐) → 로그만 남기고 새 글 올림
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from core.board import ROOT, Board
from core.sheet import Sheet
from unni import login as unni_login
from . import schedule
from .app import App

STATE = ROOT / "babi_state.json"          # 폰보드 칸: 마지막 결과·닉네임 (공개 저장소 제외)
ACCOUNT_TAB = "바비톡아이디"               # 있으면 L열에 아이디, 없으면 닉네임
_STATE_LOCK = threading.Lock()


def load_state() -> dict[str, dict]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_state(no: int, entry: dict):
    with _STATE_LOCK:
        data = load_state()
        data[str(no)] = dict(entry, at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        try:
            STATE.write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: int(kv[0]))),
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass


def account_ids() -> dict[int, str]:
    """'바비톡아이디' 탭 {폰: 아이디}. 탭이 없거나 머리글을 못 찾으면 빈 dict."""
    try:
        v = Sheet().read(ACCOUNT_TAB)
    except Exception:                                  # noqa: BLE001
        return {}
    if not v:
        return {}
    h = [str(x).strip() for x in v[0]]
    try:
        bi = next(i for i, x in enumerate(h) if x in ("폰보드", "폰", "번호"))
        ii = next(i for i, x in enumerate(h) if "아이디" in x or x.upper() == "ID")
    except StopIteration:
        return {}
    out = {}
    for r in v[1:]:
        try:
            out[int(str(r[bi]).strip())] = str(r[ii]).strip()
        except (ValueError, IndexError):
            pass
    return out


def mark(sheet: Sheet, header, row: int, status: str):
    sheet.write(schedule.TAB, f"{schedule.col_letter(header, 'status')}{row}", [[status]], text=True)


def run_key(key: str, log=print) -> dict:
    sheet = Sheet()
    values = sheet.read(schedule.TAB)
    rows = schedule.load_rows(values=values)
    j = next((x for x in rows if schedule.key_of(x) == key), None)
    if not j:
        return {"ok": False, "error": f"작업을 못 찾음: {key}"}
    return run_row(j, rows, values[0], sheet, log)


def run_row(j: schedule.Job, rows, header, sheet: Sheet, log=print) -> dict:
    t0 = time.time()
    where = f"{j.board}번 {j.row}행 [{j.topic}] {j.title}"
    log(f"{where} 시작")
    mark(sheet, header, j.row, schedule.RUNNING)
    result = {"ok": False, "error": "", "nick": "", "deleted": ""}
    try:
        board = Board()
        devs = board.select([j.board])
        if not devs:
            raise _Fail("폰 연결 안 됨 (USB/adb)")
        dev = devs[0]
        if unni_login.offline(board, devs):
            raise _Fail("인터넷 연결 없음 — " + unni_login.net_reason(board, dev))
        app = App(board, dev, log=lambda m: log(m))
        app.launch()
        if not app.in_front():
            raise _Fail("바비톡 앱이 안 뜸")

        prev = schedule.previous_title(rows, j)
        if prev:
            r = app.delete_post(prev)
            if r == "ok":
                log(f"  {j.board}: 지난 글 삭제됨 — {prev}")
                result["deleted"] = prev
            elif r == "none":
                log(f"  {j.board}: 지난 글을 내가 쓴 글에서 못 찾음 (이미 지워졌을 수 있음) — {prev}")
            else:
                raise _Fail(f"지난 글 삭제 실패 — {r[5:].strip()} (새 글 보류)")
        else:
            log(f"  {j.board}: 지난 글 없음 (처음)")

        r = app.write(j.topic, j.title, j.text)
        if r != "ok":
            raise _Fail(r[5:].strip())
        log(f"  {j.board}: 글 올림")

        nick = ""
        if app.open_my_posts() == "ok":
            nick = _author(app, j.title, j.text)
        if not nick:
            log(f"  {j.board}: 내가 쓴 글 목록에서 방금 글 확인을 못 함 (올라간 창은 확인됨)")
        result.update(ok=True, nick=nick)
        acc = account_ids().get(j.board) or nick
        cols = [schedule.col_letter(header, k) for k in ("status", "uploaded", "account")]
        values = [schedule.SUCCESS, schedule.sheet_serial(datetime.now()), acc]
        if [ord(c) for c in cols] == list(range(ord(cols[0]), ord(cols[0]) + 3)):
            sheet.write(schedule.TAB, f"{cols[0]}{j.row}", [values])
        else:
            for c, v in zip(cols, values):
                sheet.write(schedule.TAB, f"{c}{j.row}", [[v]])
        note_state(j.board, {"state": "in", "nick": nick, "why": ""})
        log(f"완료: {where} ({time.time() - t0:.0f}초)")
        return result
    except _Fail as e:
        result["error"] = str(e)
    except Exception as e:                             # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    log(f"!! {where} 실패: {result['error']}")
    try:
        mark(sheet, header, j.row, f"{schedule.FAIL}: {result['error']}")
    except Exception as e:                             # noqa: BLE001
        log(f"!! 시트 기록 실패: {e}")
    why = result["error"]
    note_state(j.board, {"state": "out" if "로그인" in why else "unknown", "nick": "", "why": why})
    return result


class _Fail(Exception):
    pass


def _author(app: App, title: str, body: str) -> str:
    from core import screen
    texts = [n.get("text", "") for n in screen.nodes(app.dump()) if n.get("text")]
    if title not in texts:
        return ""
    i = texts.index(title)
    for t in texts[i + 1:i + 5]:
        if t and not t.isdigit() and "전" not in t and len(t) < 20 and not body.startswith(t[:8]):
            return t
    return ""


def check_login(no: int, log=print) -> dict:
    """로그인 점검: 커뮤니티 > 글쓰기 를 눌러 '게시판 선택' 이 뜨면 로그인됨. 창은 닫고 홈으로."""
    board = Board()
    devs = board.select([no])
    if not devs:
        return {"state": "gone", "nick": "", "why": "USB/adb 연결 끊김"}
    if unni_login.offline(board, devs):
        return {"state": "unknown", "nick": "", "why": "인터넷 안 됨 — " + unni_login.net_reason(board, devs[0])}
    app = App(board, devs[0], log=log)
    app.launch()
    if not app.in_front():
        return {"state": "unknown", "nick": "", "why": "바비톡 앱이 안 뜸"}
    if not app.tab("커뮤니티") or not app.tap_text("글쓰기", 3.0):
        return {"state": "unknown", "nick": "", "why": "커뮤니티 화면을 못 읽음"}
    xml = app.dump()
    ok = bool(app.find(xml, text="게시판 선택"))
    close = app.find(xml, desc="닫기")
    if close:
        app.tap(close, 1.5)
    else:
        board.key(4, devs)
    app.tab("홈")
    prev = load_state().get(str(no), {})
    return {"state": "in" if ok else "out", "nick": prev.get("nick", "") if ok else "",
            "why": "" if ok else "로그아웃 — 글쓰기에서 로그인 화면이 뜸"}
