/**
 * 강언 로테이션 멈춤 감시 — 시트에 붙은 Apps Script 에 '새 파일'로 추가합니다
 * (기존 Code.gs 는 건드리지 않음).
 *
 * 대시보드는 5분마다 '강언게시글로테이션' 탭 M1 에 'yyyy-MM-dd HH:mm' 을 적습니다.
 * 이 스크립트가 10분마다 그 시각을 보고, 15분 넘게 그대로면 메일 + 텔레그램을 보냅니다.
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
const WATCH_EVERY_MIN = 10;     // 확인 간격 (트리거)

/** 10분마다 트리거가 부릅니다. */
function watchHeartbeat() {
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
  watchNotify_('🔔 강언 로테이션 감시 시작',
    WATCH_EVERY_MIN + '분마다 확인하고, ' + WATCH_STALE_MIN + '분 넘게 신호가 없으면 알립니다.');
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
