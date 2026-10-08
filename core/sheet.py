"""구글 시트 — Apps Script 웹앱을 통해 읽고 씁니다.

웹앱 주소·토큰은 settings.json 의 sheet_url / sheet_token. 웹앱 코드(Code.gs)는
시트에 붙어 있는 것을 그대로 씁니다. 탭 이름만 받는 범용 기능(tab_read /
tab_append / tab_write)이 있어서 **탭을 새로 만들어도 Code.gs 는 고치지 않습니다.**

    s = Sheet()
    rows = s.read("강언아이디")                    # 2차원 배열 (글자)
    s.append("강언게시글", [[...], [...]])
    s.write("강언게시글", "I5", [["삭제됨"]])

URL 과 토큰을 아는 사람은 누구나 시트를 읽고 쓸 수 있습니다. 같이 흘리지 마세요.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .board import load_settings

TIMEOUT = 30


class SheetError(RuntimeError):
    transient = False      # True = 네트워크/구글 쪽 일시 오류


def _transient(msg):
    exc = SheetError(msg)
    exc.transient = True
    return exc


class Sheet:
    # 다시 보내도 결과가 같은 요청만 재시도합니다. 웹앱은 가끔(특히 재배포
    # 직후) 구글 오류 HTML / 404 / 응답 없음으로 실패합니다. 줄을 붙이는
    # 요청은 실제로는 들어갔는데 응답만 못 받은 경우가 있어 재시도하면 같은
    # 줄이 두 번 생깁니다 — 재시도하지 않습니다.
    IDEMPOTENT = {"ping", "accounts", "post_live", "post_patch", "tab_read", "tab_write"}
    RETRIES = 4

    def __init__(self, settings=None):
        s = settings or load_settings()
        self.url = str(s.get("sheet_url", "")).strip()
        self.token = str(s.get("sheet_token", "")).strip()
        if not self.url.startswith("https://script.google.com/") or not self.token:
            raise SheetError("settings.json 에 sheet_url / sheet_token 이 없습니다")

    # -- 범용 ----------------------------------------------------------------

    def read(self, tab: str, range: str = "") -> list[list[str]]:
        """탭 전체(또는 A1 범위). 날짜는 'yyyy-MM-dd HH:mm' 글자로 옵니다."""
        return self.call("tab_read", sheet=tab, range=range)["values"]

    def append(self, tab: str, rows, text: bool = False, checkbox_col: int = 0) -> int:
        """맨 아래에 여러 줄. 시작 행 번호를 돌려줍니다.
        text=True 면 글자 서식으로 (날짜·숫자 자동 변환 방지)."""
        return self.call("tab_append", sheet=tab, rows=rows, text=text,
                         checkbox_col=checkbox_col)["first"]

    def write(self, tab: str, start: str, values, text: bool = False, bold: bool = False):
        """start 칸(A1 표기)부터 values 크기만큼 덮어씁니다."""
        return self.call("tab_write", sheet=tab, range=start, values=values,
                         text=text, bold=bold)

    # -- 계정 ----------------------------------------------------------------

    def accounts(self, rotation: int) -> dict:
        """'강언아이디' 로테이션 N, 사용여부 TRUE 인 줄만.
        {"accounts": {"60": {"id", "pw"}, ...}, "skipped": [...]}
        비밀번호가 실려 오므로 화면·로그에 찍지 마세요."""
        return self.call("accounts", rotation=rotation)

    # -- 전송 ----------------------------------------------------------------

    def call(self, action: str, **payload) -> dict:
        tries = self.RETRIES if action in self.IDEMPOTENT else 1
        for i in range(tries):
            try:
                return self._once(action, payload)
            except SheetError as exc:
                if i == tries - 1 or not exc.transient:
                    raise
                time.sleep(2.0 + i * 2)

    def _once(self, action: str, payload: dict) -> dict:
        body = json.dumps({"token": self.token, "action": action, **payload},
                          ensure_ascii=False).encode("utf-8")
        # text/plain 이어야 preflight 없이 갑니다. /exec 의 302 를 따라가며
        # GET 으로 바뀌는 건 정상입니다.
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": "text/plain;charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                raw = res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise _transient(f"HTTP {exc.code} — 웹앱 배포(액세스: 모든 사용자)를 확인하세요") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise _transient(f"연결 실패: {getattr(exc, 'reason', exc)}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise _transient("JSON 이 아닌 응답(구글 오류 페이지): "
                             + raw.strip()[:120].replace("\n", " "))
        if not data.get("ok"):
            raise SheetError(data.get("error", "알 수 없는 오류"))
        return data
