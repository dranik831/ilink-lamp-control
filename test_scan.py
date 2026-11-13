"""
Сканер BLE-устройств вокруг. Запусти, если подключение падает с
BleakDeviceNotFoundError — проверь, что лампа вообще видна в эфире
и что её MAC совпадает с MAC в lamp_server.py / test_off.py.

Запуск:  python test_scan.py
"""

import asyncio

from bleak import BleakScanner

MAC = "3A:11:FC:7D:C7:33"   # ожидаемый адрес люстры


async def main() -> None:
    print("Сканирую 10 секунд...")
    # return_adv=True возвращает {адрес: (BLEDevice, AdvertisementData)} —
    # RSSI и имя живут в AdvertisementData
    found_devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    if not found_devices:
        print("Ничего не найдено. Проверь, что Bluetooth-адаптер включён.")
        return

    found = False
    print(f"\n{'Адрес':<20}{'RSSI':<7}Имя")
    print("-" * 60)
    for d, adv in sorted(found_devices.values(),
                         key=lambda x: x[1].rssi, reverse=True):
        mark = ""
        if d.address.upper() == MAC.upper():
            mark = "  ← ЛЮСТРА НАЙДЕНА"
            found = True
        print(f"{d.address:<20}{adv.rssi:<7}{adv.local_name or d.name or '(без имени)'}{mark}")

    if not found:
        print(f"\nЛюстра ({MAC}) в эфире НЕ видна.")
        print("Возможные причины:")
        print("  - люстра уже подключена к приложению на телефоне (разорви там связь)")
        print("  - люстра обесточена / выключена выключателем")
        print("  - MAC изменился — возьми актуальный из списка выше")


if __name__ == "__main__":
    asyncio.run(main())
