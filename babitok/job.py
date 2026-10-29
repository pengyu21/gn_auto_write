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
from . import schedule, site as app_site
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


def accounts() -> dict[int, dict]:
    """'바비톡아이디' 탭 {폰: {"id","pw","naver","verified"}}. 열은 머리글 이름으로 찾음.
    2026-10-29 시트: No | 폰보드 번호('폰보드60') | 아이디 | 비번 | 비고 | 네이버 여부(O) | 인증 여부.
    (예전 시트처럼 폰 번호가 비고에 '폰보드60 …' 으로 있어도 읽음)"""
    import re
    try:
        v = Sheet().read(ACCOUNT_TAB)
    except Exception:                                  # noqa: BLE001
        return {}
    if not v:
        return {}
    h = [str(x).strip() for x in v[0]]
    col = lambda test, default=None: next((i for i, x in enumerate(h) if test(x)), default)   # noqa: E731
    ii = col(lambda x: x == "아이디" or x.upper() == "ID", 1)
    pi = col(lambda x: x in ("비번", "비밀번호"), 2)
    phone_cols = [i for i in (col(lambda x: "폰보드" in x), col(lambda x: x == "비고")) if i is not None]
    nv = col(lambda x: "네이버" in x)
    vi = col(lambda x: "인증" in x)
    out = {}
    for r in v[1:]:
        r = list(r) + [""] * (len(h) + 1)
        m = None
        for c in phone_cols:
            m = re.search(r"폰보드\s*(\d+)", str(r[c])) or re.fullmatch(r"\s*(\d+)\s*", str(r[c]))
            if m:
                break
        if m and str(r[ii]).strip():
            out[int(m.group(1))] = {
                "id": str(r[ii]).strip(), "pw": str(r[pi]).strip(),
                "naver": nv is not None and str(r[nv]).strip().upper() in ("O", "○", "Y", "예", "네이버"),
                "verified": str(r[vi]).strip() if vi is not None else "",
            }
    return out


def account_ids() -> dict[int, str]:
    """{폰: 아이디} — 시트 업로드 계정(L열) 기록용."""
    return {k: v["id"] for k, v in accounts().items()}


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

        # 지난 글을 지우기 전에, 이 계정이 지금 글을 쓸 수 있는지(본인인증 창이 안 뜨는지) 먼저 확인
        r = app.can_write()
        if r == "verify":
            raise _Verify()
        if r != "ok":
            raise _Fail(r[5:].strip())

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

        # 이미 올라간 줄을 '지금 실행' 으로 다시 하면 같은 제목 글이 두 개가 됨 → 먼저 올린 같은 글을 지움 (2026-10-20 69번)
        last = schedule.parse_uploaded(j.uploaded)      # 같은 줄은 다음 달에 또 돌아오니, 이번 차례(6일 안) 기록만
        if last and (datetime.now() - last).days < 6:
            r = app.delete_post(j.title)
            if r == "ok":
                log(f"  {j.board}: 이 줄을 다시 올리는 거라 먼저 올린 같은 글 삭제 — {j.title}")
                result["deleted"] = (result["deleted"] + ", " if result["deleted"] else "") + j.title
            elif r == "none":
                log(f"  {j.board}: 먼저 올린 같은 글은 목록에 없음 — {j.title}")
            else:
                raise _Fail(f"먼저 올린 같은 글 삭제 실패 — {r[5:].strip()} (새 글 보류)")

        r = app.write(j.topic, j.title, j.text)
        if r == "verify":
            raise _Verify()
        if r != "ok":
            raise _Fail(r[5:].strip())
        result["posted"] = True                         # 여기부터 실패해도 다시 하지 않음 (같은 글 두 번 방지)
        log(f"  {j.board}: 글 올림")

        nick = ""
        if app.open_my_posts() == "ok":
            nick = _author(app, j.title, j.text)
        if not nick:
            log(f"  {j.board}: 내가 쓴 글 목록에서 방금 글 확인을 못 함 (올라간 창은 확인됨)")
        result.update(ok=True, nick=nick)
        # 업로드 계정 칸: '닉네임 / 아이디' — 어느 계정으로 올라갔는지 검수하기 쉽게 (2026-10-20 요청)
        nick_shown = nick or load_state().get(str(j.board), {}).get("nick", "")
        acc = " / ".join(x for x in (nick_shown, account_ids().get(j.board, "")) if x)
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
    except _Verify:
        # 휴대폰 본인 인증 창 — 자동으로는 못 넘김. 건너뛰고 기록만 (2026-10-15 83번)
        why = "본인인증 필요 (휴대폰 본인 인증 창이 뜸 — 그 폰에서 직접 인증해야 함)"
        log(f"!! {where} 건너뜀: {why}")
        result.update(skipped=True, error=why)
        try:
            mark(sheet, header, j.row, f"{SKIP_VERIFY}: {why}")
        except Exception as e:                         # noqa: BLE001
            log(f"!! 시트 기록 실패: {e}")
        note_state(j.board, {"state": "out", "nick": "", "why": why, "tag": "본인인증 필요"})
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


