#!/usr/bin/env python3
"""
xe-watchdog: Lightweight macOS Tahoe Iris Xe health watchdog (one-shot via LaunchAgent).
Monitors & pinpoints culprits:
  1. IntelAccelerator GPU Reset (recoveryCount increase) + top CPU/GPU processes
  2. Global GART VRAM usage (> 4.5 GB) + top GPU Helper process
  3. Any GPU Helper process RSS bloat (> 1400 MB)
  4. Crash loop (ReportCrash > 50% CPU) + culprit process
  5. ClashMi TUN spike (> 70% CPU) + top TUN traffic/connection process via 127.0.0.1:9090
Uses native XeNotify.app (clicking notification opens Activity Monitor instead of Script Editor).
"""

import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

STATE_FILE = Path("/tmp/xe-watchdog-state.json")
LOG_FILE = Path("/tmp/xe-watchdog.log")
XE_NOTIFY_APP = Path.home() / "Library/Application Support/xe-watchdog/XeNotify.app"
CLASH_PATCH_FILE = Path.home() / "Library/Group Containers/group.com.nebula.clashmi/service_core_patch_final.json"

GART_WARN_GB = 4.5
GPU_PROC_RSS_WARN_MB = 1400
REPORTCRASH_CPU_WARN = 50.0
CLASH_CPU_WARN = 70.0
PKG_TEMP_WARN_C = 95
COOLDOWN_SEC = 600  # 10 minutes per alert key


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def append_log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        lines = []
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)[-199:]
        lines.append(line)
        LOG_FILE.write_text("".join(lines), encoding="utf-8")
    except Exception:
        pass


def notify(title: str, subtitle: str, body: str, cmd: str = "") -> None:
    append_log(f"NOTIFY | {title} | {subtitle} | {body}" + (f" | CMD={cmd}" if cmd else ""))
    if XE_NOTIFY_APP.exists():
        args = [
            "open", "-g", "-n", "-a", str(XE_NOTIFY_APP), "--args",
            "--title", title, "--subtitle", subtitle, "--body", body,
        ]
        if cmd:
            args.extend(["--cmd", cmd])
        res = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return
    # Fallback only if XeNotify.app is missing
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(body)}" with title "{esc(title)}" subtitle "{esc(subtitle)}"'
    subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def should_alert(state: dict, key: str, now: float, cooldown: int = COOLDOWN_SEC) -> bool:
    last = state.get("cooldowns", {}).get(key, 0)
    if now - last < cooldown:
        return False
    state.setdefault("cooldowns", {})[key] = now
    return True


def read_pkg_temp() -> tuple:
    try:
        b = subprocess.check_output(["sysctl", "-b", "debug.xepm.sensors"], stderr=subprocess.DEVNULL)
        _, _, tjmax, pkg = struct.unpack_from("<4I", b, 0)
        return pkg, tjmax
    except Exception:
        return 0, 100


