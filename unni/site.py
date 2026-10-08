"""강남언니 주소와 화면 요소. **사이트가 바뀌면 여기 한 곳만 고칩니다.**

2026-09-23 도메인이 www.gangnamunni.com -> unni.app 으로 옮겨졌습니다. 옛 주소의
/mypage 는 두 번 튕겨 홈으로 떨어져서 로그아웃이 통째로 깨진 적이 있습니다.

요소 이름은 2026-09-30 / 10-01 에 60·89번에서 화면 구조로 실측했습니다.
"""
from __future__ import annotations

BASE = "https://unni.app"
HOME = BASE
MYPAGE = f"{BASE}/mypage"
SIGNIN_EMAIL = f"{BASE}/signin/email"
COMMUNITY = f"{BASE}/community"

# -- 공통 -----------------------------------------------------------------------
PAGE = "frameMain"                              # 웹 내용이 구조에 잡혔다는 표시

# -- 홈 / 로그인 (resource-id) ----------------------------------------------------
HOME_LOGIN = "all-header-btn-login"             # 로그아웃 상태: '로그인/가입'
HOME_PROFILE = "all-header-btn-profile"         # 로그인 상태: 닉네임 버튼
MAIL_ICON = "login-section-btn-login-email"     # 로그인 방식 중 편지 아이콘
EMAIL = "login-page-input-textInput-email"      # text = 입력된 값
PASSWORD = "login-page-input-textInput-password"
SUBMIT = "login-page-btn-login"                 # 빈 칸이면 enabled=false
WRONG_PASSWORD_TEXT = "일치하지 않"              # '이메일 또는 비밀번호가 일치하지 않아요'

# -- 로그아웃 (content-desc, 정확히 일치로만) -----------------------------------------
ACCOUNT_MENU = "account management"             # 마이페이지 '계정 관리'
SIGN_OUT = "sign out"                           # 계정 관리 시트의 '로그아웃'
WITHDRAW = "withdraw member"                    # 회원 탈퇴 — 절대 누르지 않음

# -- 커뮤니티 글쓰기 / 삭제 --------------------------------------------------------
TAB_COMMUNITY = "all-tab-link-moveTo-community"  # 하단 탭 (resource-id)
WRITE_BUTTON = "Write document"                  # 연필 버튼 (content-desc)
DEFAULT_CATEGORY = "의사에게 물어보세요"            # 글쓰기 창 카테고리 기본값 (text)
CATEGORY_ITEM = "android:id/text1"               # 카테고리 목록 항목 (크롬 기본 선택창)
SUBMIT_POST = "등록하기"                          # text, 내용이 비면 enabled=false
POST_MORE = "more icon"                          # 글 작성자 오른쪽 점 3개 (content-desc)
DELETE = "삭제하기"                               # 시트의 항목과 확인창 버튼이 같은 글자
DELETE_CONFIRM_TEXT = "내가 쓴 글을 삭제할까요?"    # 이 창이 떴을 때만 확인 버튼을 누름
# 지운 글 주소를 열면: 2026-09-30 엔 /community 로 튕김, 10-07 엔 같은 주소에 이 문구.
NOT_FOUND_TEXT = "페이지를 찾을 수 없어요"
