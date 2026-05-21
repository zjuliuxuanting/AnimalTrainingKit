"""
行为盒子 - 命令行调试工具

用法示例：
  python cli.py env                                # 检测环境依赖
  python cli.py detect --port /dev/cu.usbserial-xxxx  # 探测芯片信息
  python cli.py flash --port /dev/cu.xxx --bin firmware.bin --address 0x0
  python cli.py flash-multi --port /dev/cu.xxx 0x1000 bootloader.bin 0x8000 partitions.bin 0x10000 app.bin
  python cli.py erase --port /dev/cu.xxx            # 擦除Flash
  python cli.py listen --port /dev/cu.xxx            # 监听串口输出
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hardware.burner import Burner, BurnStatus
from hardware.env_installer import EnvInstaller, EnvStatus


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_env(_args: argparse.Namespace) -> int:
    installer = EnvInstaller()
    items = installer.check_all()
    rows = []
    missing = []
    for item in items:
        row = {
            "name": item.name,
            "type": item.env_type.value,
            "status": item.status.value,
            "current_version": item.current_version,
            "required_version": item.required_version,
        }
        rows.append(row)
        if item.status in (EnvStatus.NOT_INSTALLED, EnvStatus.VERSION_MISMATCH):
            missing.append(row)
    _print_json({"missing_count": len(missing), "items": rows})
    return 0 if not missing else 2


def cmd_detect(args: argparse.Namespace) -> int:
    burner = Burner()
    logs: List[str] = []

    def on_progress(progress: int, message: str):
        if args.quiet:
            return
        print(f"[{progress:3d}%] {message}")

    def on_status(status: BurnStatus, message: str):
        if args.quiet:
            return
        print(f"[状态] {status.value} {message}".rstrip())

    def on_log(message: str):
        if message.strip():
            logs.append(message)
            if not args.quiet and args.verbose:
                print(message)

    burner.set_callbacks(on_progress=on_progress, on_status=on_status, on_log=on_log)
    ok, info, output = burner.detect_device(args.port)
    payload = {
        "port": args.port,
        "success": ok,
        "device_info": asdict(info) if info else None,
        "raw": output,
    }
    if args.json:
        _print_json(payload)
    else:
        if ok and info:
            print(f"芯片类型: {info.chip_type.value}")
            if info.mac_address:
                print(f"MAC: {info.mac_address}")
            if info.flash_size:
                print(f"Flash: {info.flash_size}")
            if info.crystal_freq:
                print(f"晶振: {info.crystal_freq}")
            if info.features:
                print(f"特性: {', '.join(info.features)}")
        else:
            print("探测失败。原始输出如下：")
            print(output)
    return 0 if ok else 1


def cmd_erase(args: argparse.Namespace) -> int:
    burner = Burner()

    def on_progress(progress: int, message: str):
        if not args.quiet:
            print(f"[{progress:3d}%] {message}")

    def on_status(status: BurnStatus, message: str):
        if not args.quiet:
            print(f"[状态] {status.value} {message}".rstrip())

    def on_log(message: str):
        if not args.quiet and args.verbose and message.strip():
            print(message)

    burner.set_callbacks(on_progress=on_progress, on_status=on_status, on_log=on_log)
    result = burner.erase_flash(args.port)
    if args.json:
        _print_json(asdict(result))
    else:
        print(result.message)
    return 0 if result.success else 1


def cmd_flash(args: argparse.Namespace) -> int:
    burner = Burner()

    def on_progress(progress: int, message: str):
        if not args.quiet:
            print(f"[{progress:3d}%] {message}")

    def on_status(status: BurnStatus, message: str):
        if not args.quiet:
            print(f"[状态] {status.value} {message}".rstrip())

    def on_log(message: str):
        if not args.quiet and args.verbose and message.strip():
            print(message)

    burner.set_callbacks(on_progress=on_progress, on_status=on_status, on_log=on_log)
    result = burner.flash_firmware(
        port=args.port,
        firmware_path=args.bin,
        address=args.address,
        verify=not args.no_verify,
    )
    if args.json:
        _print_json(asdict(result))
    else:
        print(result.message)
    return 0 if result.success else 1


def _parse_flash_multi_pairs(pairs: List[str]) -> Tuple[bool, List[Tuple[str, str]], str]:
    if len(pairs) == 0 or len(pairs) % 2 != 0:
        return False, [], "参数格式错误：需要成对提供 <address> <bin_path> ..."
    files: List[Tuple[str, str]] = []
    for i in range(0, len(pairs), 2):
        addr = pairs[i]
        path = pairs[i + 1]
        files.append((addr, path))
    return True, files, ""


def cmd_flash_multi(args: argparse.Namespace) -> int:
    ok, files, msg = _parse_flash_multi_pairs(args.pairs)
    if not ok:
        print(msg, file=sys.stderr)
        return 2

    burner = Burner()

    def on_progress(progress: int, message: str):
        if not args.quiet:
            print(f"[{progress:3d}%] {message}")

    def on_status(status: BurnStatus, message: str):
        if not args.quiet:
            print(f"[状态] {status.value} {message}".rstrip())

    def on_log(message: str):
        if not args.quiet and args.verbose and message.strip():
            print(message)

    burner.set_callbacks(on_progress=on_progress, on_status=on_status, on_log=on_log)
    result = burner.flash_multiple(
        port=args.port,
        files=files,
        verify=not args.no_verify,
    )
    if args.json:
        _print_json(asdict(result))
    else:
        print(result.message)
    return 0 if result.success else 1


def cmd_listen(args: argparse.Namespace) -> int:
    try:
        import serial
    except Exception as e:
        print("缺少依赖: pyserial。请先安装: pip install pyserial", file=sys.stderr)
        return 2

    port = args.port
    baud = args.baud
    timeout = args.timeout
    seconds = args.seconds

    import time

    start = time.time()
    deadline = start + seconds

    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
    except Exception as e:
        print(f"无法打开串口 {port}: {e}", file=sys.stderr)
        return 1

    print(f"监听串口: {port} @ {baud}，持续 {seconds}s（Ctrl+C 可中断）")
    lines: List[str] = []
    try:
        if args.reset:
            try:
                ser.dtr = False
                ser.rts = True
                time.sleep(0.05)
                ser.rts = False
                time.sleep(0.05)
            except Exception:
                pass

        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            try:
                s = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:
                s = str(raw)
            if s:
                lines.append(s)
                print(s)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass

    if args.json:
        _print_json({"port": port, "baud": baud, "seconds": seconds, "lines": lines[-200:]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="behavior_box_cli", description="行为盒子命令行工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("env", help="检测环境依赖（Python包/驱动/ESP-IDF）")
    sp.set_defaults(func=cmd_env)

    sp = sub.add_parser("detect", help="探测芯片信息（esptool chip_id）")
    sp.add_argument("--port", required=True, help="串口，如 /dev/cu.xxx 或 COM3")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.add_argument("--quiet", action="store_true", help="静默（仅输出结果）")
    sp.add_argument("--verbose", action="store_true", help="输出更多日志")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("erase", help="擦除 flash（危险操作）")
    sp.add_argument("--port", required=True, help="串口")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.add_argument("--quiet", action="store_true", help="静默")
    sp.add_argument("--verbose", action="store_true", help="输出更多日志")
    sp.set_defaults(func=cmd_erase)

    sp = sub.add_parser("flash", help="烧录单个 bin 到指定地址（esptool write_flash）")
    sp.add_argument("--port", required=True, help="串口")
    sp.add_argument("--bin", required=True, help="固件 bin 文件路径")
    sp.add_argument("--address", default="0x0", help="烧录地址，默认 0x0")
    sp.add_argument("--no-verify", action="store_true", help="不校验（更快但不推荐）")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.add_argument("--quiet", action="store_true", help="静默")
    sp.add_argument("--verbose", action="store_true", help="输出更多日志")
    sp.set_defaults(func=cmd_flash)

    sp = sub.add_parser("flash-multi", help="多文件多地址烧录：<addr1> <bin1> <addr2> <bin2> ...")
    sp.add_argument("--port", required=True, help="串口")
    sp.add_argument("--no-verify", action="store_true", help="不校验（不推荐）")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.add_argument("--quiet", action="store_true", help="静默")
    sp.add_argument("--verbose", action="store_true", help="输出更多日志")
    sp.add_argument("pairs", nargs=argparse.REMAINDER, help="地址与 bin 路径成对传入")
    sp.set_defaults(func=cmd_flash_multi)

    sp = sub.add_parser("listen", help="监听串口输出（用于验证烧录后是否正常启动）")
    sp.add_argument("--port", required=True, help="串口")
    sp.add_argument("--baud", type=int, default=115200, help="波特率（默认 115200）")
    sp.add_argument("--seconds", type=int, default=8, help="监听时长秒数（默认 8）")
    sp.add_argument("--timeout", type=float, default=0.5, help="read 超时秒数（默认 0.5）")
    sp.add_argument("--reset", action="store_true", help="监听前通过RTS/DTR尝试复位设备")
    sp.add_argument("--json", action="store_true", help="JSON 输出（包含末尾若干行）")
    sp.set_defaults(func=cmd_listen)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
