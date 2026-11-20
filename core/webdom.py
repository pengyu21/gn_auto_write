"""크롬 웹 내용을 화면 구조(uiautomator dump)에 채워 넣습니다.

2026-11-20 98번: 화면에는 강남언니 페이지가 멀쩡히 보이는데 dump 에는 크롬의
'웹 보기' 껍데기만 나오고 웹 요소(id·글자·버튼)가 하나도 없었습니다. 크롬을
111 로 되돌리고 재부팅해도 같았습니다 — 크롬이 웹 내용을 접근성(dump)으로 넘겨주지
않는 폰이 생긴 것. 그래서 웹 내용은 크롬 개발자 연결(USB 디버깅 + adb forward
localabstract:chrome_devtools_remote)로 페이지에서 직접 읽어서, 크롬이 넘겨주던
것과 같은 모양의 <node> 로 만들어 dump 안에 넣습니다. 로그인·글쓰기·삭제 코드는
그대로 같은 id / 글자 / content-desc 로 찾습니다.

    resource-id  = HTML id            content-desc = aria-label (없으면 img alt)
    text         = 입력칸 값 / 선택된 항목 / 글자    class = EditText·Button·View·TextView
    clickable / enabled / bounds(화면 픽셀, 보이는 부분만)

웹 내용이 dump 에 제대로 들어 있는 폰(크롬이 넘겨주는 폰)은 건드리지 않습니다.
"""
from __future__ import annotations

import base64
import html
import json
import os
import socket
import struct
import urllib.request
from typing import Optional

CHROME = "com.android.chrome"
WEB_ROOT_DESC = {"웹 보기", "Web View", "Web view"}     # 크롬 웹 영역 껍데기 (content-desc)
PORT_BASE = 9300                                       # 폰보드 번호마다 PC 쪽 포트 9300+번호
TIMEOUT = 6.0
PAGE_TIMEOUT = 2.0                                     # 탭 하나에 기다리는 시간

# 페이지 안에서 돌리는 스크립트: 화면에 보이는 요소를 문서 순서대로 [속성…] 으로 돌려줌
_JS = r"""
(() => {
  const vw = innerWidth, vh = innerHeight, out = [];
  const INPUT = new Set(['INPUT', 'TEXTAREA']);
  const CLICK = new Set(['A', 'BUTTON', 'SELECT', 'SUMMARY', 'LABEL']);
  const own = el => { let s = ''; for (const c of el.childNodes) if (c.nodeType === 3) s += c.nodeValue; return s.replace(/\s+/g, ' ').trim(); };
  const shown = el => { const st = getComputedStyle(el); return st.visibility !== 'hidden' && st.display !== 'none' && +st.opacity !== 0; };
  // 커서가 손가락인 요소 안의 글자는 부모를 따라 손가락이 됨 — 손가락이 '시작되는' 요소만 누를 수 있다고 봄
  const pointer = el => getComputedStyle(el).cursor === 'pointer' &&
      !(el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer');
  const clickable = el => CLICK.has(el.tagName) || INPUT.has(el.tagName) || el.hasAttribute('onclick') ||
      ['button', 'link', 'tab', 'menuitem', 'option', 'checkbox', 'radio', 'switch', 'combobox'].includes(el.getAttribute('role')) ||
      pointer(el);
  const off = el => el.disabled === true || el.getAttribute('aria-disabled') === 'true' || !!el.closest('[disabled],[aria-disabled="true"]');
  // 크롬이 버튼 글자로 내보내던 이름: 자식의 aria-label / 그림 alt 가 그 자식의 글자보다 먼저
  // (마이페이지 프로필 버튼 = 아바타 '온' 이 아니라 aria-label '온세상이주황')
  const name = el => {
    const parts = [];
    for (const c of el.childNodes) {
      if (c.nodeType === 3) parts.push(c.nodeValue);
      else if (c instanceof Element && shown(c))
        parts.push(c.getAttribute('aria-label') || (c.tagName === 'IMG' ? (c.getAttribute('alt') || '') : name(c)));
    }
    return parts.join(' ').replace(/\s+/g, ' ').trim();
  };
  const walk = el => {
    if (!(el instanceof Element) || !shown(el)) return;
    const r = el.getBoundingClientRect();
    const x0 = Math.max(0, r.left), y0 = Math.max(0, r.top), x1 = Math.min(vw, r.right), y1 = Math.min(vh, r.bottom);
    const t = el.tagName, id = el.id || '', label = el.getAttribute('aria-label') || (t === 'IMG' ? (el.getAttribute('alt') || '') : '');
    let text = '', cls = 'View';
    if (INPUT.has(t)) { text = el.type === 'password' ? '•'.repeat(el.value.length) : el.value; cls = 'EditText'; }
    else if (t === 'SELECT') { text = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : ''; }
    else if (t === 'BUTTON' || t === 'A' || el.getAttribute('role') === 'button') { text = label ? '' : name(el); cls = 'Button'; }
    else { text = own(el); if (text) cls = 'TextView'; }
    if (t === 'IMG') cls = 'Image';
    const click = clickable(el);
    if ((id || label || text || click || INPUT.has(t)) && x1 > x0 && y1 > y0)
      out.push([t, id, label, text, cls, click ? 1 : 0, off(el) ? 0 : 1, x0, y0, x1, y1]);
    for (const c of el.children) walk(c);
    if (el.shadowRoot) for (const c of el.shadowRoot.children) walk(c);
  };
  walk(document.body);
  return JSON.stringify({vw, vh, dpr: devicePixelRatio, vis: document.visibilityState, url: location.href, n: out});
})()
"""


