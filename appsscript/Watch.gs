/**
 * 강언 로테이션 멈춤 감시 — 시트에 붙은 Apps Script 에 '새 파일'로 추가합니다
 * (기존 Code.gs 는 건드리지 않음).
 *
 * 대시보드는 5분마다 '강언게시글로테이션' 탭 M1 에 'yyyy-MM-dd HH:mm' 을 적습니다.
 * 이 스크립트가 5분마다 그 시각을 보고, 15분 넘게 그대로면 메일 + 텔레그램을 보냅니다.
 * 또 프로그램이 '알림' 탭에 적어 둔 업로드 완료 등을 메일로 보냅니다 (텔레그램은 프로그램이 직접).
 * 구글 서버에서 돌아서 PC 가 꺼져도, 인터넷이 끊겨도 알림이 옵니다.
 * 멈춘 동안은 1시간마다 다시 알리고, 다시 돌기 시작하면 '복구' 알림을 한 번 보냅니다.
 *
 * 설정 (토큰은 코드에 쓰지 않습니다 — 이 파일은 공개 저장소에 있음):
 *   프로젝트 설정(톱니바퀴) → 스크립트 속성 에 세 개 추가
 *     WATCH_TELEGRAM_TOKEN   텔레그램 봇 토큰
 *     WATCH_TELEGRAM_CHAT    알림 받을 대화방 번호
 *     WATCH_EMAIL            알림 받을 메일 주소
 *   그다음 편집기에서 installWatch 를 한 번 실행 → 권한 승인 → 시험 알림이 오면 끝.
 */

const WATCH_SHEET = '강언게시글로테이션';
const WATCH_CELL = 'M1';
const WATCH_STALE_MIN = 15;     // 이 시간 넘게 신호가 없으면 멈춘 것으로 봄
const WATCH_REPEAT_MIN = 60;    // 멈춘 동안 다시 알리는 간격
const WATCH_EVERY_MIN = 5;      // 확인 간격 (트리거) — 바꾸면 installWatch 를 다시 실행
const WATCH_MAIL_TAB = '알림';  // 프로그램이 업로드 완료 등을 적어 두면 여기서 메일로 보냄
const WATCH_MAIL_KEEP = 500;    // 알림 탭에 남길 줄 수

/** 트리거가 부릅니다: 보낼 메일 처리 + 멈춤 확인. */
function watchHeartbeat() {
  try { watchMailQueue_(); } catch (e) { console.error('알림 메일 처리 실패: ' + e); }
  const props = PropertiesService.getScriptProperties();
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WATCH_SHEET);
  const raw = sh ? String(sh.getRange(WATCH_CELL).getDisplayValue()).trim() : '';
  const tz = Session.getScriptTimeZone();
  let last = null;
  try { last = Utilities.parseDate(raw.slice(0, 16), tz, 'yyyy-MM-dd HH:mm'); } catch (e) { last = null; }
  const now = new Date();
  const ageMin = last ? Math.round((now.getTime() - last.getTime()) / 60000) : null;
  const alertedAt = Number(props.getProperty('WATCH_ALERTED_AT') || 0);

  if (ageMin === null || ageMin > WATCH_STALE_MIN) {
    if (!alertedAt || (now.getTime() - alertedAt) / 60000 >= WATCH_REPEAT_MIN) {
      watchNotify_('⛔ 강언 로테이션이 멈춘 것 같아요',
        '마지막 신호: ' + (raw || '없음') + (ageMin === null ? '' : ' (' + ageMin + '분 전)') + '\n' +
        'PC 전원·인터넷, 대시보드 창이 켜져 있는지 확인해 주세요.\n' +
        '멈춘 동안 ' + WATCH_REPEAT_MIN + '분마다 다시 알립니다.');
      props.setProperty('WATCH_ALERTED_AT', String(now.getTime()));
    }
  } else if (alertedAt) {
    watchNotify_('✅ 강언 로테이션 다시 동작', '마지막 신호: ' + raw);
    props.deleteProperty('WATCH_ALERTED_AT');
  }
}

/** 처음 한 번 실행: 트리거 등록 + 시험 알림 (권한 승인 창이 뜹니다). */
function installWatch() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'watchHeartbeat'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('watchHeartbeat').timeBased().everyMinutes(WATCH_EVERY_MIN).create();
  watchMailTab_();
  watchNotify_('🔔 강언 로테이션 감시 시작',
    WATCH_EVERY_MIN + '분마다 확인하고, ' + WATCH_STALE_MIN + '분 넘게 신호가 없으면 알립니다.\n' +
    '업로드 완료 메일은 \'' + WATCH_MAIL_TAB + '\' 탭을 거쳐 ' + WATCH_EVERY_MIN + '분 안에 옵니다.');
}

/** '알림' 탭 (없으면 만듦): A 시각, B 제목, C 내용, D 메일 보냄 */
function watchMailTab_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(WATCH_MAIL_TAB);
  if (!sh) {
    sh = ss.insertSheet(WATCH_MAIL_TAB);
    sh.getRange(1, 1, 1, 4).setValues([['시각', '제목', '내용', '메일 보냄']]).setFontWeight('bold');
    sh.setColumnWidth(3, 520);
  }
  return sh;
}

/** 아직 안 보낸 줄을 메일로 보내고 D 에 보낸 시각을 적습니다. 여러 건이면 한 통으로. */
function watchMailQueue_() {
  const email = PropertiesService.getScriptProperties().getProperty('WATCH_EMAIL');
  const lock = LockService.getScriptLock();       // 프로그램이 동시에 줄을 붙이는 것과 겹치지 않게
  lock.waitLock(20000);
  try {
    const sh = watchMailTab_();
    const last = sh.getLastRow();
    if (last < 2 || !email) return;
    const vals = sh.getRange(2, 1, last - 1, 4).getDisplayValues();
    const todo = [];
    vals.forEach(function (r, i) { if (r[1] && !r[3]) todo.push(i); });
    if (todo.length) {
      const subject = todo.length === 1 ? vals[todo[0]][1] : '강언 알림 ' + todo.length + '건 — ' + vals[todo[todo.length - 1]][1];
      const body = todo.map(function (i) { return vals[i][1] + '\n' + vals[i][2]; }).join('\n\n────────\n\n');
      MailApp.sendEmail(email, subject, body);
      const at = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
      todo.forEach(function (i) { sh.getRange(i + 2, 4).setValue(at); });
    }
    if (last - 1 > WATCH_MAIL_KEEP + 100) sh.deleteRows(2, last - 1 - WATCH_MAIL_KEEP);
  } finally {
    lock.releaseLock();
  }
}

/** 감시 끄기. */
function uninstallWatch() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'watchHeartbeat'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  PropertiesService.getScriptProperties().deleteProperty('WATCH_ALERTED_AT');
}

function watchNotify_(title, body) {
  const props = PropertiesService.getScriptProperties();
  const email = props.getProperty('WATCH_EMAIL');
  const token = props.getProperty('WATCH_TELEGRAM_TOKEN');
  const chat = props.getProperty('WATCH_TELEGRAM_CHAT');
  if (email) {
    try { MailApp.sendEmail(email, title, body); } catch (e) { console.error('메일 실패: ' + e); }
  }
  if (token && chat) {
    try {
      UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
        method: 'post', contentType: 'application/json', muteHttpExceptions: true,
        payload: JSON.stringify({ chat_id: chat, text: title + '\n' + body }),
      });
    } catch (e) { console.error('텔레그램 실패: ' + e); }
  }
}
