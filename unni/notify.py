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


MAIL_TAB = "알림"     # 시트 탭. Watch.gs 가 5분마다 읽어 메일로 보내고 'D 메일 보냄' 에 시각을 적음


def queue_mail(title: str, body: str) -> bool:
    """메일 보낼 내용을 시트 '알림' 탭에 한 줄 붙입니다 (보내는 건 시트 Apps Script).
    이 PC 에 메일 계정·비밀번호를 두지 않으려고 이렇게 합니다."""
    try:
        from datetime import datetime
        from core.sheet import Sheet
        Sheet().append(MAIL_TAB, [[datetime.now().strftime("%Y-%m-%d %H:%M:%S"), title, body, ""]], text=True)
        return True
    except Exception:                                   # noqa: BLE001 — 탭이 아직 없으면 등
        return False


def both_async(title: str, body: str):
    """텔레그램(바로) + 메일(시트 거쳐 5분 안)."""
    def run():
        telegram(f"{title}\n{body}")
        queue_mail(title, body)
    threading.Thread(target=run, daemon=True).start()
