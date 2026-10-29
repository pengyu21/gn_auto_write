"""앱스스크립트 자동 반영 (clasp) — 코드 고친 뒤 이 파일 하나만 실행하면 시트 쪽 스크립트·웹앱이 바뀜.

    python tools/gas_deploy.py            바뀐 게 있으면 올리고 웹앱을 새 버전으로
    python tools/gas_deploy.py --check    올리지 않고 무엇이 다른지만
    python tools/gas_deploy.py --force    같아도 새 버전으로 다시 배포 (연결 확인용)

순서
  1. clasp pull — 앱스스크립트의 지금 파일을 gas/ 로 내려받음 (웹 편집기에서 직접 고친 Code.gs 를 덮어쓰지 않게)
  2. 이 저장소가 관리하는 파일만 gas/ 에 복사: appsscript/Dash.gs·Watch.gs·DashWeb.html
     (Code.gs 등 그 밖의 파일은 시트 쪽 것을 그대로 둠)
  3. 다른 게 있으면 clasp push → 새 버전 → 웹앱 배포를 그 버전으로 (주소는 그대로)

gas/ 는 공개 저장소에서 빠짐(.gitignore) — Code.gs 에 시트 정보가 있을 수 있어서.
처음 한 번: clasp login (이 PC 사용자 폴더 .clasprc.json 에 토큰), 앱스스크립트 API 사용 설정, gas/ 에 clasp clone.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAS = ROOT / "gas"
SRC = ROOT / "appsscript"
# 저장소 파일 → 앱스스크립트 파일 (clasp 는 .gs 를 .js 로 내려받음)
MANAGED = {"Dash.gs": "Dash.js", "Watch.gs": "Watch.js", "DashWeb.html": "DashWeb.html"}
CONF = GAS / "deploy.json"          # {"deployment": 웹앱 배포 ID} — 없으면 가장 최근 버전 배포를 골라 적어 둠


def clasp(*args, check=True) -> str:
    exe = shutil.which("clasp") or str(Path(os.environ.get("APPDATA", "")) / "npm" / "clasp.cmd")
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + os.pathsep + r"C:\Program Files\nodejs"
    r = subprocess.run([exe, *args], cwd=GAS, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise SystemExit(f"clasp {' '.join(args)} 실패:\n{out.strip()}")
    return out


def norm(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n") if p.exists() else ""


def deployment_id() -> str:
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))["deployment"]
    except (OSError, ValueError, KeyError):
        pass
    best = None
    for m in re.finditer(r"- (\S+) @(\d+)", clasp("list-deployments")):
        if best is None or int(m.group(2)) > best[1]:
            best = (m.group(1), int(m.group(2)))
    if not best:
        raise SystemExit("웹앱 배포를 못 찾음 — 앱스스크립트에서 한 번 '배포' 해 두세요")
    CONF.write_text(json.dumps({"deployment": best[0]}, ensure_ascii=False), encoding="utf-8")
    print(f"웹앱 배포: …{best[0][-8:]} (버전 {best[1]}) 을 이후에도 씀 — 바꾸려면 gas/deploy.json")
    return best[0]


def main():
    check_only = "--check" in sys.argv
    if not (GAS / ".clasp.json").exists():
        raise SystemExit("gas/.clasp.json 이 없음 — gas 폴더에서 clasp clone <스크립트 ID> 먼저")
    clasp("pull")
    changed = [src for src, dst in MANAGED.items() if norm(SRC / src) != norm(GAS / dst)]
    if not changed and "--force" not in sys.argv:
        print("앱스스크립트가 이미 최신입니다 (바꿀 것 없음).")
        return
    print("바뀐 파일:", ", ".join(changed))
    if check_only:
        return
    for src in changed:
        (GAS / MANAGED[src]).write_text(norm(SRC / src), encoding="utf-8")
    clasp("push", "--force")
    sys.path.insert(0, str(ROOT))
    from version import VERSION
    desc = f"v{VERSION} 자동 반영 ({', '.join(changed) or '다시 배포'})"
    out = clasp("create-version", desc)
    m = re.search(r"version (\d+)", out, re.I) or re.search(r"(\d+)", out)
    if not m:
        raise SystemExit(f"새 버전 번호를 못 읽음:\n{out}")
    ver = m.group(1)
    dep = deployment_id()
    clasp("update-deployment", dep, "-V", ver, "-d", desc)
    print(f"완료: 앱스스크립트 올림 → 버전 {ver} → 웹앱 배포 …{dep[-8:]} (주소 그대로)")


if __name__ == "__main__":
    main()
