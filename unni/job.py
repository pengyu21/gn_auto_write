"""시트 한 행 = 작업 하나: 계정 전환 -> 지난 글 삭제 -> 새 글 업로드 -> 시트 기록.

    from unni import job
    job.run_row(61)                      # 지난 글(게시글 URL)도 지움
    job.run_row(61, delete_old=False)    # 올리기만
    job.run_key("2-금-8-88")             # 주차-요일-시-폰 으로 찾기 (행 번호는 정렬하면 바뀜)

시트 기록 (사용자가 정한 규칙):
    작업 여부        '작업중' -> '성공' / '실패: 이유'
    게시글 URL       새 글 주소 (다음 차례에 이 글을 지우고 새로 올림)
    최종 업로드 날짜  시트 날짜 값(숫자). 열 서식 'yyyy-mm-dd (ddd) hh:mm' 으로
                     '2026-10-07 (수) 17:31' 처럼 보임
    업로드 계정       '아이디 (닉네임)' — 계정이 바뀌어도 알아챌 수 있게
    (열은 머리글 이름으로 찾습니다. '삭제 유무' 열은 2026-10-07 사용자가 뺌 —
     있으면 지난 글 삭제 결과를 적고, 없으면 건너뜁니다.)

지난 글을 못 지우면 새 글을 올리지 않고 작업 여부에 '실패: 지난 글 삭제 실패 …'
를 남깁니다 (같은 행 글이 두 개 쌓이지 않게). 그래서 '성공' 이면 지난 글은 정리된 것.
닉네임을 아는 계정이면 커뮤니티 화면 닉네임이 다를 때 글을 쓰지 않습니다.
"""
from __future__ import annotations

import time
from datetime import datetime

from core import chrome
from core.board import Board
from core.sheet import Sheet
from . import login, post, schedule


def key_of(j: schedule.Job) -> str:
    """행이 정렬로 옮겨져도 같은 작업을 가리키는 이름: '주차-요일-시-폰'.
    시간까지 넣는 이유: 사용자가 폰 배정을 바꾸면(2026-10-08) 같은 폰이 다른 시간대로
    옮겨 가는데, 시간이 빠진 이름이면 옛 계획(시작 시각·건너뜀 표시)이 그대로 붙습니다."""
    return f"{j.week}-{j.day}-{j.hour}-{j.board}"


def run_key(key: str, delete_old: bool = True, log=print) -> dict:
    return _run(lambda j: key_of(j) == key, key, delete_old, log)


def run_row(row: int, delete_old: bool = True, log=print) -> dict:
    return _run(lambda j: j.row == row, f"{row}행", delete_old, log)


def _run(match, label, delete_old, log) -> dict:
    t0 = time.time()
    sheet = Sheet()
    values = sheet.read(schedule.TAB)
    idx = schedule.columns(values[0])
    job = next((j for j in schedule.load_rows(values=values) if match(j)), None)
    if not job:
        raise ValueError(f"시트에서 작업을 못 찾음: {label}")
    row = job.row

    def put(**fields):
        """여러 칸을 씁니다. 붙어 있는 칸이면 한 번에 (시트 왕복이 1~2초씩이라)."""
        cells = sorted((idx[f], v) for f, v in fields.items() if f in idx)
        if not cells:
            return
        cols = [c for c, _v in cells]
        if cols == list(range(cols[0], cols[0] + len(cols))):
            sheet.write(schedule.TAB, f"{schedule.col_letter(cols[0])}{row}",
                        [[v for _c, v in cells]], text=False)
        else:
            for c, v in cells:
                sheet.write(schedule.TAB, f"{schedule.col_letter(c)}{row}", [[v]], text=False)

    def fail(msg, **more):
        put(status=f"{schedule.FAIL}: {msg}", **more)
        log(f"!! {job.board}번 {job.week}주차 {job.day} {job.hour}시 실패: {msg}  ({time.time() - t0:.0f}초)")
        return {"ok": False, "error": msg}

    log(f"=== {job.board}번 · {job.week}주차 {job.day} {job.hour}시 · 로테 {job.rotation} · "
        f"{job.surgery} [{job.category}] ===")
    board = Board()
    devs = board.select([job.board])
    if not devs:
        return fail("폰 연결 안 됨")
    dev = devs[0]
    if login.offline(board, devs):
        return fail("인터넷 연결 없음")
    put(status=schedule.RUNNING)
    try:
        return _steps(job, board, devs, dev, idx, put, fail, delete_old, log, t0)
    finally:
        # 작업이 끝나면(성공·실패 모두) 그 폰의 크롬 탭을 모두 닫습니다 — 탭이 계속 쌓여서
        # (사용자 요청 2026-10-10). 로그인은 쿠키라 탭을 닫아도 풀리지 않습니다.
        try:
            chrome.close_all_tabs(board, devs)
            log(f"  {job.board}번 크롬 탭 정리")
        except Exception as exc:                     # noqa: BLE001 — 탭 정리 실패는 결과에 영향 없음
            log(f"  {job.board}번 탭 정리 실패: {exc}")


def _steps(job, board, devs, dev, idx, put, fail, delete_old, log, t0) -> dict:
    # 1. 이 행의 로테이션 계정으로 (미리 로그인돼 있으면 확인만)
    account = login.load_accounts(job.rotation).get(job.board)
    if not account:
        return fail(f"'강언아이디' 로테이션 {job.rotation} 에 {job.board}번 계정 없음")
    sw = login.switch(board, dev, account, log=log)
    if sw.startswith("fail"):
        return fail(f"로그인: {sw[5:].strip()}")
    log(f"  계정 확인/전환 {time.time() - t0:.0f}초")

    # 2. 지난 글
    if delete_old and job.url:
        log(f"  지난 글 삭제: {job.url}")
        k = post.delete(board, devs, lambda d: job.url, log=log)[job.board]
        if "deleted" in idx:
            put(deleted=k)
        if k not in ("삭제됨", "이미 없음"):
            return fail(f"지난 글 삭제 실패 — 새 글 보류 ({k})")

    # 3. 새 글 — 닉네임을 아는 계정이면 그 닉네임일 때만 씀
    want = login.known_nicks().get(account["id"], "")
    r = post.write(board, devs, lambda d: job.text, lambda d: job.category, log=log,
                   expect_for=lambda d: want)[job.board]
    who = f"{account['id']} ({r['nick']})" if r["nick"] else account["id"]
    if not r["ok"]:
        return fail(r["error"], account=who)
    login.remember_nick(account["id"], r["nick"])
    put(status=schedule.SUCCESS, url=r["url"], uploaded=schedule.sheet_serial(datetime.now()), account=who)
    log(f"  완료: {r['url']}  (총 {time.time() - t0:.0f}초)")
    return {"ok": True, "url": r["url"], "nick": r["nick"]}
