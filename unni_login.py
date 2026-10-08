"""강남언니 로테이션 계정 로그인 — 폰보드 60~99번.

    python unni_login.py                          # 60-99, 로테이션 1
    python unni_login.py --only 60-69             # 일부만
    python unni_login.py --only 89 --rotation 2
    python unni_login.py --logout-first           # 이미 로그인된 기기는 로그아웃 후 다시 로그인
    python unni_login.py --dry-run                # 시트만 읽고 배정만 보여줌 (기기 안 건드림)
    python unni_login.py --state                  # 로그인 여부만 점검
    python unni_login.py --keep-tabs              # 끝나고 크롬 탭을 닫지 않음
    python unni_login.py --restore-ime            # 도중에 멈춰 ADB 키보드로 남은 기기 복구

흐름과 주의점은 unni/login.py 에 있습니다. 설정은 settings.json, 폰 번호표는 roster.csv.

GUI 에서:
    import unni_login
    result = unni_login.run("60-99", rotation=1, log=my_log_fn, stop=stop_event)
"""
from __future__ import annotations

import argparse
import json
import sys

from core import keyboard
from core.board import Board
from unni.login import run, run_state      # noqa: F401  GUI 에서 unni_login.run 으로 씀


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="unni.app 로테이션 계정 로그인")
    ap.add_argument("--only", default="60-99", help="예: 60-99, 60,61,70-75")
    ap.add_argument("--rotation", type=int, default=1, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--retries", type=int, default=1, help="실패 기기 재시도 횟수")
    ap.add_argument("--logout-first", action="store_true",
                    help="이미 로그인된 기기는 로그아웃 후 이 로테이션 계정으로 로그인")
    ap.add_argument("--dry-run", action="store_true",
                    help="시트만 읽고 배정(마스킹)만 출력, 기기는 안 건드림")
    ap.add_argument("--keep-tabs", action="store_true",
                    help="작업이 끝나고 크롬 탭을 닫지 않음 (기본은 끝에 모두 닫음)")
    ap.add_argument("--json", action="store_true", help="마지막에 결과를 JSON 으로 출력")
    ap.add_argument("--state", action="store_true", help="로그인 여부만 점검")
    ap.add_argument("--restore-ime", action="store_true",
                    help="ADB 키보드로 남은 기기를 원래 키보드로 복구만 함")
    a = ap.parse_args()

    if a.state:
        run_state(a.only)
        return
    if a.restore_ime:
        board = Board()
        keyboard.restore(board, board.select(a.only))
        return
    result = run(a.only, rotation=a.rotation, retries=a.retries,
                 logout_first=a.logout_first, dry_run=a.dry_run,
                 close_tabs=not a.keep_tabs)
    if a.json:
        print(json.dumps({str(k): v for k, v in result.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
