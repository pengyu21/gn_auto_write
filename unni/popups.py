"""팝업 닫기. 강남언니는 팝업을 자주, 여러 겹으로 띄웁니다.

전부 **글자가 정확히 일치할 때만** 누릅니다. '구글 계정으로 계속', '앱으로
편하게 보기', '확인', '저장' 같은 건 절대 넣지 마세요 — 크롬 구글 로그인 /
앱 설치 / 비밀번호 저장으로 넘어갑니다.
"""
from __future__ import annotations

import time

from core import screen

CHROME = "com.android.chrome"
CHROME_DISMISS = {                    # 크롬 자체 안내창·말풍선
    "로그아웃 상태로 사용", "로그아웃 상태 유지", "계정 없이 사용",
    "Use without an account", "Stay signed out",
    "나중에", "No thanks", "아니요", "안함", "사용 안함", "저장 안함", "Never",
}
CHROME_LATER = {"나중에", "No thanks", "Not now"}     # 'Chrome 알림' 시트 (id 가 버전마다 다름)
PERMISSION_DISMISS = {"허용 안함", "허용 안 함", "Don't allow", "차단"}
PERMISSION_PKGS = {"com.android.permissioncontroller", "com.google.android.permissioncontroller"}
WEB_DISMISS_TEXT = {                  # 강남언니 페이지 안 팝업
    "모바일 웹으로 볼게요", "모바일웹으로 볼게요", "모바일 웹으로 볼게요.",
    "닫기", "오늘 하루 보지 않기", "오늘 그만 보기", "오늘 하루 그만 보기",
    "다시 보지 않기", "다음에 할게요", "나중에 할게요", "괜찮아요",
}
WEB_DISMISS_DESC = {"close", "Close", "닫기", "close modal", "Close modal", "모달 닫기"}
SCREEN_AREA = 1080 * 1920


def find_popup(xml):
    """이 화면에서 닫아야 할 팝업 버튼. (이름, (x, y)) 또는 None.

    앱 설치 팝업은 'close' 가 두 개로 잡힙니다 — 화면 전체를 덮는 배경과
    오른쪽 위 X. 배경 가운데는 그림이라 눌러도 안 닫힙니다(79번에서 스무 번
    넘게 누름). 그래서 화면 35% 이상을 덮는 건 버리고 가장 작은 걸 누릅니다.
    """
    closers = []
    for n in screen.nodes(xml):
        pkg = n.get("package", "")
        text = n.get("text", "").strip()
        desc = n.get("content-desc", "").strip()
        pt = screen.centre(n)
        if not pt:
            continue
        if pkg == CHROME:
            if desc in WEB_DISMISS_DESC and screen.area(n) < SCREEN_AREA * 0.35:
                closers.append(n)
            if text in CHROME_LATER:
                return f"크롬 '{text}'", pt
            if n.get("resource-id", "").startswith(f"{CHROME}:id/"):
                if text in CHROME_DISMISS:
                    return f"크롬 '{text}'", pt
                continue
            if text in WEB_DISMISS_TEXT:
                return f"페이지 '{text}'", pt
            if text in CHROME_DISMISS and n.get("class", "").endswith("Button"):
                return f"크롬 '{text}'", pt
        elif pkg in PERMISSION_PKGS and text in PERMISSION_DISMISS:
            return f"권한창 '{text}'", pt
    if closers:
        n = min(closers, key=screen.area)
        return f"페이지 '{n.get('content-desc')}'", screen.centre(n)
    return None


def close_popups(board, devs, rounds: int = 4, quiet: bool = False) -> dict[int, str]:
    """팝업을 전부 닫고, 마지막으로 읽은 화면 구조 {번호: xml} 를 돌려줍니다.

    돌려주는 구조는 팝업이 없는 상태라 부르는 쪽이 그대로 다음 판단에 씁니다.
    같은 버튼을 눌러도 안 닫히는 기기는 더 누르지 않고 그 화면을 그대로 돌려줍니다.
    """
    screens: dict[int, str] = {}
    pending = list(devs)
    tried: dict[int, set] = {}
    for _ in range(rounds):
        if not pending:
            break
        got = screen.dump(board, pending)
        screens.update(got)
        taps = []
        for d in pending:
            xml = got.get(d.no)
            hit = find_popup(xml) if xml else None
            if not hit:
                continue
            seen = tried.setdefault(d.no, set())
            if hit in seen:
                if not quiet:
                    print(f"  !! {d.no}: {hit[0]} 눌러도 안 닫힘")
                continue
            seen.add(hit)
            taps.append((d, *hit[1]))
            if not quiet:
                print(f"  팝업 닫기 {d.no}: {hit[0]}")
        if not taps:
            break
        board.tap(taps)
        time.sleep(1.6)
        pending = [d for d, _x, _y in taps]
        for d in pending:
            screens.pop(d.no, None)
    missing = [d for d in devs if d.no not in screens]      # 마지막에 누른 기기
    if missing:
        screens.update(screen.dump(board, missing))
    return screens
