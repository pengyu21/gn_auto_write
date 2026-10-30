"""텔레그램 알림. settings.json 의 telegram_token / telegram_chat_id 를 씁니다
(공개 저장소에 올리지 않는 파일). 설정이 없으면 조용히 건너뜁니다.

    from unni import notify
    notify.telegram("79번 2주차 목 8시 실패: 인터넷 연결 없음")

알림이 실패해도 작업을 멈추지 않습니다 (알림 때문에 업로드가 깨지면 안 됨).
'프로그램이 멈췄을 때' 알림은 여기가 아니라 시트 쪽 Apps Script(appsscript/Watch.gs)가
M1 생존 신호를 보고 보냅니다 — 프로그램이 꺼지면 스스로는 알릴 수 없어서.
"""
from __future__ import annotations

import json
import threading
import urllib.request

from core.board import load_settings

TIMEOUT = 15


def telegram(text: str) -> bool:
    s = load_settings()
    token = str(s.get("telegram_token", "")).strip()
    chat = s.get("telegram_chat_id")
    if not token or not chat:
        return False
    body = json.dumps({"chat_id": chat, "text": text[:4000],
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception:                                   # noqa: BLE001 — 알림 실패는 무시
        return False


def telegram_async(text: str):
    """작업 스레드를 붙잡지 않게 따로 보냅니다."""
    threading.Thread(target=telegram, args=(text,), daemon=True).start()


# 시트 탭. Watch.gs 가 5분마다 읽어 메일로 보내고 '메일 보냄' 칸에 시각을 적음 (열은 머리글 이름으로 찾음).
# 2026-10-12 '알림' -> '강언업로드이력', 2026-10-15 -> '업로드이력' (강남언니·바비톡 같이). Watch.gs 와 같은 이름이어야 함.
MAIL_TAB = "업로드이력"


# 열은 시트 1행 머리글 이름으로 맞춰 적음 — 사용자가 열을 넣거나 옮겨도 그대로 (2026-10-30 '폰보드' 열 추가)
MAIL_HEAD = ["시각", "앱", "로테이션", "폰보드", "제목", "내용", "URL", "메일 보냄"]   # 머리글을 못 읽을 때 쓰는 기본값


def history_fields(at: str, title: str, body: str, sent: str = "") -> dict[str, str]:
    """'업로드이력' 한 줄의 칸 {머리글: 값}. 앱·로테이션·폰보드·URL 은 알림 제목·내용에서 뽑음
    (예전 이력을 바꿀 때도 같은 규칙)."""
    import re
    text = f"{title}\n{body}"
    app = "바비톡" if "바비톡" in title else "강남언니" if ("강남언니" in text or "로테" in body or "unni.app" in body) else ""
    rot = re.search(r"로테\s*(\d+)", text)
    no = re.search(r"(?<!\d)(\d{2})번", body)
    url = re.search(r"https?://(?:www\.)?unni\.app/community/\d+", body)
    return {"시각": at, "앱": app, "로테이션": rot.group(1) if rot and app == "강남언니" else "",
            "폰보드": no.group(1) if no else "", "제목": title, "내용": body,
            "URL": url.group(0) if url else "", "메일 보냄": sent}


def history_row(head: list[str], fields: dict[str, str]) -> list[str]:
    """머리글 순서대로 값을 늘어놓음. 모르는 머리글 칸은 비움."""
    return [fields.get(str(h).strip(), "") for h in head]


def queue_mail(title: str, body: str) -> bool:
    """메일 보낼 내용을 시트 '업로드이력' 탭에 한 줄 붙입니다 (보내는 건 시트 Apps Script).
    이 PC 에 메일 계정·비밀번호를 두지 않으려고 이렇게 합니다."""
    try:
        from datetime import datetime
        from core.sheet import Sheet
        sh = Sheet()
        try:
            head = [str(x).strip() for x in (sh.read(MAIL_TAB, "A1:Z1") or [[]])[0]]
            while head and not head[-1]:                # 칸 위치는 그대로 두고 끝의 빈칸만 뗌
                head.pop()
            head = head or MAIL_HEAD
        except Exception:                               # noqa: BLE001
            head = MAIL_HEAD
        f = history_fields(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), title, body)
        sh.append(MAIL_TAB, [history_row(head, f)], text=True)
        return True
    except Exception:                                   # noqa: BLE001 — 탭이 아직 없으면 등
        return False


def both_async(title: str, body: str):
    """텔레그램(바로) + 메일(시트 거쳐 5분 안)."""
    def run():
        telegram(f"{title}\n{body}")
        queue_mail(title, body)
    threading.Thread(target=run, daemon=True).start()