def read_gpu_stats() -> dict:
    out = subprocess.check_output(
        ["ioreg", "-r", "-c", "IntelAccelerator", "-d", "1"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    stats = {}
    for k in ("recoveryCount", "gartUsedBytes", "gartSizeBytes", "textureCount"):
        m = re.search(rf'"{k}"=(\d+)', out)
        if m:
            stats[k] = int(m.group(1))
    return stats


def read_processes() -> list:
    out = subprocess.check_output(
        ["ps", "-Ao", "pid,pcpu,rss,comm"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
            cpu = float(parts[1])
            rss_mb = int(parts[2]) / 1024.0
            comm = parts[3]
            procs.append((pid, cpu, rss_mb, comm))
        except ValueError:
            continue
    return procs


def top_cpu_summary(procs: list, limit: int = 2) -> str:
    skip = {"kernel_task", "ps", "top", "python3", "Python"}
    ranked = [
        (cpu, os.path.basename(comm))
        for _, cpu, _, comm in procs
        if os.path.basename(comm) not in skip and cpu >= 5.0
    ]
    ranked.sort(reverse=True)
    if not ranked:
        return "CPU 均正常"
    return " / ".join(f"{name} {cpu:.0f}%" for cpu, name in ranked[:limit])


def top_gpu_summary(gpu_helpers: list) -> str:
    if not gpu_helpers:
        return "无高载 GPU 进程"
    rss_mb, name, cpu, _ = sorted(gpu_helpers, reverse=True)[0]
    return f"{name} {rss_mb:.0f}MB ({cpu:.0f}%)"


def clash_top_culprit() -> str:
    try:
        cfg = json.loads(CLASH_PATCH_FILE.read_text(encoding="utf-8"))
        secret = cfg.get("secret", "")
        req = urllib.request.Request(
            "http://127.0.0.1:9090/connections",
            headers={"Authorization": f"Bearer {secret}"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        conns = data.get("connections") or []
        if not conns:
            return ""
        bytes_by_proc = Counter()
        cnt_by_proc = Counter()
        for c in conns:
            p = c.get("metadata", {}).get("process") or "unknown"
            bytes_by_proc[p] += c.get("download", 0) + c.get("upload", 0)
            cnt_by_proc[p] += 1
        top_p, top_b = bytes_by_proc.most_common(1)[0]
        return f"头号流量：{top_p} ({cnt_by_proc[top_p]}连接 / {top_b/1024/1024:.1f}MB)"
    except Exception:
        return ""


def recent_crash_name() -> str:
    dirs = [Path.home() / "Library/Logs/DiagnosticReports", Path("/Library/Logs/DiagnosticReports")]
    now = time.time()
    newest = (0.0, "")
    for d in dirs:
        if not d.exists():
            continue
        for p in d.iterdir():
            if not p.is_file() or p.suffix not in (".ips", ".diag", ".crash"):
                continue
            try:
                mt = p.stat().st_mtime
                if now - mt <= 180 and mt > newest[0]:
                    newest = (mt, p.name.split("-")[0].split("_")[0])
            except OSError:
                continue
    return newest[1]


def main() -> int:
    test_mode = "--test" in sys.argv
    now = time.time()
    state = load_state()

    gpu = read_gpu_stats()
    procs = read_processes()

    gpu_helpers = []
    reportcrash_cpu = 0.0
    clash_cpu = 0.0
    for pid, cpu, rss_mb, comm in procs:
        base = os.path.basename(comm)
        low = comm.lower()
        if "(gpu)" in low or "helper (gpu)" in low:
            gpu_helpers.append((rss_mb, base, cpu, pid))
        if base == "ReportCrash":
            reportcrash_cpu += cpu
        if "clashmiServiceSE" in comm:
            clash_cpu += cpu

    cpu_top = top_cpu_summary(procs)
    gpu_top = top_gpu_summary(gpu_helpers)

    # 1. GPU Reset detection
    rec = gpu.get("recoveryCount", 0)
    prev_rec = state.get("recoveryCount")
    if prev_rec is None:
        state["recoveryCount"] = rec
    elif rec > prev_rec:
        state["recoveryCount"] = rec
        notify(
            "Xe GPU 重置预警",
            f"GPU Reset 累计 {rec} 次 | GPU: {gpu_top}",
            f"CPU: {cpu_top}。若出现全局闪屏/残缺，请保存文件后注销重登或重启恢复。",
        )
    elif rec < prev_rec:
        state["recoveryCount"] = rec

    # 2. Global GART usage
    gart_used_gb = gpu.get("gartUsedBytes", 0) / (1024 ** 3)
    gart_total_gb = gpu.get("gartSizeBytes", 0) / (1024 ** 3)
    if gart_used_gb >= GART_WARN_GB and should_alert(state, "gart_high", now, 900):
        notify(
            "Xe 显存池偏高",
            f"GART {gart_used_gb:.2f}/{gart_total_gb:.1f} GB | {gpu_top}",
            f"CPU: {cpu_top}。建议关闭闲置重图形标签页/窗口。",
        )

    # 3. Single GPU Helper process RSS bloat
    for rss_mb, name, cpu, pid in sorted(gpu_helpers, reverse=True):
        if rss_mb >= GPU_PROC_RSS_WARN_MB:
            key = f"gpu_rss_{name}"
            if should_alert(state, key, now):
                notify(
                    "GPU 进程显存膨胀",
                    f"{name} 占 {rss_mb:.0f} MB (PID {pid}, CPU {cpu:.0f}%)",
                    f"全局 GART {gart_used_gb:.2f}GB | 点通知打开终端按回车即可重启该 GPU 进程。",
                    cmd=f'kill -TERM {pid}  # {name}',
                )
            break

    # 4. ReportCrash loop
    if reportcrash_cpu >= REPORTCRASH_CPU_WARN and should_alert(state, "reportcrash", now):
        culprit = recent_crash_name()
        extra = f"疑似 {culprit}" if culprit else "请查诊断日志"
        cmd = f'pkill -x "{culprit}"' if culprit else ""
        notify(
            "崩溃循环预警",
            f"ReportCrash {reportcrash_cpu:.0f}% ({extra})",
            f"CPU榜首: {cpu_top}。" + ("点通知打开终端按回车结束异常进程。" if cmd else "建议退出异常程序。"),
            cmd=cmd,
        )

    # 5. ClashMi CPU spike
    if clash_cpu >= CLASH_CPU_WARN and should_alert(state, "clash_cpu", now):
        top_clash = clash_top_culprit()
        body = f"{top_clash}；CPU: {cpu_top}" if top_clash else f"CPU: {cpu_top}，建议检查 ClashMi 连接表。"
        notify(
            "ClashMi TUN 占用偏高",
            f"clashmiServiceSE CPU {clash_cpu:.0f}%",
            body,
        )

    # 6. CPU Package high temperature (>= 95C)
    pkg_temp, tjmax = read_pkg_temp()
    if pkg_temp >= PKG_TEMP_WARN_C and should_alert(state, "pkg_temp_high", now):
        notify(
            "CPU 高温预警",
            f"封装温度 {pkg_temp}°C (TjMax {tjmax}°C)",
            f"CPU榜首: {cpu_top}。若持续高温可考虑清灰/更换硅脂。",
        )

    save_state(state)

    if test_mode:
        summary = (
            f"temp={pkg_temp}C, recovery={rec}, GART={gart_used_gb:.2f}/{gart_total_gb:.1f}GB, "
            f"CPU=[{cpu_top}], GPU=[{gpu_top}], Clash={clash_cpu:.1f}%"
        )
        print("WATCHDOG_OK:", summary)
        notify(
            "Xe 监控已更新（点通知待回车执行）",
            f"GART {gart_used_gb:.2f}GB | {gpu_top}",
            f"CPU: {cpu_top}。点击本通知可体验弹出终端待回车确认。",
            cmd='echo "演示成功：未结束任何进程，实际预警时会预填对应的 pkill 命令"',
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
