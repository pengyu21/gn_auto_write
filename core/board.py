"""adb 로 폰보드 전체를 다루는 기본 층.

xiaowei 가 adb 서버를 두 개(5037, 5038) 띄워 두고 기기를 나눠 붙입니다.
기기마다 자기 서버로 명령을 보내야 하므로 ANDROID_ADB_SERVER_PORT 를
프로세스마다 지정합니다. 서버를 띄우거나 죽이지는 않습니다 — xiaowei 것이라
죽이면 보드 전체 화면 미러링이 끊깁니다.

폰보드 번호(60~99)는 roster.csv 의 시리얼 -> 번호 표로 정합니다.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.json"
ROSTER = ROOT / "roster.csv"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_DEVICE_LINE = re.compile(r"^(\S+)\s+(device|offline|unauthorized)\s*$")


def load_settings() -> dict:
    # PowerShell 이 쓴 파일은 BOM 이 붙어 있어 utf-8-sig 로 읽습니다.
    return json.loads(SETTINGS.read_text(encoding="utf-8-sig"))


def parse_panels(sel) -> list[int]:
    """'60-99' / '60,61,70-75' / [60, 61] -> [60, 61, ...]"""
    if isinstance(sel, (list, tuple, set)):
        sel = ",".join(str(s) for s in sel)
    out = set()
    for part in re.split(r"[,\s]+", str(sel)):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


@dataclass(frozen=True)
class Device:
    serial: str
    port: int
    no: int                 # 폰보드 번호

    def __str__(self):
        return str(self.no)


@dataclass
class Result:
    dev: Device
    stdout: str
    stderr: str
    code: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.code == 0


class Board:
    def __init__(self, settings: Optional[dict] = None):
        s = settings or load_settings()
        self.adb = str(s["adb_path"])
        self.ports = [int(p) for p in s.get("adb_ports", [5037, 5038])]
        self.max_parallel = int(s.get("max_parallel", 40))
        if not Path(self.adb).is_file():
            raise FileNotFoundError(f"adb 가 없습니다: {self.adb} (settings.json 의 adb_path)")
        self._devices: Optional[list[Device]] = None

    # -- 기기 ------------------------------------------------------------------

    def devices(self, refresh: bool = False) -> list[Device]:
        """연결된(state=device) 기기 중 roster.csv 에 번호가 있는 것."""
        if self._devices is None or refresh:
            roster = _load_roster()
            found = []
            for port in self.ports:
                out = self._exec(port, ["devices"], timeout=20)[0]
                for line in out.splitlines():
                    m = _DEVICE_LINE.match(line.strip())
                    if m and m.group(2) == "device" and m.group(1) in roster:
                        found.append(Device(m.group(1), port, roster[m.group(1)]))
            self._devices = sorted(found, key=lambda d: d.no)
        return self._devices

    def select(self, panels) -> list[Device]:
        wanted = set(parse_panels(panels))
        return [d for d in self.devices() if d.no in wanted]

    # -- 명령 ------------------------------------------------------------------

    def run(self, devs: Sequence[Device], args_for: Callable[[Device], Sequence[str]],
            timeout: float = 30.0) -> list[Result]:
        """기기마다 다른 adb 인자로 한 번에 병렬 실행. 결과는 devs 순서."""
        devs = list(devs)
        if not devs:
            return []

        def one(d: Device) -> Result:
            out, err, code, to = self._exec(d.port, ["-s", d.serial, *args_for(d)], timeout)
            return Result(d, out, err, code, to)

        with ThreadPoolExecutor(max_workers=max(1, min(self.max_parallel, len(devs)))) as pool:
            return list(pool.map(one, devs))

    def shell(self, command: str, devs: Sequence[Device], timeout: float = 30.0) -> list[Result]:
        return self.run(devs, lambda d: ["shell", command], timeout)

    def tap(self, points: Iterable[tuple[Device, int, int]], timeout: float = 20.0):
        """[(기기, x, y), ...] — 기기마다 다른 자리를 동시에 누릅니다."""
        where = {d: (x, y) for d, x, y in points}
        return self.run(list(where), lambda d: ["shell", "input", "tap",
                                                str(where[d][0]), str(where[d][1])], timeout)

    def key(self, code, devs: Sequence[Device], timeout: float = 20.0):
        """키 이벤트. 4=BACK, 61=TAB, 66=ENTER, 224=화면 켜기."""
        return self.shell(f"input keyevent {code}", devs, timeout)

    def _exec(self, port: int, args: Sequence[str], timeout: float):
        env = os.environ.copy()
        env["ANDROID_ADB_SERVER_PORT"] = str(port)
        proc = subprocess.Popen([self.adb, *map(str, args)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, creationflags=_NO_WINDOW)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            out, err = proc.communicate()
        return _text(out), _text(err), proc.returncode if proc.returncode is not None else -1, timed_out


def _text(raw: Optional[bytes]) -> str:
    return (raw or b"").decode("utf-8", "replace").replace("\r\n", "\n").rstrip()


def _load_roster() -> dict[str, int]:
    """시리얼 -> 폰보드 번호."""
    out = {}
    if ROSTER.is_file():
        with open(ROSTER, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                serial, no = (row.get("Serial") or "").strip(), (row.get("No") or "").strip()
                if serial and no.isdigit():
                    out[serial] = int(no)
    return out
