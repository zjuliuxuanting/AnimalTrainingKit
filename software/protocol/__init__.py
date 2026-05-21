"""
通信协议层 — 实现上位机与ESP32 Hub的Wi-Fi/BLE通信

模块结构:
- messages: 消息模型（信封、命令、事件、错误）
- transport: 传输抽象接口
- ws_transport: WebSocket传输实现
- ble_transport: BLE GATT传输实现
- device_manager: 设备发现、连接管理、心跳与状态机
"""
