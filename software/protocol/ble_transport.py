"""
BLE GATT 传输实现

基于 bleak 库实现与 ESP32 Hub 的 BLE 通信。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, List, Dict

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    BleakScanner = None
    BleakClient = None

from .transport import TransportBase, TransportState, TransportConfig

logger = logging.getLogger("BehaviorBox.BleTransport")

SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
CHAR_TX_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
CHAR_RX_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"


class BleDiscoveryResult:
    """BLE 扫描结果"""

    def __init__(self, address: str, name: str, rssi: int):
        self.address = address
        self.name = name
        self.rssi = rssi

    def __repr__(self):
        return f"BleDiscoveryResult({self.name}, {self.address}, RSSI={self.rssi})"

    def to_dict(self) -> dict:
        return {"address": self.address, "name": self.name, "rssi": self.rssi}


async def discover_devices(scan_time: float = 5.0) -> List[BleDiscoveryResult]:
    """扫描 BLE 设备"""
    if BleakScanner is None:
        raise ImportError("bleak 库未安装，请执行: pip install bleak")

    results: List[BleDiscoveryResult] = []

    def callback(device, advertisement_data):
        name = device.name or advertisement_data.local_name or "Unknown"
        results.append(
            BleDiscoveryResult(
                address=device.address,
                name=name,
                rssi=advertisement_data.rssi or 0,
            )
        )

    async with BleakScanner(callback) as scanner:
        await asyncio.sleep(scan_time)

    return results


class BleTransport(TransportBase):
    """BLE GATT 传输层"""

    def __init__(self, address: str = "", config: Optional[TransportConfig] = None):
        super().__init__(config)
        self._address = address
        self._client: Optional[BleakClient] = None
        self._stop_event = asyncio.Event()

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, value: str):
        self._address = value

    async def connect(self) -> bool:
        if BleakClient is None:
            logger.error("bleak 库未安装，请执行: pip install bleak")
            return False
        if not self._address:
            logger.error("BLE 设备地址未设置")
            return False

        self._set_state(TransportState.CONNECTING)
        try:
            self._client = BleakClient(
                self._address,
                timeout=self._config.timeout,
            )
            await asyncio.wait_for(
                self._client.connect(),
                timeout=self._config.timeout,
            )
            self._set_state(TransportState.CONNECTED)
            logger.info(f"BLE 已连接: {self._address}")
            self._stop_event.clear()
            await self._client.start_notify(CHAR_RX_UUID, self._notification_handler)
            return True
        except asyncio.TimeoutError:
            logger.error(f"BLE 连接超时: {self._address}")
            self._set_state(TransportState.DISCONNECTED)
            return False
        except Exception as e:
            logger.error(f"BLE 连接失败: {e}")
            self._set_state(TransportState.DISCONNECTED)
            return False

    async def disconnect(self):
        self._set_state(TransportState.CLOSING)
        self._stop_event.set()

        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._set_state(TransportState.DISCONNECTED)
        logger.info("BLE 已断开")

    async def send(self, data: str):
        if not self._client or not self._client.is_connected:
            raise RuntimeError("BLE 未连接")
        raw = data.encode("utf-8")
        await self._client.write_gatt_char(CHAR_TX_UUID, raw)

    def _notification_handler(self, sender: int, data: bytearray):
        try:
            text = data.decode("utf-8")
            self._on_receive(text)
        except Exception as e:
            logger.error(f"BLE 数据解码失败: {e}")
