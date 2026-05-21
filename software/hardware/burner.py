import os
import sys
import subprocess
import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, List, Tuple
import threading


class BurnStatus(Enum):
    IDLE = "空闲"
    CONNECTING = "正在连接"
    ERASING = "正在擦除"
    WRITING = "正在写入"
    VERIFYING = "正在校验"
    SUCCESS = "成功"
    FAILED = "失败"
    CANCELLED = "已取消"


class BurnMode(Enum):
    FULL = "full"
    LIGHT = "light"
    NONE = "none"


class ChipType(Enum):
    ESP32 = "ESP32"
    ESP32S2 = "ESP32-S2"
    ESP32S3 = "ESP32-S3"
    ESP32C3 = "ESP32-C3"
    ESP8266 = "ESP8266"
    UNKNOWN = "Unknown"


@dataclass
class DeviceInfo:
    chip_type: ChipType
    mac_address: str
    flash_size: str
    crystal_freq: str
    features: List[str]


@dataclass
class BurnResult:
    success: bool
    status: BurnStatus
    message: str
    details: str = ""


class Burner:
    FLASH_ADDRESSES = {
        ChipType.ESP32: {
            "bootloader": "0x1000",
            "partitions": "0x8000",
            "app": "0x10000",
        },
        ChipType.ESP32S2: {
            "bootloader": "0x1000",
            "partitions": "0x8000",
            "app": "0x10000",
        },
        ChipType.ESP32S3: {
            "bootloader": "0x0",
            "partitions": "0x8000",
            "app": "0x10000",
        },
        ChipType.ESP32C3: {
            "bootloader": "0x0",
            "partitions": "0x8000",
            "app": "0x10000",
        },
        ChipType.ESP8266: {
            "app": "0x0",
        },
        ChipType.UNKNOWN: {
            "app": "0x0",
        },
    }
    
    def __init__(self):
        self._status: BurnStatus = BurnStatus.IDLE
        self._port: Optional[str] = None
        self._baudrate: int = 921600
        self._process: Optional[subprocess.Popen] = None
        self._cancelled: bool = False
        self._on_progress_callback: Optional[Callable] = None
        self._on_status_callback: Optional[Callable] = None
        self._on_log_callback: Optional[Callable] = None
        self._burn_mode: BurnMode = BurnMode.NONE
        self._logger = logging.getLogger("BehaviorBox.Burner")
        self._detect_burn_mode()
    
    def _detect_burn_mode(self):
        """检测当前可用的烧录模式"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "esptool", "version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                idf_result = subprocess.run(
                    ["idf.py", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=sys.platform == "win32"
                )
                if idf_result.returncode == 0:
                    self._burn_mode = BurnMode.FULL
                    self._logger.info("检测到 ESP-IDF，使用完整烧录模式")
                else:
                    self._burn_mode = BurnMode.LIGHT
                    self._logger.info("检测到 esptool，使用轻量烧录模式")
            else:
                self._burn_mode = BurnMode.NONE
                self._logger.warning("未检测到烧录工具")
        except Exception as e:
            self._burn_mode = BurnMode.NONE
            self._logger.error(f"检测烧录模式失败: {e}")
    
    @property
    def status(self) -> BurnStatus:
        return self._status
    
    @property
    def is_busy(self) -> bool:
        return self._status in [
            BurnStatus.CONNECTING,
            BurnStatus.ERASING,
            BurnStatus.WRITING,
            BurnStatus.VERIFYING
        ]
    
    @property
    def burn_mode(self) -> BurnMode:
        return self._burn_mode
    
    @property
    def is_light_mode(self) -> bool:
        return self._burn_mode == BurnMode.LIGHT
    
    @property
    def is_full_mode(self) -> bool:
        return self._burn_mode == BurnMode.FULL
    
    def set_callbacks(self,
                      on_progress: Optional[Callable] = None,
                      on_status: Optional[Callable] = None,
                      on_log: Optional[Callable] = None):
        self._on_progress_callback = on_progress
        self._on_status_callback = on_status
        self._on_log_callback = on_log
    
    def _notify_progress(self, progress: int, message: str = ""):
        if self._on_progress_callback:
            self._on_progress_callback(progress, message)
    
    def _notify_status(self, status: BurnStatus, message: str = ""):
        self._status = status
        if self._on_status_callback:
            self._on_status_callback(status, message)
    
    def _notify_log(self, message: str):
        if self._on_log_callback:
            self._on_log_callback(message)
    
    def _run_esptool(self, args: List[str], timeout: int = 300) -> tuple[bool, str, str]:
        cmd = [sys.executable, "-m", "esptool"] + args
        self._notify_log(f"执行命令: {' '.join(cmd)}")
        
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            output_lines = []
            while True:
                if self._cancelled:
                    self._process.terminate()
                    return False, "操作已取消", ""
                
                line = self._process.stdout.readline()
                if not line and self._process.poll() is not None:
                    break
                
                if line:
                    line = line.rstrip()
                    output_lines.append(line)
                    self._notify_log(line)
                    self._parse_progress(line)
            
            return_code = self._process.returncode
            output = "\n".join(output_lines)
            
            return return_code == 0, output, ""
            
        except subprocess.TimeoutExpired:
            if self._process:
                self._process.kill()
            return False, "操作超时", ""
        except Exception as e:
            return False, f"执行错误: {str(e)}", ""
        finally:
            self._process = None
    
    def _parse_progress(self, line: str):
        progress_match = re.search(r'(\d+)%', line)
        if progress_match:
            progress = int(progress_match.group(1))
            self._notify_progress(progress, line)
        
        if 'Writing at' in line:
            self._notify_status(BurnStatus.WRITING, line)
        elif 'Erasing' in line or 'erasing' in line:
            self._notify_status(BurnStatus.ERASING, line)
        elif 'Verifying' in line or 'Hash of data' in line:
            self._notify_status(BurnStatus.VERIFYING, line)
        elif 'Connecting' in line:
            self._notify_status(BurnStatus.CONNECTING, line)
    
    def detect_device(self, port: str) -> tuple[bool, Optional[DeviceInfo], str]:
        self._notify_status(BurnStatus.CONNECTING, f"正在检测设备 {port}...")
        self._notify_progress(0, "连接设备中...")
        
        args = [
            "--port", port,
            "--baud", str(self._baudrate),
            "chip_id"
        ]
        
        success, output, _ = self._run_esptool(args)
        
        if not success:
            self._notify_status(BurnStatus.FAILED, "设备检测失败")
            return False, None, output
        
        device_info = self._parse_device_info(output)
        
        if device_info:
            self._notify_status(BurnStatus.SUCCESS, "设备检测成功")
            self._notify_progress(100, "检测完成")
            return True, device_info, output
        else:
            self._notify_status(BurnStatus.FAILED, "无法解析设备信息")
            return False, None, output
    
    def _parse_device_info(self, output: str) -> Optional[DeviceInfo]:
        chip_type = ChipType.UNKNOWN
        mac_address = ""
        flash_size = ""
        crystal_freq = ""
        features = []
        
        chip_match = re.search(r'Chip is (ESP32(?:-S2|-S3|-C3)?|ESP8266)', output, re.IGNORECASE)
        if chip_match:
            chip_name = chip_match.group(1).upper().replace('-', '')
            if chip_name == "ESP32S2":
                chip_type = ChipType.ESP32S2
            elif chip_name == "ESP32S3":
                chip_type = ChipType.ESP32S3
            elif chip_name == "ESP32C3":
                chip_type = ChipType.ESP32C3
            elif chip_name == "ESP8266":
                chip_type = ChipType.ESP8266
            else:
                chip_type = ChipType.ESP32
        
        mac_match = re.search(r'MAC: ([0-9a-fA-F:]+)', output)
        if mac_match:
            mac_address = mac_match.group(1)
        
        flash_match = re.search(r'Flash size: ([^\n]+)', output)
        if flash_match:
            flash_size = flash_match.group(1).strip()
        
        crystal_match = re.search(r'Crystal frequency: ([^\n]+)', output)
        if crystal_match:
            crystal_freq = crystal_match.group(1).strip()
        
        features_match = re.search(r'Features: ([^\n]+)', output)
        if features_match:
            features = [f.strip() for f in features_match.group(1).split(',')]
        
        if chip_type != ChipType.UNKNOWN:
            return DeviceInfo(
                chip_type=chip_type,
                mac_address=mac_address,
                flash_size=flash_size,
                crystal_freq=crystal_freq,
                features=features
            )
        
        return None
    
    def erase_flash(self, port: str) -> BurnResult:
        if self.is_busy:
            return BurnResult(False, BurnStatus.FAILED, "设备正忙，请等待当前操作完成")
        
        self._cancelled = False
        self._notify_status(BurnStatus.ERASING, "正在擦除 Flash...")
        self._notify_progress(0, "开始擦除...")
        
        args = [
            "--port", port,
            "--baud", str(self._baudrate),
            "erase_flash"
        ]
        
        success, output, _ = self._run_esptool(args, timeout=120)
        
        if self._cancelled:
            return BurnResult(False, BurnStatus.CANCELLED, "擦除已取消")
        
        if success:
            self._notify_status(BurnStatus.SUCCESS, "擦除完成")
            self._notify_progress(100, "擦除完成")
            return BurnResult(True, BurnStatus.SUCCESS, "Flash 擦除成功", output)
        else:
            self._notify_status(BurnStatus.FAILED, "擦除失败")
            return BurnResult(False, BurnStatus.FAILED, f"擦除失败: {output}", output)
    
    def flash_firmware(self, port: str, firmware_path: str, 
                       address: str = "0x0",
                       verify: bool = True) -> BurnResult:
        if self.is_busy:
            return BurnResult(False, BurnStatus.FAILED, "设备正忙，请等待当前操作完成")
        
        if not os.path.exists(firmware_path):
            return BurnResult(False, BurnStatus.FAILED, f"固件文件不存在: {firmware_path}")
        
        self._cancelled = False
        self._notify_status(BurnStatus.CONNECTING, "准备烧录...")
        self._notify_progress(0, f"固件: {os.path.basename(firmware_path)}")
        
        args = [
            "--port", port,
            "--baud", str(self._baudrate),
            "--before", "default_reset",
            "--after", "hard_reset",
            "write_flash",
            address,
            firmware_path
        ]
        
        if verify:
            args.insert(5, "--verify")
        
        success, output, _ = self._run_esptool(args)
        
        if self._cancelled:
            return BurnResult(False, BurnStatus.CANCELLED, "烧录已取消")
        
        if success:
            self._notify_status(BurnStatus.SUCCESS, "烧录完成")
            self._notify_progress(100, "烧录成功")
            return BurnResult(True, BurnStatus.SUCCESS, "固件烧录成功", output)
        else:
            self._notify_status(BurnStatus.FAILED, "烧录失败")
            return BurnResult(False, BurnStatus.FAILED, f"烧录失败: {output}", output)
    
    def flash_multiple(self, port: str, files: List[tuple], 
                       verify: bool = True) -> BurnResult:
        if self.is_busy:
            return BurnResult(False, BurnStatus.FAILED, "设备正忙，请等待当前操作完成")
        
        for address, firmware_path in files:
            if not os.path.exists(firmware_path):
                return BurnResult(False, BurnStatus.FAILED, f"固件文件不存在: {firmware_path}")
        
        self._cancelled = False
        self._notify_status(BurnStatus.CONNECTING, "准备烧录...")
        self._notify_progress(0, f"共 {len(files)} 个文件")
        
        args = [
            "--port", port,
            "--baud", str(self._baudrate),
            "--before", "default_reset",
            "--after", "hard_reset",
            "write_flash"
        ]
        
        if verify:
            args.insert(5, "--verify")
        
        for address, firmware_path in files:
            args.extend([address, firmware_path])
        
        success, output, _ = self._run_esptool(args)
        
        if self._cancelled:
            return BurnResult(False, BurnStatus.CANCELLED, "烧录已取消")
        
        if success:
            self._notify_status(BurnStatus.SUCCESS, "烧录完成")
            self._notify_progress(100, "烧录成功")
            return BurnResult(True, BurnStatus.SUCCESS, "固件烧录成功", output)
        else:
            self._notify_status(BurnStatus.FAILED, "烧录失败")
            return BurnResult(False, BurnStatus.FAILED, f"烧录失败: {output}", output)
    
    def cancel(self):
        self._cancelled = True
        if self._process:
            self._process.terminate()
        self._notify_status(BurnStatus.CANCELLED, "操作已取消")
    
    def flash_with_esptool_light(self, port: str, bin_file: str,
                       address: str = "0x0",
                       verify: bool = True,
                       baudrate: int = None) -> BurnResult:
        """
        轻量烧录模式 - 仅使用 esptool
        
        Args:
            port: 串口
            bin_file: 固件文件路径
            address: 烧录地址（默认 0x0）
            baudrate: 波特率（默认使用实例设置）
            verify: 是否验证（默认 True）
        
        Returns:
            BurnResult: 烧录结果
        """
        if self.is_busy:
            return BurnResult(False, BurnStatus.FAILED, "设备正忙，请等待当前操作完成")
        
        if self._burn_mode == BurnMode.NONE:
            return BurnResult(False, BurnStatus.FAILED, "未检测到烧录工具，请先安装 esptool")
        
        if not os.path.exists(bin_file):
            return BurnResult(False, BurnStatus.FAILED, f"固件文件不存在: {bin_file}")
        
        self._cancelled = False
        self._notify_status(BurnStatus.CONNECTING, "准备烧录 (轻量模式)...")
        self._notify_progress(0, f"固件: {os.path.basename(bin_file)}")
        
        actual_baudrate = baudrate or self._baudrate
        
        args = [
            "--port", port,
            "--baud", str(actual_baudrate),
            "--before", "default_reset",
            "--after", "hard_reset",
            "write_flash",
            address,
            bin_file
        ]
        
        if verify:
            args.insert(5, "--verify")
        
        self._logger.info(f"轻量模式烧录: {port} @ {actual_baudrate}, 地址: {address}")
        success, output, _ = self._run_esptool(args)
        
        if self._cancelled:
            return BurnResult(False, BurnStatus.CANCELLED, "烧录已取消")
        
        if success:
            self._notify_status(BurnStatus.SUCCESS, "烧录完成")
            self._notify_progress(100, "烧录成功")
            self._logger.info("轻量模式烧录成功")
            return BurnResult(True, BurnStatus.SUCCESS, "固件烧录成功 (轻量模式)", output)
        else:
            self._notify_status(BurnStatus.FAILED, "烧录失败")
            self._logger.error(f"轻量模式烧录失败: {output}")
            return BurnResult(False, BurnStatus.FAILED, f"烧录失败: {output}", output)
    
    def get_burn_mode_info(self) -> Tuple[BurnMode, str]:
        """
        获取当前烧录模式信息
        
        Returns:
            (模式, 模式描述)
        """
        if self._burn_mode == BurnMode.FULL:
            return BurnMode.FULL, "完整模式 (ESP-IDF已安装)"
        elif self._burn_mode == BurnMode.LIGHT:
            return BurnMode.LIGHT, "轻量模式 (仅 esptool)"
        else:
            return BurnMode.NONE, "不可用 (请安装 esptool)"
    
    def check_esptool_available(self) -> bool:
        """检查 esptool 是否可用"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "esptool", "version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def refresh_burn_mode(self):
        """重新检测烧录模式"""
        self._detect_burn_mode()


