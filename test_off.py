"""
Разовый тест: подключиться к люстре, отправить инициализацию
и команду выключения света, отключиться.

Запуск:  python test_off.py
"""

import asyncio

from bleak import BleakClient

MAC       = "3A:11:FC:7D:C7:33"
CHAR_UUID = "0000a040-0000-1000-8000-00805f9b34fb"


def _pkt(*body: int) -> bytes:
    # Формат: 55 AA, тело, контрольная сумма = (0x100 - сумма тела) & 0xFF
    return bytes([0x55, 0xAA, *body, (0x100 - sum(body)) & 0xFF])


INIT1 = _pkt(0x01, 0x0B, 0x01, 0x06)
INIT2 = _pkt(0x01, 0x08, 0x15, 0x06)
OFF   = _pkt(0x01, 0x08, 0x05, 0x00)   # выключение света


async def main() -> None:
    print(f"Подключаемся к {MAC} ...")
    async with BleakClient(MAC, timeout=15.0) as client:
        print(f"Подключено: {client.is_connected}")

        print("→ INIT1")
        await client.write_gatt_char(CHAR_UUID, INIT1, response=True)
        await asyncio.sleep(0.2)

        print("→ INIT2")
        await client.write_gatt_char(CHAR_UUID, INIT2, response=True)
        await asyncio.sleep(0.5)

        print("→ OFF (выключение света)")
        await client.write_gatt_char(CHAR_UUID, OFF, response=True)

        print("Команда отправлена. Отключаюсь через 1 сек...")
        await asyncio.sleep(1.0)

    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