# -- adb forward / 탭 목록 --------------------------------------------------------
def _port(dev) -> int:
    return PORT_BASE + int(dev.no)


def _forward(board, dev) -> bool:
    r = board.run([dev], lambda d: ["forward", f"tcp:{_port(d)}", "localabstract:chrome_devtools_remote"])
    return bool(r) and r[0].code == 0


def _pages(dev) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{_port(dev)}/json", timeout=TIMEOUT) as r:
        return [p for p in json.loads(r.read().decode("utf-8")) if p.get("type") == "page"
                and p.get("webSocketDebuggerUrl")]


# -- 아주 작은 웹소켓 (표준 라이브러리만) ----------------------------------------------
def _ws_eval(ws_url: str, expr: str, timeout: float = TIMEOUT) -> Optional[str]:
    """ws://127.0.0.1:포트/devtools/page/ID 에 Runtime.evaluate 한 번 보내고 결과 문자열."""
    rest = ws_url.split("://", 1)[1]
    hostport, path = rest.split("/", 1)
    host, port = hostport.split(":")
    s = socket.create_connection((host, int(port)), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = s.recv(4096)
            if not chunk:
                return None
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            return None
        buf = head.split(b"\r\n\r\n", 1)[1]
        msg = json.dumps({"id": 1, "method": "Runtime.evaluate",
                          "params": {"expression": expr, "returnByValue": True}}).encode()
        hdr = bytes([0x81])
        n = len(msg)
        hdr += bytes([0x80 | n]) if n < 126 else (bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                                  else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))

        def need(k):
            nonlocal buf
            while len(buf) < k:
                chunk = s.recv(65536)
                if not chunk:
                    raise ConnectionError("closed")
                buf += chunk

        data = b""
        while True:
            need(2)
            fin, op, ln = buf[0] & 0x80, buf[0] & 0x0F, buf[1] & 0x7F
            i = 2
            if ln == 126:
                need(4); ln = struct.unpack(">H", buf[2:4])[0]; i = 4
            elif ln == 127:
                need(10); ln = struct.unpack(">Q", buf[2:10])[0]; i = 10
            need(i + ln)
            payload, buf = buf[i:i + ln], buf[i + ln:]
            if op == 8:
                return None
            if op in (0, 1):
                data += payload
                if fin:
                    reply = json.loads(data.decode("utf-8"))
                    data = b""
                    if reply.get("id") == 1:
                        return ((reply.get("result") or {}).get("result") or {}).get("value")
    finally:
        s.close()


# -- dump 에 끼워 넣기 -------------------------------------------------------------
def _attr(v) -> str:
    return html.escape(str(v), quote=True).replace("\n", "&#10;")


def needs_fill(xml: Optional[str]) -> bool:
    """크롬이 앞에 있는데 웹 영역이 비어 있으면 True."""
    if not xml or f'package="{CHROME}"' not in xml:
        return False
    if 'class="android.webkit.WebView"' in xml:       # 크롬이 웹 내용을 넘겨주는 폰
        return False
    return any(f'content-desc="{d}"' in xml for d in WEB_ROOT_DESC)