class _Verify(Exception):
    """본인인증 창 — 실패가 아니라 건너뜀."""


SKIP_VERIFY = "건너뜀"                    # 시트 작업 여부: '건너뜀: 본인인증 필요 (…)'


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
    """로그인 점검: 커뮤니티 > 글쓰기 > 성형 까지 들어가 제목·내용 칸이 보이면 글쓰기 가능. 아무것도 안 쓰고 나옴."""
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
    r = app.open_write()                                # 팝업은 닫으면서 커뮤니티 > 글쓰기
    prev = load_state().get(str(no), {})
    if r == "verify":
        app.tab("홈")
        return {"state": "out", "nick": prev.get("nick", ""), "tag": "본인인증 필요",
                "why": "본인인증 필요 — 글쓰기를 누르면 휴대폰 본인 인증 창이 뜸 (그 폰에서 직접 인증)"}
    if r.startswith("fail: 게시판"):
        board.key(4, devs)
        app.tab("홈")
        return {"state": "out", "nick": "", "why": "로그아웃 — 글쓰기에서 로그인 화면이 뜸"}
    if r != "ok":
        return {"state": "unknown", "nick": "", "why": "커뮤니티 화면을 못 읽음 — " + r[5:].strip()}
    # 실제 글쓰기 화면까지 들어가 봄 (2026-10-15 요청): 성형 → 주제·제목·내용 칸·작성 완료가 보이면 쓸 수 있음.
    # 아무것도 입력하지 않고 X 로 나옴 — 빈 글이면 확인 창 없이 바로 나가짐 (60번 실측).
    app.tap_text("성형", 3.0)
    xml = app.dump()
    if app.verify_screen(xml):
        app.close_verify()
        app.tab("홈")
        return {"state": "out", "nick": prev.get("nick", ""), "tag": "본인인증 필요",
                "why": "본인인증 필요 — 글쓰기를 누르면 휴대폰 본인 인증 창이 뜸 (그 폰에서 직접 인증)"}
    ready = all(app.find(xml, text=t) for t in ("눈", "코", "작성 완료")) and \
        bool(app.find(xml, text="제목을 입력해주세요 (20자 이내)")) and bool(app.find(xml, text="내용을 입력해 주세요"))
    back = app.find(xml, desc="Back Button")
    if back:
        app.tap(back, 2.0)
        x2 = app.dump()
        leave = app.find(x2, text="나가기") or app.find(x2, rid=f"{app_site.PKG}:id/yes_button")
        if leave:                                       # 혹시 '나갈까요?' 창이 뜨면
            app.tap(leave, 1.5)
    else:
        board.key(4, devs)
    app.tab("홈")
    if not ready:
        return {"state": "unknown", "nick": prev.get("nick", ""),
                "why": "글쓰기 화면이 다르게 뜸 — 성형 게시판에서 제목·내용 칸을 못 찾음 (화면 확인)"}
    return {"state": "in", "nick": prev.get("nick", ""), "why": ""}
