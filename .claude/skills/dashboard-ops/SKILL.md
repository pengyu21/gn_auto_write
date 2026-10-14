---
name: dashboard-ops
description: 강언(바비톡) 로테이션 대시보드 운영 — 코드 고친 뒤 PC 대시보드를 안전하게 다시 켜기, 시트 탭 규칙, Apps Script 파일 반영, 진행 중 작업 확인. dashboard.py·unni/·core/·ui/ 를 고쳤거나 "다시 켜", "반영해" 요청 때 사용.
---

# 대시보드 운영

## 다시 켜기 전 확인 (작업 도중에 끄면 글이 반쯤 올라간 채 멈춤)
1. 지금 시각과 `run_plan.json` → `days[오늘].at`(예정 시각), `days[오늘].done`(끝난 것)
2. `dashboard.log` 끝 몇 줄 — "미리 로그인", "[1]~[5]" 단계, "크롬 탭 정리" 가 막 찍히고 있으면 진행 중
3. 다음 작업 시작 10분 전(미리 로그인 PREP_LEAD)부터는 끄지 않는다. 애매하면 사용자에게 묻는다
4. 고친 파이썬은 먼저 `ast.parse` 로 구문 확인

## 다시 켜기
```powershell
$p = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'dashboard\.py' }
$p | % { Stop-Process -Id $_.ProcessId -Force }; Start-Sleep 3
Start-Process ".\강언 대시보드.lnk"; Start-Sleep 25
Get-Content dashboard.log -Tail 3 -Encoding utf8
```
켜진 뒤 `run_plan.json` 의 오늘 예정이 그대로인지 확인.

## 화면(ui/dashboard.html) 고쳤을 때
- `appsscript/DashWeb.html` 로 복사 (PC 화면과 웹앱이 같은 파일)
- 웹앱 반영은 사용자가 Apps Script 에 붙여넣고 "배포 관리 → 새 버전" 해야 함 — 안내만
- 화면 확인: 스크래치의 목업 HTML 을 Edge headless `--screenshot` 으로 찍어 Read 로 본다

## 시트·Apps Script
- Code.gs(doPost API)는 고치지 않는다. 새 기능은 별도 .gs 파일 (Dash.gs, Watch.gs)
- Code.gs 는 없는 탭에 쓰지 못함 → 새 탭은 사용자가 만들거나 Apps Script 함수로 생성
- 탭: 강언게시글로테이션(일정, M1=생존신호), 강언아이디, 강언업로드이력(메일 큐·이력), 강언대시보드(웹앱 값), 강언대시보드명령, 바비톡게시글로테이션
- 시트 열은 머리글 이름으로 찾는다(unni/schedule.py COLUMNS) — 사용자가 열을 넣고 빼는 일이 잦음

## 공개 저장소(github pengyu21/gn_auto_write) 올릴 때
- settings.json, 계정/닉네임/로그인 상태 json, roster.csv, dashboard.log, 백업은 절대 커밋 금지 (.gitignore)
- 올리기 전 settings.json 의 값(토큰·시트 주소·chat id·메일)이 스테이징 내용에 없는지 검사
- 공용 PC — 개인 계정 로그인 금지, 배포 키(core.sshCommand)만 사용