def _web_box(xml: str) -> Optional[tuple[int, int, int, int]]:
    import re
    for d in WEB_ROOT_DESC:
        m = re.search(r'<node\b[^>]*content-desc="%s"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(d), xml)
        if m:
            return tuple(int(v) for v in m.groups())
    return None


def read_page(board, dev) -> Optional[dict]:
    """보이는 탭의 요소 목록. 못 읽으면 None."""
    try:
        if not _forward(board, dev):
            return None
        pages = _pages(dev)[:12]
    except Exception:                                   # noqa: BLE001 — 못 읽으면 원래 dump 그대로
        return None
    # 뒤에 있는 탭은 크롬이 멈춰 둬서 대답이 없음 — 탭마다 짧게 기다리고 넘어감 (98번에서 한 탭 때문에 통째로 실패)
    for p in pages:
        try:
            raw = _ws_eval(p["webSocketDebuggerUrl"], _JS, timeout=PAGE_TIMEOUT)
            got = json.loads(raw) if raw else None
        except Exception:                               # noqa: BLE001
            continue
        if got and got.get("vis") == "visible":
            return got
    return None


def _web_top(xml: str, box) -> int:
    """웹 영역 위쪽 = 크롬 주소창 아래 (주소창이 숨으면 껍데기 위쪽)."""
    import re
    for rid in ("com.android.chrome:id/toolbar", "com.android.chrome:id/control_container"):
        m = re.search(r'<node\b[^>]*resource-id="%s"[^>]*bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"' % re.escape(rid), xml)
        if m:
            y1, y2 = int(m.group(2)), int(m.group(4))
            if y2 > y1 and box[1] <= y2 < box[3]:
                return y2
    return box[1]


def rows(page: dict, left: int, top: int, scale: float, bottom: int = 10 ** 6) -> list[str]:
    """bottom: 웹 영역 아래 끝 (화면 px). 그 아래로 넘친 부분은 잘라냄 — 화면 밖이라 누르면 안 됨."""
    out = []
    for tag, rid, label, text, cls, click, en, x0, y0, x1, y1 in page["n"]:
        sy0, sy1 = top + round(y0 * scale), min(bottom, top + round(y1 * scale))
        if sy1 <= sy0:
            continue
        b = f"[{left + round(x0 * scale)},{sy0}][{left + round(x1 * scale)},{sy1}]"
        klass = {"EditText": "android.widget.EditText", "Button": "android.widget.Button",
                 "TextView": "android.widget.TextView", "Image": "android.widget.Image"}.get(cls, "android.view.View")
        out.append(f'<node index="0" text="{_attr(text)}" resource-id="{_attr(rid)}" class="{klass}" '
                   f'package="{CHROME}" content-desc="{_attr(label)}" checkable="false" checked="false" '
                   f'clickable="{"true" if click else "false"}" enabled="{"true" if en else "false"}" '
                   f'focusable="{"true" if click else "false"}" focused="false" scrollable="false" '
                   f'long-clickable="false" password="false" selected="false" bounds="{b}" webdom="1" />')
    return out


def fill(board, dev, xml: str) -> str:
    """xml 의 '웹 보기' 껍데기 안에 웹 요소 <node> 들을 넣은 xml. 못 하면 원래 xml."""
    import re
    box = _web_box(xml)
    page = read_page(board, dev) if box else None
    if not page or not page.get("n"):
        return xml
    scale = (box[2] - box[0]) / max(1.0, float(page["vw"]))     # CSS px -> 화면 px
    new = rows(page, box[0], _web_top(xml, box), scale, box[3])
    m = None
    for d in WEB_ROOT_DESC:
        m = re.search(r'<node\b[^>]*content-desc="%s"[^>]*?(/?)>' % re.escape(d), xml)
        if m:
            break
    if not m:
        return xml
    head, tail = xml[:m.end()], xml[m.end():]
    if m.group(1) == "/":                                       # 자식 없는 노드면 열어서 자식으로 넣음
        return head[:-2] + ">" + "".join(new) + "</node>" + tail
    return head + "".join(new) + tail