if __name__ == "__main__":
    import serial.tools.list_ports
    
    def on_progress(progress: int, message: str):
        print(f"[{progress}%] {message}")
    
    def on_status(status: BurnStatus, message: str):
        print(f"[状态] {status.value}: {message}")
    
    def on_log(message: str):
        if message.strip():
            print(f"  {message}")
    
    burner = Burner()
    burner.set_callbacks(
        on_progress=on_progress,
        on_status=on_status,
        on_log=on_log
    )
    
    print("=" * 60)
    print("ESP32 烧录测试")
    print("=" * 60)
    
    ports = list(serial.tools.list_ports.comports())
    esp32_port = None
    for p in ports:
        if p.vid == 0x0403 or p.vid == 0x10C4:
            esp32_port = p.device
            print(f"\n检测到设备: {p.device} ({p.description})")
            break
    
    if not esp32_port:
        print("\n未检测到 ESP32 设备")
        sys.exit(0)
    
    print("\n【设备信息检测】")
    success, device_info, _ = burner.detect_device(esp32_port)
    
    if success and device_info:
        print(f"  芯片类型: {device_info.chip_type.value}")
        print(f"  MAC 地址: {device_info.mac_address}")
        print(f"  Flash 大小: {device_info.flash_size}")
        print(f"  晶振频率: {device_info.crystal_freq}")
        if device_info.features:
            print(f"  特性: {', '.join(device_info.features)}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
