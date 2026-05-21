import os
import sys
import platform
import subprocess
import shutil
import webbrowser
import zipfile
import tarfile
import stat
import ctypes
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Callable, Tuple, Dict
import urllib.request
import tempfile
import re
import time

# Windows-only modules
try:
    import winreg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    winreg = None  # type: ignore


class BurnMode(Enum):
    FULL = "full"
    LIGHT = "light"
    NONE = "none"


class EnvStatus(Enum):
    INSTALLED = "已安装"
    NOT_INSTALLED = "未安装"
    VERSION_MISMATCH = "版本不匹配"
    ERROR = "检测错误"
    DEVICE_DETECTED = "设备已识别"
    NO_DEVICE = "未检测到设备"


class EnvType(Enum):
    PYTHON = "Python"
    PIP_PACKAGE = "Pip Package"
    COMPILER = "编译器"
    DRIVER = "驱动"
    TOOL = "工具"
    ESP_IDF = "ESP-IDF"


class PendingItemType(Enum):
    PIP_PACKAGE = "pip_package"
    ESP_IDF = "esp_idf"
    USB_DRIVER = "usb_driver"


@dataclass
class PendingItem:
    name: str
    item_type: PendingItemType
    status: EnvStatus
    description: str = ""
    install_url: str = ""
    manual_guide: str = ""
    driver_vid: Optional[int] = None


@dataclass
class EnvItem:
    name: str
    env_type: EnvType
    status: EnvStatus
    current_version: Optional[str] = None
    required_version: Optional[str] = None
    description: str = ""
    install_url: str = ""
    manual_guide: str = ""


