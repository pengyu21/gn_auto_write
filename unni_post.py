"""시트 '강언게시글로테이션' 의 한 행을 실행: 계정 전환 -> 지난 글 삭제 -> 새 글 업로드.

    python unni_post.py --row 61               # 지난 글(J열)도 지우고 올림
    python unni_post.py --row 61 --no-delete   # 지우지 않고 올리기만

흐름과 시트 기록 규칙은 unni/job.py 에 있습니다.
"""
from __future__ import annotations

import argparse
import sys

from unni.job import run_row


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="강언게시글로테이션 한 행 실행")
    ap.add_argument("--row", type=int, required=True, help="시트 행 번호 (머리글=1)")
    ap.add_argument("--no-delete", action="store_true", help="J열의 지난 글을 지우지 않음")
    a = ap.parse_args()
    run_row(a.row, delete_old=not a.no_delete)


if __name__ == "__main__":
    main()
