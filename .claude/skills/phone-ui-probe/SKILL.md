---
name: phone-ui-probe
description: 폰보드(60~99) 안드로이드 화면을 adb·uiautomator 로 실측해 누를 요소(id/text/desc)를 찾는 절차. 바비톡 앱(com.sleet.beautyplastic)이나 크롬 화면의 새 자동화 단계를 만들거나, "버튼을 못 찾음" 류 실패를 조사할 때 사용.
---

# 폰 화면 실측 (추측으로 누르지 않기)

원칙: **좌표를 짐작해서 누르지 않는다.** 항상 화면을 덤프해 요소를 id → text → content-desc 순으로 찾고, 찾은 요소의 중심을 누른다. 못 찾으면 실패로 돌려주고 이유를 남긴다.

## 도구 (core/)
- `core.board.Board()` — `select([번호])` 로 기기, `shell(명령, devs)`, `key(키코드, devs)`, `tap([(dev, x, y)])`, `run(devs, lambda d: [...])`
- `core.screen` — `dump(board, devs) -> {번호: xml}`, `nodes(xml)`, `find(xml, rid=/text=/desc=)`, `point(...)`(중심 좌표), `url_of(xml)`(크롬 주소)
- 덤프 속성은 html.unescape 된 값으로 비교 (`&#10;` 같은 줄바꿈 주의)
- 키보드 입력은 `core.keyboard` (ADB IME). 입력 뒤엔 화면이 줄어드니 **키보드를 내리고 다시 덤프한 뒤** 다음 버튼을 찾는다

## 절차
1. 한 대(보통 60번)로 시작. 스크립트는 스크래치 폴더에 파일로 쓰고 실행 (PowerShell `python -c` 따옴표 문제 회피)
2. 앱 실행: `am start -n com.sleet.beautyplastic/.activity.SplashActivity` (바비톡) — 앞에 떴는지 `dumpsys activity activities | grep ResumedActivity`
3. 단계마다: 덤프 → 텍스트/ id 목록 출력 → 대상 요소 확인 → 누름 → 1.5~3초 대기 → 다시 덤프로 결과 확인
4. 팝업(이벤트 배너 '닫기'/'오늘 안보기', 권한 창)은 매 단계 시작 때 먼저 닫는다 — 폰마다 뜨는 팝업이 다름
5. 화면 캡처가 필요하면 `screencap -p /sdcard/x.png` → `adb pull` → Read 로 이미지 확인
6. 찾은 id/문구는 `unni/site.py` 처럼 앱별 상수 파일(예: `babitok/site.py`)에 모으고, 왜 그 요소인지 한 줄 주석

## 안전
- 실측 중에도 자동 작업(강남언니 스케줄)이 같은 폰을 쓸 수 있다. 시작 전 `run_plan.json` 의 오늘 예정 시각과 `dashboard.log` 끝부분을 보고 겹치지 않는 폰·시간에 한다
- '회원 탈퇴'·'계정 삭제' 류 버튼은 절대 누르지 않는다 (문구로 걸러서 막기)
- 글쓰기 실측은 실제로 올라가므로, 등록 직전까지만 확인하거나 올린 뒤 바로 삭제까지 확인
