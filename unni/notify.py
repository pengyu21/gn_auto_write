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
