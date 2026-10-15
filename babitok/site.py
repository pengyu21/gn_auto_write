"""바비톡 앱(com.sleet.beautyplastic 7.0.35) 화면 요소 — 2026-10-14 60번에서 실측.

글쓰기:  커뮤니티 탭 → '글쓰기' → 게시판 '성형' → 주제 칩 → 제목 칸 → 내용 칸 → '작성 완료'
         → '게시글이 업로드 되었어요' 창 (yes_button=글 보기 / no_button=아니오)
지난 글 삭제: MY 바비톡 탭 → '내가쓴글' → '커뮤니티' 탭 → (자동화로 올린 제목인 글) → 휴지통 → yes_button '확인'
         목록은 최신순. 계정이 원래 직접 쓴 글도 섞여 있으므로
         **시트 제목과 같은 글만** 지운다.

아래 탭(홈·전체 서비스·커뮤니티·찜·MY)은 글자 노드의 bounds 가 [0,0][0,0] 이라 글자로 못 누른다.
같은 줄(y≈1596~1685)의 클릭 가능한 View 5칸이 글자와 같은 순서 → 칸 순서(index)로 누른다.
"""
PKG = "com.sleet.beautyplastic"
MAIN = f"{PKG}/.activity.SplashActivity"

# 아래 탭: 글자 순서 = 칸 순서
TABS = ["홈", "전체 서비스", "커뮤니티", "찜", "MY 바비톡"]

# 커뮤니티
WRITE_BUTTON = "글쓰기"                         # text
BOARD_TITLE = "게시판 선택"                     # 게시판 고르는 창 머리글 (뜨면 로그인돼 있음)
BOARD_SURGERY = "성형"                          # 맨 위 게시판
TOPICS = ["눈", "코", "지방흡입/이식", "가슴", "안면윤곽/양악", "남자성형", "기타"]   # 칩 text (다중 선택 가능)
TITLE_HINT = "제목을 입력해주세요 (20자 이내)"   # 빈 제목 칸 text
BODY_HINT = "내용을 입력해 주세요"              # 빈 내용 칸 text
SUBMIT = "작성 완료"
UPLOADED_TITLE = "게시글이 업로드 되었어요"      # rid title_text
YES = f"{PKG}:id/yes_button"
NO = f"{PKG}:id/no_button"

# MY 바비톡 → 내가 쓴 글
MY_POSTS = "내가쓴글"                           # text (옆에 개수)
MY_POSTS_TITLE = "내가 작성한 게시글"           # rid navigation_title
MY_POSTS_COMMUNITY = "커뮤니티"                 # content-desc (후기/커뮤니티/댓글 탭)
NO_POSTS = "내가 작성한 게시글이 없습니다"

# 휴대폰 본인 인증 창 (인증 안 된 계정이 글쓰기를 누르면 뜸, 2026-10-15 83번) — 자동으로는 못 넘김.
# '다음에 하기' 로 닫고 그 작업은 건너뜀 (시트에 '건너뜀: 본인인증 필요').
VERIFY_TITLE = f"{PKG}:id/user_verification_title"   # '휴대폰 본인 인증'
VERIFY_LATER = f"{PKG}:id/pass_close"                # '다음에 하기'
VERIFY_TEXT = "휴대폰 본인 인증"

# 글 보기 화면 오른쪽 위: 공유(816~936) · 휴지통(936~1080) — 둘 다 desc 'None' 이라 오른쪽 것이 휴지통
DELETE_TITLE = "게시글 삭제"                    # rid title_text, 확인 = YES
BACK = "Back Button"                            # content-desc
