/**
 * 강언/바비톡 로테이션 대시보드 — 웹앱 (폰·어디서나 보기)
 *
 * 시트에 붙은 Apps Script 에 '새 파일'로 추가합니다 (Code.gs·Watch.gs 는 건드리지 않음).
 * 화면은 같은 프로젝트의 HTML 파일 'DashWeb' (= 이 저장소 appsscript/DashWeb.html, PC 대시보드와 같은 화면).
 *
 * 값은 PC 대시보드가 보냅니다: '강언대시보드' 탭 A1 = {"at","n"}, A2… = 값(JSON) 조각.
 * 웹앱 버튼은 '강언대시보드명령' 탭에 한 줄 남기고, PC 가 30초 안에 읽어 실행합니다.
 *
 * 누가 무엇을
 *   링크가 있는 누구나: 보기만 (계정 메일은 가려서 보임)
 *   시트 주인(또는 스크립트 속성 DASH_VIEWERS 에 쉼표로 적은 메일, 구글 로그인 상태): 버튼까지
 *
 * 설치
 *   1. 새 파일 Dash(스크립트) + DashWeb(HTML) 추가 → 저장
 *   2. 편집기에서 setupDash 한 번 실행 (탭 두 개를 만듦)
 *   3. 배포 → 새 배포(또는 배포 관리 → 새 버전) → 유형 '웹 앱' → 실행: 나 / 액세스: 모든 사용자
 */

const DASH_TAB = '강언대시보드';
const DASH_CMD_TAB = '강언대시보드명령';
const DASH_CMDS = ['auto', 'run_now', 'check_login', 'reload',
                   'babi_auto', 'babi_run_now', 'babi_check_login', 'babi_reload'];   // 바비톡 탭

function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('DashWeb')
    .setTitle('강언/바비톡 로테이션 대시보드')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** 화면이 부름: 이 사람이 버튼을 쓸 수 있는지. */
function dashWho() {
  return { control: dashAllowed_() };
}

/** 화면이 부름: PC 가 보낸 값(JSON 글자). 없으면 빈 글자. 주인이 아니면 메일을 가림. */
function dashSnapshot() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(DASH_TAB);
  if (!sh) { setupDash(); return ''; }        // setupDash 를 안 돌렸어도 열기만 하면 탭이 생기고, PC 가 30초 안에 채움
  const head = String(sh.getRange('A1').getDisplayValue() || '');
  if (!head) return '';
  const meta = JSON.parse(head);
  if (!meta.n) return '';
  const raw = sh.getRange(2, 1, meta.n, 1).getValues().map(function (r) { return String(r[0]); }).join('');
  if (dashAllowed_()) return raw;
  // abcdef@gmail.com → abc***@gmail.com
  return raw.replace(/([A-Za-z0-9._%+-]{1,3})[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+\.[A-Za-z0-9.-]+)/g, '$1***@$2');
}

/** 화면 버튼이 부름: 명령을 남김 (PC 가 실행). 주인만. */
function dashCommand(cmd, arg) {
  if (!dashAllowed_()) throw new Error('보기 전용입니다 (버튼은 시트 주인 계정만)');
  if (DASH_CMDS.indexOf(cmd) < 0) throw new Error('모르는 명령: ' + cmd);
  const sh = dashTab_(DASH_CMD_TAB, ['시각', '명령', '인자', '보낸 사람', '처리']);
  const at = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    sh.appendRow([at, cmd, String(arg || ''), Session.getActiveUser().getEmail(), '']);
    // 오래된 줄 정리 (300줄 유지)
    const last = sh.getLastRow();
    if (last > 400) sh.deleteRows(2, last - 301);
  } finally {
    lock.releaseLock();
  }
  return 'ok';
}

/** 처음 한 번: 탭 두 개를 만듭니다. */
function setupDash() {
  const sh = dashTab_(DASH_TAB, null);
  sh.getRange('A:A').setNumberFormat('@');
  sh.setColumnWidth(1, 400);
  dashTab_(DASH_CMD_TAB, ['시각', '명령', '인자', '보낸 사람', '처리']);
}

function dashTab_(name, header) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    if (header) sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  }
  return sh;
}

/** 시트 주인(또는 DASH_VIEWERS)만 버튼. 로그인 안 한 사람·다른 계정은 메일이 비어 보기 전용. */
function dashAllowed_() {
  const me = String(Session.getActiveUser().getEmail() || '').toLowerCase();
  if (!me) return false;
  const owner = String(Session.getEffectiveUser().getEmail() || '').toLowerCase();
  const extra = String(PropertiesService.getScriptProperties().getProperty('DASH_VIEWERS') || '')
    .toLowerCase().split(',').map(function (s) { return s.trim(); }).filter(String);
  return me === owner || extra.indexOf(me) >= 0;
}
