# gn_auto_write

폰보드(60~99번 안드로이드 40대)로 강남언니(unni.app) 커뮤니티 글을 시트 일정대로 올리고,
다음 차례에 지난 글을 지운 뒤 새로 올리는 자동화 + 데스크톱 대시보드.

## 구성

| 경로 | 하는 일 |
|---|---|
| `dashboard.py` + `ui/dashboard.html` | 대시보드 창 (pywebview). 일정·폰 상태·달력, 자동 실행 켜기/끄기, 지금 실행 |
| `unni/scheduler.py` | 자동 실행. 오늘 날짜 행만, 시간대 안 무작위 분(0~40분), 지난 시간대는 건너뜀, 미리 로그인, M1 생존 신호 |
| `unni/job.py` | 시트 한 행 = 작업 하나: 계정 전환 → 지난 글 삭제 → 새 글 업로드 → 시트 기록 |
| `unni/post.py` | 글 올리기 / 지우기 (화면 구조로 버튼을 찾아 누름) |
| `unni/login.py` | 로그인·로그아웃·로그인 상태 점검, 빠른 계정 전환 |
| `unni/schedule.py` | 시트 ↔ 날짜 (일요일 시작 달력 주차, 6주차는 건너뜀) |
| `unni/site.py` | 강남언니 주소와 화면 요소 이름 (사이트가 바뀌면 여기만 고침) |
| `core/` | adb(폰보드), 화면 구조 읽기, 크롬, ADB 키보드 입력, 구글 시트 |
| `unni_login.py`, `unni_post.py` | 명령줄 도구 |

## 처음 설정

1. Python 3.12+ 와 `pip install -r requirements.txt`
2. `settings.example.json` → `settings.json` 으로 복사하고 시트 웹앱 주소·토큰, adb 경로 입력
3. `roster.example.csv` → `roster.csv` 로 복사하고 폰 시리얼 ↔ 폰보드 번호 입력
4. 실행: `pythonw dashboard.py` (콘솔 창 없이) 또는 `python dashboard.py`

> **`settings.json`, `roster.csv`, `account_nicks.json`, `login_state.json` 은 절대 올리지 마세요.**
> 특히 `settings.json` 의 시트 토큰이 있으면 누구나 '강언아이디' 탭(아이디/비밀번호)을 읽을 수 있습니다.
> `.gitignore` 에 들어 있습니다.

## 시트 '강언게시글로테이션'

열은 머리글 이름으로 찾습니다 (순서가 바뀌어도 됨).

| 열 | 내용 |
|---|---|
| 주차 / 요일 / 작업시간 | 1~5주차, 월~일, '15시' — 그 달 달력(일요일 시작)의 주차·요일에 실행 |
| 로테이션 / 폰보드 | 어느 계정(시트 '강언아이디' 의 로테이션 N)으로 어느 폰에서 |
| 수술부위 / 게시글 / 게시판 | 올릴 글. 게시판은 '자유수다' 또는 '병원질문' |
| 작업 여부 | 프로그램이 기록: '작업중' → '성공' / '실패: 이유' |
| 게시글 URL | 올린 글 주소. 다음 차례에 이 글을 지우고 새로 올림 |
| 최종 업로드 날짜 | 날짜 값. 열 서식 `yyyy-mm-dd (ddd) hh:mm` |
| 업로드 계정 | '아이디 (닉네임)' — 계정이 바뀌었는지 확인용 |
| M1 셀 | 마지막 실행 시각 (5분마다, 프로그램 멈춤 감시용) |

## 자동 실행 설정 (`settings.json`)

| 키 | 뜻 |
|---|---|
| `auto_from`, `auto_until` | 이 기간에만 자동 실행 |
| `rotation_start` | 이 날 이전은 대시보드에서 '기록 없음' 으로 표시 |
| `skip_boards` | 자동 실행에서 뺄 폰 번호 목록 (예: 인터넷 안 되는 폰) |

## 명령줄

```
python unni_login.py --state                 # 로그인 상태 점검
python unni_login.py --only 78 --rotation 2  # 로그인
python unni_login.py --restore-ime           # 도중에 멈췄을 때 키보드 원래대로
python unni_post.py --row 61 [--no-delete]   # 시트 한 행 실행
```

## 안전장치

- 누를 곳은 화면 구조(id / 글자)로 찾고, 못 찾으면 누르지 않고 실패로 남깁니다 (좌표로 짐작해서 누르지 않음).
- 지난 글을 못 지우면 새 글을 올리지 않습니다 (같은 행 글이 두 개 쌓이지 않게).
- 닉네임을 아는 계정이면 화면 닉네임이 다를 때 글을 쓰지 않습니다.
- 대시보드는 한 개만 실행됩니다 (두 개면 같은 글이 두 번 올라갈 수 있음).