class EnvInstaller:
    MIN_PYTHON_VERSION = (3, 9)
    
    COLOR_RED = "\033[91m"
    COLOR_GREEN = "\033[92m"
    COLOR_YELLOW = "\033[93m"
    COLOR_BLUE = "\033[94m"
    COLOR_MAGENTA = "\033[95m"
    COLOR_CYAN = "\033[96m"
    COLOR_RESET = "\033[0m"
    
    REQUIRED_PIP_PACKAGES = [
        ("PyQt6", "图形界面框架"),
        ("pyserial", "串口通信库"),
        ("esptool", "ESP32/ESP8266 烧录工具"),
    ]
    
    COMPILERS = {
        "esptool": {
            "description": "ESP32/ESP8266 烧录工具",
            "pip_package": "esptool",
            "manual_guide_windows": "pip install esptool",
            "manual_guide_macos": "pip3 install esptool",
        },
    }
    
    ESP_IDF_EIM_URL = "https://dl.espressif.cn/dl/eim/"
    
    MIRROR_URLS = {
        "cp210x_driver_windows": [
            "https://www.silabs.com/documents/public/software/CP210x_Windows_Drivers.zip",
            "https://www.silabs.com/documents/public/software/CP210x_VCP_Windows.zip",
        ],
        "cp210x_driver_macos": [
            "https://www.silabs.com/documents/public/software/SiLabsUSBDriverDisk.dmg",
        ],
        "ftdi_driver_windows": [
            "https://ftdichip.com/wp-content/uploads/2023/09/CDM212364_Setup.zip",
            "https://ftdichip.com/drivers/vcp-drivers/",
        ],
        "ftdi_driver_macos": [
            "https://ftdichip.com/wp-content/uploads/2023/09/FTDIUSBSerialDriver_v2_6.dmg",
        ],
    }
    
    DRIVERS = {
        "CP210x": {
            "description": "CP210x USB转串口驱动",
            "vid": 0x10C4,
            "pid": 0xEA60,
            "windows_url": "https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers",
            "macos_url": "https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers",
            "windows_registry_key": r"SYSTEM\CurrentControlSet\Services\SilabsSER",
            "macos_kext_path": "/Library/Extensions/SiLabsUSBDriver.kext",
            "manual_guide_windows": "1. 访问: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers\n2. 下载 Windows 版本\n3. 解压后运行 CP210xVCPInstaller_x64.exe",
            "manual_guide_macos": "1. 访问: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers\n2. 下载 macOS 版本\n3. 运行安装程序\n注意: macOS 可能需要在系统偏好设置中允许加载",
        },
        "FTDI": {
            "description": "FTDI USB转串口驱动",
            "vid": 0x0403,
            "pid": 0x6001,
            "windows_url": "https://ftdichip.com/drivers/vcp-drivers/",
            "macos_url": "https://ftdichip.com/drivers/vcp-drivers/",
            "windows_registry_key": r"SYSTEM\CurrentControlSet\Services\FTDIBUS",
            "macos_kext_path": "/Library/Extensions/FTDIUSBSerialDriver.kext",
            "manual_guide_windows": "1. 访问: https://ftdichip.com/drivers/vcp-drivers/\n2. 下载 Windows 版本 CDM212364_Setup.zip\n3. 解压后运行安装程序",
            "manual_guide_macos": "1. 访问: https://ftdichip.com/drivers/vcp-drivers/\n2. 下载 macOS 版本\n3. 运行安装程序",
        },
    }
    
    ESP_IDF_INFO = {
        "min_version": "5.0",
        "target_version": "5.1.2",
        "description": "ESP32 开发框架 (Espressif IoT Development Framework)",
        "install_url": "https://dl.espressif.cn/dl/eim/",
        "windows_install_dir": "esp\\esp-idf",
        "macos_install_dir": "esp/esp-idf",
        "manual_guide_windows": """【推荐】使用 ESP-IDF Installation Manager (GUI版本)

1. 访问官方下载页面:
   https://dl.espressif.cn/dl/eim/

2. 选择「GUI下载器」(图形界面版本)
   - Windows 用户选择: eim-gui-windows-x64.exe
   - 优势: 可视化安装、自动配置环境变量、一键验证

3. 运行下载的安装程序
   - 双击 eim-gui-windows-x64.exe
   - 按照向导完成安装
   - 安装程序会自动下载并配置 ESP-IDF

4. 安装完成后验证
   - 打开「ESP-IDF 5.x CMD」或「ESP-IDF 5.x PowerShell」
   - 运行: idf.py --version

【备选】命令行安装方式
1. 安装 Git for Windows: https://git-scm.com/download/win
2. 打开命令提示符，执行:
   mkdir %USERPROFILE%\\esp
   cd %USERProfile%\\esp
   git clone -b v5.3 --recursive https://github.com/espressif/esp-idf.git
3. 进入 esp-idf 目录，执行:
   install.bat esp32
4. 设置环境变量:
   export.bat
5. 验证安装:
   idf.py --version""",
        "manual_guide_macos": """【推荐】使用 ESP-IDF Installation Manager (GUI版本)

1. 访问官方下载页面:
   https://dl.espressif.cn/dl/eim/

2. 选择「GUI下载器」(图形界面版本)
   - Apple Silicon (M1/M2/M3): eim-gui-macos-aarch64.dmg
   - Intel Mac: eim-gui-macos-x64.dmg
   - 优势: 可视化安装、自动配置环境变量、一键验证

3. 运行下载的安装程序
   - 双击 DMG 文件挂载
   - 运行安装程序
   - 安装程序会自动下载并配置 ESP-IDF

4. 安装完成后验证
   - 打开终端
   - 运行: idf.py --version

【备选】命令行安装方式
1. 打开终端
2. 安装依赖:
   brew install cmake ninja dfu-util python3
3. 克隆 ESP-IDF:
   mkdir ~/esp
   cd ~/esp
   git clone -b v5.3 --recursive https://github.com/espressif/esp-idf.git
4. 运行安装脚本:
   cd ~/esp/esp-idf
   ./install.sh esp32
5. 设置环境变量 (添加到 ~/.zshrc 或 ~/.bash_profile):
   alias get_idf='. ~/esp/esp-idf/export.sh'
6. 验证安装:
   idf.py --version""",
    }
    
    def __init__(self):
        self._system = platform.system()
        self._is_windows = self._system == "Windows"
        self._is_macos = self._system == "Darwin"
        self._env_items: List[EnvItem] = []
        self._on_progress_callback: Optional[Callable] = None
        self._temp_dir: Optional[str] = None
        self._is_admin = self._check_admin_privileges()
    
    @property
    def system(self) -> str:
        return self._system
    
    @property
    def is_windows(self) -> bool:
        return self._is_windows
    
    @property
    def is_macos(self) -> bool:
        return self._is_macos
    
    @property
    def is_admin(self) -> bool:
        return self._is_admin
    
    def set_progress_callback(self, callback: Optional[Callable]):
        self._on_progress_callback = callback
    
    def _notify_progress(self, message: str, progress: int = 0):
        if self._on_progress_callback:
            self._on_progress_callback(message, progress)
    
    def _check_admin_privileges(self) -> bool:
        if self._is_windows:
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        elif self._is_macos:
            return os.geteuid() == 0
        return False
    
    def _get_temp_dir(self) -> str:
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="behaviortrain_")
        return self._temp_dir
    
    def _cleanup_temp_dir(self):
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
                self._temp_dir = None
            except Exception:
                pass
    
    def _download_file(self, url: str, dest_path: str, description: str = "文件", max_retries: int = 3) -> Tuple[bool, str]:
        self._notify_progress(f"正在下载 {description}...", 0)
        
        for retry in range(max_retries):
            try:
                if retry > 0:
                    self._notify_progress(f"重试下载 ({retry + 1}/{max_retries})...", 0)
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                req = urllib.request.Request(url, headers=headers)
                
                with urllib.request.urlopen(req, timeout=120) as response:
                    total_size = response.headers.get('Content-Length')
                    if total_size:
                        total_size = int(total_size)
                    
                    downloaded = 0
                    chunk_size = 8192
                    
                    with open(dest_path, 'wb') as f:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size:
                                progress = int((downloaded / total_size) * 80)
                                self._notify_progress(f"正在下载 {description}... {downloaded}/{total_size} bytes", progress)
                
                self._notify_progress(f"{description} 下载完成", 80)
                return True, dest_path
                
            except urllib.error.URLError as e:
                self._notify_progress(f"下载失败 (尝试 {retry + 1}/{max_retries}): {str(e)}", 0)
                if retry == max_retries - 1:
                    return False, f"下载失败: 网络错误 - {str(e)}"
                time.sleep(2)
            except Exception as e:
                self._notify_progress(f"下载失败 (尝试 {retry + 1}/{max_retries}): {str(e)}", 0)
                if retry == max_retries - 1:
                    return False, f"下载失败: {str(e)}"
                time.sleep(2)
        
        return False, f"下载失败: 已重试 {max_retries} 次"
    
    def _download_with_mirrors(self, mirror_key: str, filename: str, description: str = "文件") -> Tuple[bool, str]:
        urls = self.MIRROR_URLS.get(mirror_key, [])
        if not urls:
            return False, f"未找到 {description} 的下载地址"
        
        dest_path = os.path.join(self._get_temp_dir(), filename)
        
        for i, url in enumerate(urls):
            self._notify_progress(f"尝试下载源 {i+1}/{len(urls)}...", 0)
            success, result = self._download_file(url, dest_path, description)
            if success:
                return True, result
            self._notify_progress(f"下载源 {i+1} 失败，尝试下一个...", 0)
        
        error_msg = f"{self.COLOR_RED}【{description} 下载失败】{self.COLOR_RESET}\n\n"
        error_msg += f"{self.COLOR_YELLOW}所有下载源均无法连接，可能原因：{self.COLOR_RESET}\n"
        error_msg += "  1. 网络连接不稳定\n"
        error_msg += "  2. 防火墙阻止了下载\n"
        error_msg += "  3. 下载服务器暂时不可用\n\n"
        error_msg += f"{self.COLOR_CYAN}建议手动下载：{self.COLOR_RESET}\n"
        for i, url in enumerate(urls, 1):
            error_msg += f"  源{i}: {url}\n"
        
        return False, error_msg
    
    def _get_esp_idf_download_failure_guide(self) -> str:
        """获取 ESP-IDF 下载失败后的引导信息"""
        guide = f"\n{self.COLOR_RED}{'='*60}{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_RED}【ESP-IDF 自动下载失败】{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_RED}{'='*60}{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_GREEN}推荐手动下载 GUI 版本安装器：{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_CYAN}访问官方下载页面：{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_BLUE}https://dl.espressif.cn/dl/eim/{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_YELLOW}选择「GUI下载器」的优势：{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 图形化界面，操作简单直观\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 自动配置环境变量，无需手动设置\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 一键验证安装，确保环境正确\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 支持离线安装，网络要求更低\n\n"
        
        guide += f"{self.COLOR_MAGENTA}Windows 用户请下载：{self.COLOR_RESET}\n"
        guide += f"   eim-gui-windows-x64.exe\n\n"
        
        guide += f"{self.COLOR_CYAN}正在为您打开下载页面...{self.COLOR_RESET}\n"
        
        try:
            webbrowser.open(self.ESP_IDF_EIM_URL)
        except Exception:
            pass
        
        return guide
    
    def _run_command(self, cmd: List[str], cwd: str = None, timeout: int = 600, 
                     shell: bool = False, admin: bool = False) -> Tuple[int, str, str]:
        try:
            if admin and self._is_windows and not self._is_admin:
                if isinstance(cmd, list):
                    cmd = ' '.join(cmd)
                result = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", cmd[0] if isinstance(cmd, list) else cmd.split()[0],
                    ' '.join(cmd[1:]) if isinstance(cmd, list) else ' '.join(cmd.split()[1:]),
                    cwd, 1
                )
                return result, "", ""
            
            if self._is_windows and isinstance(cmd, list):
                cmd_str = ' '.join(f'"{c}"' if ' ' in c else c for c in cmd)
                result = subprocess.run(
                    cmd_str,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    shell=True
                )
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    shell=shell
                )
            
            return result.returncode, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return -1, "", "命令执行超时"
        except Exception as e:
            return -1, "", str(e)
    
    def check_all(self) -> List[EnvItem]:
        self._env_items = []
        
        self._notify_progress("检测 Python 环境...", 10)
        self._check_python()
        
        self._notify_progress("检测 Python 依赖包...", 25)
        self._check_pip_packages()
        
        self._notify_progress("检测编译工具...", 40)
        self._check_compilers()
        
        self._notify_progress("检测 ESP-IDF 环境...", 55)
        self._check_esp_idf()
        
        self._notify_progress("检测 USB 驱动...", 75)
        self._check_drivers()
        
        self._notify_progress("检测完成", 100)
        return self._env_items
    
    def _check_python(self):
        current_version = sys.version_info[:2]
        version_str = f"{current_version[0]}.{current_version[1]}"
        required_str = f"{self.MIN_PYTHON_VERSION[0]}.{self.MIN_PYTHON_VERSION[1]}"
        
        if current_version >= self.MIN_PYTHON_VERSION:
            status = EnvStatus.INSTALLED
        else:
            status = EnvStatus.VERSION_MISMATCH
        
        self._env_items.append(EnvItem(
            name="Python",
            env_type=EnvType.PYTHON,
            status=status,
            current_version=version_str,
            required_version=required_str,
            description="Python 运行环境",
            install_url="https://www.python.org/downloads/",
            manual_guide=self._get_python_manual_guide()
        ))
    
    def _get_python_manual_guide(self) -> str:
        if self._is_windows:
            return """1. 访问 Python 官网: https://www.python.org/downloads/
2. 下载 Python 3.9 或更高版本
3. 运行安装程序，勾选 "Add Python to PATH"
4. 完成安装后重启命令行"""
        elif self._is_macos:
            return """方式一 (推荐): 使用 Homebrew
1. 打开终端
2. 运行: brew install python@3.10

方式二: 官网下载
1. 访问: https://www.python.org/downloads/
2. 下载 macOS 版本
3. 运行安装程序"""
        return ""
    
    def _check_pip_packages(self):
        for package_name, description in self.REQUIRED_PIP_PACKAGES:
            version = self._get_pip_package_version(package_name)
            
            if version:
                status = EnvStatus.INSTALLED
            else:
                status = EnvStatus.NOT_INSTALLED
            
            self._env_items.append(EnvItem(
                name=package_name,
                env_type=EnvType.PIP_PACKAGE,
                status=status,
                current_version=version,
                description=description,
                install_url=f"pip install {package_name}",
                manual_guide=f"pip install {package_name}" if self._is_windows else f"pip3 install {package_name}"
            ))
    
    def _get_pip_package_version(self, package_name: str) -> Optional[str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Version:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None
    
    def _check_compilers(self):
        for name, info in self.COMPILERS.items():
            version = self._check_compiler_version(name)
            
            if version:
                status = EnvStatus.INSTALLED
            else:
                status = EnvStatus.NOT_INSTALLED
            
            self._env_items.append(EnvItem(
                name=name,
                env_type=EnvType.COMPILER,
                status=status,
                current_version=version,
                description=info.get("description", ""),
                install_url=info.get("windows_url", "") if self._is_windows else info.get("macos_url", ""),
                manual_guide=info.get("manual_guide_windows", "") if self._is_windows else info.get("manual_guide_macos", "")
            ))
    
    def _check_compiler_version(self, name: str) -> Optional[str]:
        try:
            if name == "esptool":
                result = subprocess.run(
                    [sys.executable, "-m", "esptool", "version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return result.stdout.strip().split("\n")[0]
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return None
    
    def _check_esp_idf(self):
        version = self._get_esp_idf_version()
        
        if version:
            min_version = tuple(map(int, self.ESP_IDF_INFO["min_version"].split(".")))
            version_tuple = self._parse_version(version)
            
            if version_tuple and version_tuple >= min_version:
                status = EnvStatus.INSTALLED
            else:
                status = EnvStatus.VERSION_MISMATCH
        else:
            status = EnvStatus.NOT_INSTALLED
        
        self._env_items.append(EnvItem(
            name="ESP-IDF",
            env_type=EnvType.ESP_IDF,
            status=status,
            current_version=version,
            required_version=self.ESP_IDF_INFO["min_version"],
            description=self.ESP_IDF_INFO["description"],
            install_url=self.ESP_IDF_INFO["install_url"],
            manual_guide=self.ESP_IDF_INFO["manual_guide_windows"] if self._is_windows else self.ESP_IDF_INFO["manual_guide_macos"]
        ))
    
    def _get_esp_idf_version(self) -> Optional[str]:
        try:
            idf_path = os.environ.get("IDF_PATH", "")
            
            result = subprocess.run(
                ["idf.py", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                shell=self._is_windows
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                match = re.search(r'(\d+\.\d+(?:\.\d+)?)', output)
                if match:
                    return match.group(1)
            
            if idf_path and os.path.exists(idf_path):
                version_file = os.path.join(idf_path, "version.txt")
                if os.path.exists(version_file):
                    with open(version_file, 'r') as f:
                        version = f.read().strip()
                        match = re.search(r'(\d+\.\d+(?:\.\d+)?)', version)
                        if match:
                            return match.group(1)
            
            common_paths = []
            if self._is_windows:
                common_paths = [
                    os.path.join(os.environ.get("USERPROFILE", ""), "esp", "esp-idf"),
                    os.path.join(os.environ.get("USERPROFILE", ""), "esp", "esp-idf-v5.1.2"),
                    "C:\\Espressif\\frameworks\\esp-idf-v5.1.2",
                ]
            else:
                common_paths = [
                    os.path.expanduser("~/esp/esp-idf"),
                    os.path.expanduser("~/esp/esp-idf-v5.1.2"),
                ]
            
            for path in common_paths:
                version_file = os.path.join(path, "version.txt")
                if os.path.exists(version_file):
                    with open(version_file, 'r') as f:
                        version = f.read().strip()
                        match = re.search(r'(\d+\.\d+(?:\.\d+)?)', version)
                        if match:
                            return match.group(1)
            
            return None
            
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
    
    def _parse_version(self, version_str: str) -> Optional[tuple]:
        try:
            parts = version_str.split(".")
            return tuple(int(p) for p in parts[:3])
        except (ValueError, AttributeError):
            return None
    
    def _check_drivers(self):
        import serial.tools.list_ports
        
        detected_devices = {}
        for port in serial.tools.list_ports.comports():
            if port.vid is not None:
                vid = int(port.vid)
                detected_devices[vid] = {
                    "port": port.device,
                    "vid": vid,
                    "pid": port.pid if port.pid else 0,
                    "description": port.description if hasattr(port, 'description') else ""
                }
        
        for name, info in self.DRIVERS.items():
            vid = info.get("vid", 0)
            if vid is not None:
                vid = int(vid)
            
            device_detected = vid in detected_devices
            
            if device_detected:
                status = EnvStatus.DEVICE_DETECTED
            else:
                driver_installed = self._check_driver_installed(name)
                if driver_installed:
                    status = EnvStatus.INSTALLED
                else:
                    status = EnvStatus.NO_DEVICE
            
            self._env_items.append(EnvItem(
                name=f"{name} 驱动",
                env_type=EnvType.DRIVER,
                status=status,
                description=info.get("description", ""),
                install_url=info.get("windows_url", "") if self._is_windows else info.get("macos_url", ""),
                manual_guide=info.get("manual_guide_windows", "") if self._is_windows else info.get("manual_guide_macos", "")
            ))
    
    def _check_driver_installed(self, driver_name: str) -> bool:
        driver_info = self.DRIVERS.get(driver_name, {})
        
        if self._is_windows:
            registry_key = driver_info.get("windows_registry_key", "")
            if registry_key:
                try:
                    if winreg is None:
                        return False
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_key)
                    winreg.CloseKey(key)
                    return True
                except OSError:
                    pass
            return False
        
        elif self._is_macos:
            kext_path = driver_info.get("macos_kext_path", "")
            if kext_path and os.path.exists(kext_path):
                return True
            return False
        
        return False
    
    def install_pip_package(self, package_name: str) -> Tuple[bool, str]:
        self._notify_progress(f"正在安装 {package_name}...", 0)
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name, "--upgrade"],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                self._notify_progress(f"{package_name} 安装成功", 100)
                return True, f"{package_name} 安装成功"
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return False, f"安装失败: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "安装超时，请检查网络连接"
        except Exception as e:
            return False, f"安装出错: {str(e)}"
    
    def install_missing_pip_packages(self) -> Tuple[int, int, List[str]]:
        success_count = 0
        fail_count = 0
        failed_packages = []
        
        for item in self._env_items:
            if item.env_type == EnvType.PIP_PACKAGE and item.status == EnvStatus.NOT_INSTALLED:
                success, msg = self.install_pip_package(item.name)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    failed_packages.append(f"{item.name}: {msg}")
        
        return success_count, fail_count, failed_packages
    
    def get_pending_items(self) -> List[PendingItem]:
        pending_items = []
        
        for item in self._env_items:
            if item.status in [EnvStatus.NOT_INSTALLED, EnvStatus.VERSION_MISMATCH]:
                if item.env_type == EnvType.PIP_PACKAGE:
                    pending_items.append(PendingItem(
                        name=item.name,
                        item_type=PendingItemType.PIP_PACKAGE,
                        status=item.status,
                        description=item.description,
                        install_url=item.install_url,
                        manual_guide=item.manual_guide
                    ))
                elif item.env_type == EnvType.ESP_IDF:
                    pending_items.append(PendingItem(
                        name=item.name,
                        item_type=PendingItemType.ESP_IDF,
                        status=item.status,
                        description=item.description,
                        install_url=item.install_url,
                        manual_guide=item.manual_guide
                    ))
                elif item.env_type == EnvType.DRIVER:
                    driver_vid = None
                    for driver_name, driver_info in self.DRIVERS.items():
                        if driver_name in item.name:
                            driver_vid = driver_info.get("vid")
                            break
                    pending_items.append(PendingItem(
                        name=item.name,
                        item_type=PendingItemType.USB_DRIVER,
                        status=item.status,
                        description=item.description,
                        install_url=item.install_url,
                        manual_guide=item.manual_guide,
                        driver_vid=driver_vid
                    ))
            elif item.status == EnvStatus.NO_DEVICE and item.env_type == EnvType.DRIVER:
                driver_vid = None
                for driver_name, driver_info in self.DRIVERS.items():
                    if driver_name in item.name:
                        driver_vid = driver_info.get("vid")
                        break
                pending_items.append(PendingItem(
                    name=item.name,
                    item_type=PendingItemType.USB_DRIVER,
                    status=item.status,
                    description=item.description,
                    install_url=item.install_url,
                    manual_guide=item.manual_guide,
                    driver_vid=driver_vid
                ))
        
        return pending_items
    
    def install_esp_idf_windows(self) -> Tuple[bool, str]:
        self._notify_progress(f"{self.COLOR_BLUE}开始安装 ESP-IDF (Windows)...{self.COLOR_RESET}", 0)
        
        target_version = self.ESP_IDF_INFO["target_version"]
        install_dir = os.path.join(os.environ.get("USERPROFILE", ""), 
                                   self.ESP_IDF_INFO["windows_install_dir"])
        
        installer_path = None
        user_profile = os.environ.get("USERPROFILE", "")
        download_dir = os.path.join(user_profile, "Downloads")
        common_dirs = [user_profile, download_dir, self._get_temp_dir()]
        
        for search_dir in common_dirs:
            if not os.path.exists(search_dir):
                continue
            for file in os.listdir(search_dir):
                if file.startswith("esp-idf-tools-setup") and file.endswith(".exe"):
                    installer_path = os.path.join(search_dir, file)
                    self._notify_progress(f"{self.COLOR_GREEN}发现本地安装包: {file}{self.COLOR_RESET}", 10)
                    break
            if installer_path:
                break
        
        if not installer_path:
            self._notify_progress(f"{self.COLOR_YELLOW}ESP-IDF 自动下载功能已停用{self.COLOR_RESET}", 10)
            self._notify_progress(f"{self.COLOR_YELLOW}请使用官方 GUI 安装器进行安装...{self.COLOR_RESET}", 20)
            
            guide = self._get_esp_idf_download_failure_guide()
            esptool_success, esptool_msg = self.install_esptool_only()
            if esptool_success:
                return True, f"{self.COLOR_YELLOW}【ESP-IDF 需手动安装，已启用轻量烧录模式】{self.COLOR_RESET}\n\n{self.COLOR_GREEN}esptool 已安装，核心烧录功能可用{self.COLOR_RESET}\n{guide}"
            else:
                return False, f"{self.COLOR_RED}【ESP-IDF 和 esptool 均安装失败】{self.COLOR_RESET}\n{guide}"
        
        self._notify_progress("正在运行 ESP-IDF 安装程序...", 50)
        
        silent_cmd = [
            installer_path,
            "/verysilent",
            "/norestart",
            f'/dir="{install_dir}"'
        ]
        
        returncode, stdout, stderr = self._run_command(silent_cmd, timeout=1800)
        
        if returncode != 0:
            self._notify_progress(f"{self.COLOR_YELLOW}静默安装失败，尝试交互式安装...{self.COLOR_RESET}", 60)
            try:
                subprocess.Popen([installer_path], shell=True)
                return True, f"{self.COLOR_CYAN}已启动 ESP-IDF 安装程序，请在弹出的窗口中完成安装{self.COLOR_RESET}"
            except Exception as e:
                self._notify_progress(f"{self.COLOR_YELLOW}ESP-IDF 安装失败，启用轻量烧录模式...{self.COLOR_RESET}", 70)
                esptool_success, esptool_msg = self.install_esptool_only()
                if esptool_success:
                    guide = self._get_esp_idf_download_failure_guide()
                    return True, f"{self.COLOR_YELLOW}【ESP-IDF 安装失败，已启用轻量烧录模式】{self.COLOR_RESET}\n{guide}"
                guide = self._get_esp_idf_download_failure_guide()
                return False, f"{self.COLOR_RED}【ESP-IDF 安装失败】{self.COLOR_RESET}\n错误: {str(e)}\n{guide}"
        
        self._notify_progress(f"{self.COLOR_GREEN}ESP-IDF 安装完成，正在验证...{self.COLOR_RESET}", 80)
        
        idf_path = os.path.join(install_dir, "esp-idf")
        export_bat = os.path.join(idf_path, "export.bat")
        
        if os.path.exists(export_bat):
            verify_cmd = f'call "{export_bat}" && idf.py --version'
            returncode, stdout, stderr = self._run_command(
                ["cmd", "/c", verify_cmd],
                timeout=60
            )
            
            if returncode == 0:
                self._notify_progress(f"{self.COLOR_GREEN}ESP-IDF 安装验证成功{self.COLOR_RESET}", 100)
                return True, f"{self.COLOR_GREEN}【ESP-IDF v{target_version} 安装成功】{self.COLOR_RESET}"
        
        self._notify_progress(f"{self.COLOR_GREEN}ESP-IDF 安装完成，请重启终端后验证{self.COLOR_RESET}", 100)
        return True, f"{self.COLOR_GREEN}ESP-IDF 安装完成{self.COLOR_RESET}\n安装目录: {install_dir}"
    
    def install_esp_idf_macos(self) -> Tuple[bool, str]:
        self._notify_progress("开始安装 ESP-IDF (macOS)...", 0)
        
        target_version = self.ESP_IDF_INFO["target_version"]
        install_dir = os.path.expanduser(f"~/{self.ESP_IDF_INFO['macos_install_dir']}")
        
        self._notify_progress("正在检查 Homebrew...", 5)
        returncode, _, _ = self._run_command(["brew", "--version"], timeout=30)
        
        if returncode != 0:
            self._notify_progress("正在安装 Homebrew...", 10)
            brew_install = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            returncode, stdout, stderr = self._run_command(
                ["bash", "-c", brew_install],
                timeout=600
            )
            
            if returncode != 0:
                return False, "Homebrew 安装失败，请手动安装 Homebrew 后重试"
        
        self._notify_progress("正在安装依赖工具...", 15)
        deps = ["cmake", "ninja", "dfu-util", "python3"]
        for dep in deps:
            self._notify_progress(f"正在安装 {dep}...", 20)
            self._run_command(["brew", "install", dep], timeout=300)
        
        self._notify_progress("正在克隆 ESP-IDF 仓库...", 30)
        
        if os.path.exists(install_dir):
            shutil.rmtree(install_dir)
        
        os.makedirs(os.path.dirname(install_dir), exist_ok=True)
        
        clone_cmd = [
            "git", "clone",
            "-b", f"v{target_version}",
            "--recursive",
            "--depth", "1",
            "https://github.com/espressif/esp-idf.git",
            install_dir
        ]
        
        returncode, stdout, stderr = self._run_command(clone_cmd, timeout=1800)
        
        if returncode != 0:
            return False, f"克隆 ESP-IDF 仓库失败: {stderr}"
        
        self._notify_progress("正在运行 ESP-IDF 安装脚本...", 60)
        
        install_sh = os.path.join(install_dir, "install.sh")
        os.chmod(install_sh, os.stat(install_sh).st_mode | stat.S_IEXEC)
        
        returncode, stdout, stderr = self._run_command(
            ["./install.sh", "esp32"],
            cwd=install_dir,
            timeout=1800
        )
        
        if returncode != 0:
            return False, f"ESP-IDF 安装脚本执行失败: {stderr}"
        
        self._notify_progress("正在配置环境变量...", 80)
        
        shell_rc = os.path.expanduser("~/.zshrc")
        if not os.path.exists(shell_rc):
            shell_rc = os.path.expanduser("~/.bash_profile")
        
        idf_alias = f'\n# ESP-IDF\nalias get_idf=". {install_dir}/export.sh"\n'
        idf_path_export = f'export IDF_PATH="{install_dir}"\n'
        
        with open(shell_rc, 'a') as f:
            f.write(idf_alias)
            f.write(idf_path_export)
        
        self._notify_progress("正在验证安装...", 90)
        
        export_sh = os.path.join(install_dir, "export.sh")
        verify_cmd = f'source {export_sh} && idf.py --version'
        
        returncode, stdout, stderr = self._run_command(
            ["bash", "-c", verify_cmd],
            timeout=60
        )
        
        if returncode == 0:
            self._notify_progress("ESP-IDF 安装验证成功", 100)
            return True, f"ESP-IDF v{target_version} 安装成功，请重启终端后运行 'get_idf' 激活环境"
        
        self._notify_progress("ESP-IDF 安装完成", 100)
        return True, f"ESP-IDF 安装完成，请重启终端后运行 'get_idf' 激活环境"
    
    def install_esp_idf(self) -> Tuple[bool, str, str]:
        if self._is_windows:
            success, msg = self.install_esp_idf_windows()
            return success, msg, "auto" if success else "error"
        elif self._is_macos:
            success, msg = self.install_esp_idf_macos()
            return success, msg, "auto" if success else "error"
        else:
            return False, "不支持的操作系统", "error"
    
    def install_usb_driver_windows(self, driver_name: str) -> Tuple[bool, str]:
        self._notify_progress(f"{self.COLOR_BLUE}开始安装 {driver_name} 驱动 (Windows)...{self.COLOR_RESET}", 0)
        
        driver_info = self.DRIVERS.get(driver_name, {})
        
        if not self._is_admin:
            self._notify_progress(f"{self.COLOR_YELLOW}检测到无管理员权限，尝试提权...{self.COLOR_RESET}", 5)
            has_admin, admin_msg = self.check_admin_and_prompt()
            if not has_admin:
                self._notify_progress(f"{self.COLOR_RED}无法自动提权，显示手动安装指南...{self.COLOR_RESET}", 10)
                guide = self._get_driver_manual_guide(driver_name)
                return False, f"{self.COLOR_RED}【需要管理员权限安装驱动】{self.COLOR_RESET}\n\n{guide}"
        
        if driver_name == "CP210x":
            return self._install_cp210x_windows(driver_info)
        elif driver_name == "FTDI":
            return self._install_ftdi_windows(driver_info)
        else:
            return False, f"{self.COLOR_RED}未知的驱动类型: {driver_name}{self.COLOR_RESET}"
    
    def _install_cp210x_windows(self, driver_info: Dict) -> Tuple[bool, str]:
        self._notify_progress("正在下载 CP210x 驱动...", 10)
        
        success, result = self._download_with_mirrors(
            "cp210x_driver_windows",
            "CP210x_Windows_Drivers.zip",
            "CP210x 驱动"
        )
        
        if not success:
            self._notify_progress(f"{self.COLOR_RED}驱动下载失败{self.COLOR_RESET}", 15)
            guide = self._get_driver_manual_guide("CP210x")
            return False, f"{result}\n\n{guide}"
        
        zip_path = result
        extract_dir = os.path.join(self._get_temp_dir(), "cp210x_driver")
        
        self._notify_progress("正在解压驱动文件...", 30)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            self._notify_progress(f"{self.COLOR_RED}解压失败{self.COLOR_RESET}", 35)
            guide = self._get_driver_manual_guide("CP210x")
            return False, f"{self.COLOR_RED}【解压驱动文件失败】{self.COLOR_RESET}\n错误: {str(e)}\n\n{guide}"
        
        inf_file = None
        exe_file = None
        
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                file_lower = file.lower()
                if file_lower.endswith('.inf') and 'cp210x' in file_lower:
                    inf_file = os.path.join(root, file)
                elif file_lower.endswith('.exe'):
                    exe_file = os.path.join(root, file)
        
        if exe_file:
            self._notify_progress("正在运行驱动安装程序...", 50)
            returncode, stdout, stderr = self._run_command(
                [exe_file, "/silent"],
                timeout=120
            )
            
            self._notify_progress(f"安装程序返回码: {returncode}", 55)
            if stdout:
                self._notify_progress(f"安装输出: {stdout[:200]}", 56)
            
            if returncode == 0:
                self._notify_progress(f"{self.COLOR_GREEN}驱动安装完成{self.COLOR_RESET}", 80)
                if self._check_driver_installed("CP210x"):
                    self._notify_progress(f"{self.COLOR_GREEN}CP210x 驱动安装成功{self.COLOR_RESET}", 100)
                    return True, f"{self.COLOR_GREEN}【CP210x 驱动安装成功】{self.COLOR_RESET}"
                else:
                    return True, f"{self.COLOR_YELLOW}CP210x 驱动安装程序已执行，请重新插拔设备后验证{self.COLOR_RESET}"
            else:
                self._notify_progress(f"{self.COLOR_YELLOW}安装程序执行失败，尝试 PNPUtil...{self.COLOR_RESET}", 60)
        
        if inf_file:
            self._notify_progress(f"正在安装驱动 (PNPUtil): {inf_file}", 50)
            
            pnputil_cmd = ["pnputil", "/add-driver", inf_file, "/install", "/subdirs"]
            returncode, stdout, stderr = self._run_command(pnputil_cmd, timeout=60)
            
            self._notify_progress(f"PNPUtil 返回码: {returncode}", 55)
            if stdout:
                self._notify_progress(f"PNPUtil 输出: {stdout[:300]}", 56)
            if stderr:
                self._notify_progress(f"PNPUtil 错误: {stderr[:200]}", 57)
            
            if returncode == 0:
                self._notify_progress(f"{self.COLOR_GREEN}驱动安装完成{self.COLOR_RESET}", 80)
                if self._check_driver_installed("CP210x"):
                    self._notify_progress(f"{self.COLOR_GREEN}CP210x 驱动安装成功{self.COLOR_RESET}", 100)
                    return True, f"{self.COLOR_GREEN}【CP210x 驱动安装成功】{self.COLOR_RESET}"
                else:
                    return True, f"{self.COLOR_YELLOW}CP210x 驱动已安装，请重新插拔设备后验证{self.COLOR_RESET}"
            
            self._notify_progress(f"{self.COLOR_RED}PNPUtil 安装失败{self.COLOR_RESET}", 70)
            guide = self._get_driver_manual_guide("CP210x")
            return False, f"{self.COLOR_RED}【驱动自动安装失败】{self.COLOR_RESET}\n错误: {stderr}\n\n{guide}"
        
        self._notify_progress(f"{self.COLOR_RED}未找到驱动安装文件{self.COLOR_RESET}", 80)
        guide = self._get_driver_manual_guide("CP210x")
        return False, f"{self.COLOR_RED}【未找到驱动安装文件】{self.COLOR_RESET}\n\n{guide}"
    
    def _install_ftdi_windows(self, driver_info: Dict) -> Tuple[bool, str]:
        self._notify_progress(f"{self.COLOR_BLUE}正在下载 FTDI 驱动...{self.COLOR_RESET}", 10)
        
        success, result = self._download_with_mirrors(
            "ftdi_driver_windows",
            "CDM212364_Setup.zip",
            "FTDI 驱动"
        )
        
        if not success:
            self._notify_progress(f"{self.COLOR_RED}FTDI 驱动下载失败{self.COLOR_RESET}", 15)
            guide = self._get_driver_manual_guide("FTDI")
            return False, f"{result}\n\n{guide}"
        
        zip_path = result
        extract_dir = os.path.join(self._get_temp_dir(), "ftdi_driver")
        
        self._notify_progress("正在解压驱动文件...", 30)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            self._notify_progress(f"{self.COLOR_RED}解压失败{self.COLOR_RESET}", 35)
            guide = self._get_driver_manual_guide("FTDI")
            return False, f"{self.COLOR_RED}【解压驱动文件失败】{self.COLOR_RESET}\n错误: {str(e)}\n\n{guide}"
        
        exe_file = None
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.lower().endswith('.exe'):
                    exe_file = os.path.join(root, file)
                    break
            if exe_file:
                break
        
        if not exe_file:
            self._notify_progress(f"{self.COLOR_RED}未找到驱动安装程序{self.COLOR_RESET}", 50)
            guide = self._get_driver_manual_guide("FTDI")
            return False, f"{self.COLOR_RED}【未找到驱动安装程序】{self.COLOR_RESET}\n\n{guide}"
        
        self._notify_progress("正在运行驱动安装程序...", 50)
        
        returncode, stdout, stderr = self._run_command(
            [exe_file, "-silent"],
            timeout=120
        )
        
        self._notify_progress(f"安装程序返回码: {returncode}", 55)
        if stdout:
            self._notify_progress(f"安装输出: {stdout[:200]}", 56)
        
        if returncode == 0:
            self._notify_progress(f"{self.COLOR_GREEN}驱动安装完成，正在验证...{self.COLOR_RESET}", 80)
            if self._check_driver_installed("FTDI"):
                self._notify_progress(f"{self.COLOR_GREEN}FTDI 驱动安装成功{self.COLOR_RESET}", 100)
                return True, f"{self.COLOR_GREEN}【FTDI 驱动安装成功】{self.COLOR_RESET}"
            else:
                return True, f"{self.COLOR_YELLOW}FTDI 驱动安装程序已执行，请重新插拔设备后验证{self.COLOR_RESET}"
        
        self._notify_progress(f"{self.COLOR_RED}驱动安装失败{self.COLOR_RESET}", 70)
        guide = self._get_driver_manual_guide("FTDI")
        return False, f"{self.COLOR_RED}【驱动自动安装失败】{self.COLOR_RESET}\n错误: {stderr}\n\n{guide}"
    
    def install_usb_driver_macos(self, driver_name: str) -> Tuple[bool, str]:
        self._notify_progress(f"开始安装 {driver_name} 驱动 (macOS)...", 0)
        
        driver_info = self.DRIVERS.get(driver_name, {})
        
        if driver_name == "CP210x":
            return self._install_cp210x_macos(driver_info)
        elif driver_name == "FTDI":
            return self._install_ftdi_macos(driver_info)
        else:
            return False, f"未知的驱动类型: {driver_name}"
    
    def _install_cp210x_macos(self, driver_info: Dict) -> Tuple[bool, str]:
        self._notify_progress("正在下载 CP210x 驱动...", 10)
        
        success, result = self._download_with_mirrors(
            "cp210x_driver_macos",
            "SiLabsUSBDriverDisk.dmg",
            "CP210x 驱动"
        )
        
        if not success:
            return False, f"下载 CP210x 驱动失败: {result}"
        
        dmg_path = result
        
        self._notify_progress("正在挂载 DMG...", 30)
        
        returncode, stdout, stderr = self._run_command(
            ["hdiutil", "attach", dmg_path],
            timeout=60
        )
        
        if returncode != 0:
            return False, f"挂载 DMG 失败: {stderr}"
        
        mount_point = None
        for line in stdout.split('\n'):
            if '/Volumes/' in line:
                parts = line.split()
                mount_point = parts[-1] if parts else None
                break
        
        if not mount_point:
            return False, "无法找到挂载点"
        
        self._notify_progress("正在查找安装包...", 40)
        
        pkg_file = None
        for file in os.listdir(mount_point):
            if file.endswith('.pkg'):
                pkg_file = os.path.join(mount_point, file)
                break
        
        if not pkg_file:
            self._run_command(["hdiutil", "detach", mount_point], timeout=30)
            return False, "未找到安装包"
        
        self._notify_progress("正在安装驱动 (需要管理员权限)...", 50)
        
        returncode, stdout, stderr = self._run_command(
            ["sudo", "installer", "-pkg", pkg_file, "-target", "/"],
            timeout=120
        )
        
        self._run_command(["hdiutil", "detach", mount_point], timeout=30)
        
        if returncode == 0:
            self._notify_progress("驱动安装完成，正在验证...", 80)
            if self._check_driver_installed("CP210x"):
                self._notify_progress("CP210x 驱动安装成功", 100)
                return True, "CP210x 驱动安装成功，请重新插拔设备"
            else:
                return True, "CP210x 驱动已安装，可能需要在系统偏好设置中允许加载"
        
        return False, f"驱动安装失败: {stderr}"
    
    def _install_ftdi_macos(self, driver_info: Dict) -> Tuple[bool, str]:
        self._notify_progress("正在下载 FTDI 驱动...", 10)
        
        success, result = self._download_with_mirrors(
            "ftdi_driver_macos",
            "FTDIUSBSerialDriver.dmg",
            "FTDI 驱动"
        )
        
        if not success:
            return False, f"下载 FTDI 驱动失败: {result}"
        
        dmg_path = result
        
        self._notify_progress("正在挂载 DMG...", 30)
        
        returncode, stdout, stderr = self._run_command(
            ["hdiutil", "attach", dmg_path],
            timeout=60
        )
        
        if returncode != 0:
            return False, f"挂载 DMG 失败: {stderr}"
        
        mount_point = None
        for line in stdout.split('\n'):
            if '/Volumes/' in line:
                parts = line.split()
                mount_point = parts[-1] if parts else None
                break
        
        if not mount_point:
            return False, "无法找到挂载点"
        
        self._notify_progress("正在查找安装包...", 40)
        
        pkg_file = None
        for file in os.listdir(mount_point):
            if file.endswith('.pkg'):
                pkg_file = os.path.join(mount_point, file)
                break
        
        if not pkg_file:
            self._run_command(["hdiutil", "detach", mount_point], timeout=30)
            return False, "未找到安装包"
        
        self._notify_progress("正在安装驱动 (需要管理员权限)...", 50)
        
        returncode, stdout, stderr = self._run_command(
            ["sudo", "installer", "-pkg", pkg_file, "-target", "/"],
            timeout=120
        )
        
        self._run_command(["hdiutil", "detach", mount_point], timeout=30)
        
        if returncode == 0:
            self._notify_progress("驱动安装完成，正在验证...", 80)
            if self._check_driver_installed("FTDI"):
                self._notify_progress("FTDI 驱动安装成功", 100)
                return True, "FTDI 驱动安装成功，请重新插拔设备"
            else:
                return True, "FTDI 驱动已安装，可能需要在系统偏好设置中允许加载"
        
        return False, f"驱动安装失败: {stderr}"
    
    def install_usb_driver(self, driver_name: str, driver_info: Dict = None) -> Tuple[bool, str, str]:
        if driver_info is None:
            driver_info = self.DRIVERS.get(driver_name, {})
        
        if self._is_windows:
            success, msg = self.install_usb_driver_windows(driver_name)
            return success, msg, "auto" if success else "error"
        elif self._is_macos:
            success, msg = self.install_usb_driver_macos(driver_name)
            return success, msg, "auto" if success else "error"
        else:
            return False, "不支持的操作系统", "error"
    
    def verify_driver_install(self, driver_name: str) -> Tuple[bool, str]:
        driver_info = self.DRIVERS.get(driver_name, {})
        
        if self._check_driver_installed(driver_name):
            return True, f"{driver_name} 驱动已正确安装"
        
        import serial.tools.list_ports
        vid = driver_info.get("vid", 0)
        
        for port in serial.tools.list_ports.comports():
            if port.vid == vid:
                return True, f"{driver_name} 设备已识别"
        
        return False, f"{driver_name} 驱动未检测到，请检查安装"
    
    def install_missing_envs(self) -> Dict[str, Dict]:
        results = {
            "pip_package": {"success": 0, "fail": 0, "failed": [], "manual": []},
            "esp_idf": {"success": 0, "fail": 0, "failed": [], "manual": [], "downgraded": False},
            "usb_driver": {"success": 0, "fail": 0, "failed": [], "manual": []}
        }
        
        pending_items = self.get_pending_items()
        
        if not pending_items:
            return results
        
        pip_items = [item for item in pending_items if item.item_type == PendingItemType.PIP_PACKAGE]
        esp_idf_items = [item for item in pending_items if item.item_type == PendingItemType.ESP_IDF]
        driver_items = [item for item in pending_items if item.item_type == PendingItemType.USB_DRIVER]
        
        total_items = len(pending_items)
        processed = 0
        
        for item in pip_items:
            processed += 1
            progress = int((processed / total_items) * 100)
            self._notify_progress(f"正在安装 Python 包: {item.name}...", progress)
            
            success, msg = self.install_pip_package(item.name)
            if success:
                results["pip_package"]["success"] += 1
            else:
                results["pip_package"]["fail"] += 1
                results["pip_package"]["failed"].append(f"{item.name}: {msg}")
        
        for item in driver_items:
            processed += 1
            progress = int((processed / total_items) * 100)
            driver_name = item.name.replace(" 驱动", "")
            self._notify_progress(f"正在安装 {driver_name} 驱动...", progress)
            
            success, msg, install_type = self.install_usb_driver(driver_name)
            if success:
                results["usb_driver"]["success"] += 1
            else:
                results["usb_driver"]["fail"] += 1
                results["usb_driver"]["failed"].append(f"{item.name}: {msg}")
                if "手动安装指南" in msg:
                    results["usb_driver"]["manual"].append({"name": item.name, "message": msg})
        
        for item in esp_idf_items:
            processed += 1
            progress = int((processed / total_items) * 100)
            self._notify_progress(f"正在安装 ESP-IDF...", progress)
            
            success, msg, install_type = self.install_esp_idf()
            if success:
                if "轻量烧录模式" in msg:
                    results["esp_idf"]["downgraded"] = True
                    results["esp_idf"]["manual"].append({"name": item.name, "message": msg})
                else:
                    results["esp_idf"]["success"] += 1
            else:
                results["esp_idf"]["fail"] += 1
                results["esp_idf"]["failed"].append(f"{item.name}: {msg}")
        
        self._cleanup_temp_dir()
        
        return results
    
    def get_missing_items(self) -> List[EnvItem]:
        return [item for item in self._env_items 
                if item.status in [EnvStatus.NOT_INSTALLED, EnvStatus.VERSION_MISMATCH]]
    
    def get_manual_guide(self, item_name: str) -> str:
        for item in self._env_items:
            if item.name == item_name:
                guide = f"【{item.name}】手动安装指南\n\n"
                guide += f"类型: {item.env_type.value}\n"
                guide += f"状态: {item.status.value}\n"
                if item.current_version:
                    guide += f"当前版本: {item.current_version}\n"
                if item.required_version:
                    guide += f"要求版本: {item.required_version}\n"
                guide += f"\n安装步骤:\n{item.manual_guide}\n"
                if item.install_url:
                    guide += f"\n下载地址: {item.install_url}"
                return guide
        return "未找到该项环境信息"
    
    def get_all_manual_guides(self) -> str:
        missing_items = self.get_missing_items()
        if not missing_items:
            return "所有环境已安装完成，无需手动安装。"
        
        guides = []
        for item in missing_items:
            guide = f"\n{'='*50}\n"
            guide += f"【{item.name}】\n"
            guide += f"类型: {item.env_type.value}\n"
            guide += f"状态: {item.status.value}\n"
            if item.current_version:
                guide += f"当前版本: {item.current_version}\n"
            if item.required_version:
                guide += f"要求版本: {item.required_version}\n"
            guide += f"\n安装步骤:\n{item.manual_guide}\n"
            if item.install_url:
                guide += f"\n下载地址: {item.install_url}"
            guides.append(guide)
        
        return "\n".join(guides)
    
    def generate_report(self) -> str:
        report = []
        report.append("=" * 60)
        report.append("环境检测报告")
        report.append(f"系统: {self._system}")
        report.append("=" * 60)
        
        current_type = None
        for item in self._env_items:
            if item.env_type != current_type:
                current_type = item.env_type
                report.append(f"\n【{current_type.value}】")
            
            if item.status == EnvStatus.INSTALLED:
                status_icon = "✓"
            elif item.status == EnvStatus.DEVICE_DETECTED:
                status_icon = "✓"
            else:
                status_icon = "✗"
            
            version_info = ""
            if item.current_version:
                version_info = f" ({item.current_version})"
                if item.required_version and item.status == EnvStatus.VERSION_MISMATCH:
                    version_info += f" [需要 {item.required_version}]"
            
            report.append(f"  {status_icon} {item.name}{version_info}: {item.status.value}")
        
        missing_count = len(self.get_missing_items())
        report.append("\n" + "=" * 60)
        report.append(f"检测结果: {missing_count} 项需要安装")
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def check_admin_and_prompt(self) -> Tuple[bool, str]:
        if self._is_admin:
            return True, "已具有管理员权限"
        
        if self._is_windows:
            return False, "请以管理员身份重新运行程序（右键点击程序 -> 以管理员身份运行）"
        elif self._is_macos:
            return False, "请使用 sudo 运行程序，或输入管理员密码授权"
        
        return False, "需要管理员权限"
    
    def get_burn_mode(self) -> BurnMode:
        """
        获取当前可用的烧录模式
        
        Returns:
            BurnMode.FULL: ESP-IDF已安装，支持完整功能
            BurnMode.LIGHT: 仅esptool可用，支持轻量烧录
            BurnMode.NONE: 均不可用
        """
        esp_idf_installed = self._check_esp_idf_installed()
        if esp_idf_installed:
            return BurnMode.FULL
        
        esptool_available = self._check_esptool_available()
        if esptool_available:
            return BurnMode.LIGHT
        
        return BurnMode.NONE
    
    def _check_esp_idf_installed(self) -> bool:
        """检查ESP-IDF是否已安装"""
        version = self._get_esp_idf_version()
        if version:
            min_version = tuple(map(int, self.ESP_IDF_INFO["min_version"].split(".")))
            version_tuple = self._parse_version(version)
            if version_tuple and version_tuple >= min_version:
                return True
        return False
    
    def _check_esptool_available(self) -> bool:
        """检查esptool是否可用"""
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
    
    def install_esptool_only(self) -> Tuple[bool, str]:
        """
        仅安装esptool（轻量模式）
        
        Returns:
            (是否成功, 消息)
        """
        self._notify_progress("正在安装 esptool (轻量烧录模式)...", 0)
        
        success, msg = self.install_pip_package("esptool")
        
        if success:
            self._notify_progress("esptool 安装成功，轻量烧录模式已启用", 100)
            return True, "esptool 安装成功，已启用轻量烧录模式"
        else:
            return False, f"esptool 安装失败: {msg}"
    
    def run_as_admin(self) -> bool:
        """
        以管理员权限重新运行程序
        
        Returns:
            是否成功启动
        """
        if self._is_admin:
            return True
        
        if self._is_windows:
            try:
                script = sys.executable
                params = ' '.join(sys.argv)
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", script, params, None, 1
                )
                return True
            except Exception:
                return False
        elif self._is_macos:
            return False
        
        return False
    
    def _get_driver_manual_guide(self, driver_name: str) -> str:
        """
        获取驱动手动安装指南（带颜色输出）
        
        Args:
            driver_name: 驱动名称 (CP210x 或 FTDI)
            
        Returns:
            手动安装指南字符串
        """
        driver_info = self.DRIVERS.get(driver_name, {})
        if not driver_info:
            return f"{self.COLOR_RED}未知的驱动类型: {driver_name}{self.COLOR_RESET}"
        
        url = driver_info.get("windows_url", "") if self._is_windows else driver_info.get("macos_url", "")
        
        guide = f"\n{self.COLOR_CYAN}{'='*50}{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_CYAN}【{driver_name} 驱动手动安装指南】{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_CYAN}{'='*50}{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 1: 下载驱动{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_BLUE}官方下载地址:{self.COLOR_RESET}\n"
        guide += f"   {url}\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 2: 解压文件{self.COLOR_RESET}\n"
        guide += f"   如果是 ZIP 格式，右键解压到当前文件夹\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 3: 安装驱动{self.COLOR_RESET}\n"
        if self._is_windows:
            guide += f"   方式一: 右键点击 INF 文件 → 安装\n"
            guide += f"   方式二: 运行 EXE 安装程序\n\n"
        else:
            guide += f"   运行 PKG 安装包\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 4: 重新插拔设备{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 5: 验证安装{self.COLOR_RESET}\n"
        guide += f"   点击「一键检测环境」验证安装结果\n\n"
        
        guide += f"{self.COLOR_MAGENTA}如果安装失败，请尝试:{self.COLOR_RESET}\n"
        guide += f"   • 以管理员身份运行安装程序\n"
        if self._is_windows:
            guide += f"   • 禁用驱动签名验证（高级启动选项）\n"
        else:
            guide += f"   • 在系统偏好设置中允许加载\n"
        
        try:
            webbrowser.open(url)
        except Exception:
            pass
        
        return guide
    
    def _get_esp_idf_manual_guide(self) -> str:
        """
        获取 ESP-IDF 手动安装指南（带颜色输出）
        
        Returns:
            手动安装指南字符串
        """
        guide = f"\n{self.COLOR_CYAN}{'='*60}{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_CYAN}【ESP-IDF 手动安装指南】{self.COLOR_RESET}\n"
        guide += f"{self.COLOR_CYAN}{'='*60}{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_GREEN}【推荐】使用 GUI 版本安装器{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 1: 访问官方下载页面{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_BLUE}https://dl.espressif.cn/dl/eim/{self.COLOR_RESET}\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 2: 选择「GUI下载器」{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_MAGENTA}Windows 用户:{self.COLOR_RESET} eim-gui-windows-x64.exe\n"
        guide += f"   {self.COLOR_MAGENTA}macOS Apple Silicon:{self.COLOR_RESET} eim-gui-macos-aarch64.dmg\n"
        guide += f"   {self.COLOR_MAGENTA}macOS Intel:{self.COLOR_RESET} eim-gui-macos-x64.dmg\n\n"
        
        guide += f"{self.COLOR_GREEN}GUI 版本优势：{self.COLOR_RESET}\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 图形化界面，操作简单直观\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 自动配置环境变量，无需手动设置\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 一键验证安装，确保环境正确\n"
        guide += f"   {self.COLOR_GREEN}✓{self.COLOR_RESET} 支持离线安装，网络要求更低\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 3: 运行安装程序{self.COLOR_RESET}\n"
        guide += f"   双击下载的文件，按照向导完成安装\n\n"
        
        guide += f"{self.COLOR_YELLOW}步骤 4: 验证安装{self.COLOR_RESET}\n"
        guide += f"   打开「ESP-IDF 5.x CMD」或终端，运行: idf.py --version\n\n"
        
        guide += f"{self.COLOR_MAGENTA}提示:{self.COLOR_RESET}\n"
        guide += f"   当前已启用轻量烧录模式，核心烧录功能可用。\n"
        guide += f"   安装完整 ESP-IDF 后可获得编译功能。\n"
        
        try:
            webbrowser.open(self.ESP_IDF_EIM_URL)
        except Exception:
            pass
        
        return guide
    
    def show_manual_driver_guide(self, driver_name: str) -> Tuple[bool, str]:
        """
        显示驱动手动安装指南并打开下载页面
        
        Args:
            driver_name: 驱动名称 (CP210x 或 FTDI)
            
        Returns:
            (是否成功, 消息)
        """
        driver_info = self.DRIVERS.get(driver_name, {})
        if not driver_info:
            return False, f"未知的驱动类型: {driver_name}"
        
        url = driver_info.get("windows_url", "") if self._is_windows else driver_info.get("macos_url", "")
        
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        
        guide = f"""【{driver_name} 驱动手动安装指南】

1. 下载驱动
   访问: {url}

2. 解压文件（如果是ZIP格式）

3. 安装驱动
   Windows: 右键点击 INF 文件 -> 安装
   macOS: 运行 PKG 安装包

4. 重新插拔设备

5. 点击「一键检测环境」验证安装结果

如果安装失败，请尝试:
- 以管理员身份运行安装程序
- 禁用驱动签名验证（Windows）
- 在系统偏好设置中允许加载（macOS）
"""
        return True, guide


if __name__ == "__main__":
    def on_progress(message: str, progress: int):
        print(f"[{progress}%] {message}")
    
    installer = EnvInstaller()
    installer.set_progress_callback(on_progress)
    
    print("开始检测环境...\n")
    items = installer.check_all()
    
    print("\n" + installer.generate_report())
    
    print(f"\n管理员权限: {installer.is_admin}")
    
    pending = installer.get_pending_items()
    if pending:
        print(f"\n待处理项 ({len(pending)} 项):")
        for item in pending:
            print(f"  - {item.name} ({item.item_type.value})")
    else:
        print("\n所有环境已安装完成!")
