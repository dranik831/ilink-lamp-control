"""
iLink люстра — постоянное BLE-соединение + HTTP-управление.

Сервер всё время держит BLE-подключение к люстре. Управление по HTTP:
    http://<ip-сервера>:3883/lamp/on
    http://<ip-сервера>:3883/lamp/off
    http://<ip-сервера>:3883/lamp/brightness?val=128      (0-255)
    http://<ip-сервера>:3883/lamp/rgb?r=255&g=100&b=0
    http://<ip-сервера>:3883/lamp/warmth?val=200          (0=холодный, 255=тёплый)
    http://<ip-сервера>:3883/lamp/status

Пути работают и без префикса /lamp (то есть /on == /lamp/on).

Отличие от старой версии: BLE и HTTP живут в ОДНОМ asyncio-цикле,
никаких потоков и run_coroutine_threadsafe — из-за этого раньше
и рассинхронизировалось.
"""

import asyncio
import sys
from urllib.parse import urlparse, parse_qs

from bleak import BleakClient

MAC       = "3A:11:FC:7D:C7:33"
CHAR_UUID = "0000a040-0000-1000-8000-00805f9b34fb"
PORT      = 3883

WRITE_TIMEOUT = 5.0     # сек на одну команду
RECONNECT_DELAY = 5.0   # сек между попытками переподключения


# ─── Пакеты протокола ─────────────────────────────────────────
# Формат: 55 AA, тело, контрольная сумма = (0x100 - сумма тела) & 0xFF
def _pkt(*body: int) -> bytes:
    return bytes([0x55, 0xAA, *body, (0x100 - sum(body)) & 0xFF])

INIT1 = _pkt(0x01, 0x0B, 0x01, 0x06)
INIT2 = _pkt(0x01, 0x08, 0x15, 0x06)
ON    = _pkt(0x01, 0x08, 0x05, 0x01)
OFF   = _pkt(0x01, 0x08, 0x05, 0x00)

def make_brightness(val: int) -> bytes:   # val: 0-255
    return _pkt(0x01, 0x08, 0x01, val & 0xFF)

def make_warmth(val: int) -> bytes:       # 0=холодный, 255=тёплый
    return _pkt(0x01, 0x08, 0x07, val & 0xFF)

def make_rgb(r: int, g: int, b: int) -> bytes:
    return _pkt(0x03, 0x08, 0x02, r & 0xFF, g & 0xFF, b & 0xFF)


# ─── Состояние BLE ────────────────────────────────────────────
client: BleakClient | None = None
write_lock = asyncio.Lock()


async def ble_worker(stop_event: asyncio.Event) -> None:
    """Держит соединение с люстрой, переподключается при обрыве."""
    global client
    while not stop_event.is_set():
        try:
            async with BleakClient(MAC, timeout=15.0) as c:
                client = c
                print(f"[BLE] Подключено к {MAC}")

                await c.write_gatt_char(CHAR_UUID, INIT1, response=True)
                await asyncio.sleep(0.2)
                await c.write_gatt_char(CHAR_UUID, INIT2, response=True)
                await asyncio.sleep(0.5)
                print("[BLE] Инициализация отправлена — готов к командам")

                # Живём, пока устройство на связи
                while c.is_connected and not stop_event.is_set():
                    await asyncio.sleep(1)

                print("[BLE] Соединение потеряно")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[BLE] Ошибка: {e!r}")

        client = None
        if not stop_event.is_set():
            print(f"[BLE] Переподключение через {RECONNECT_DELAY:.0f} сек...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=RECONNECT_DELAY)
            except asyncio.TimeoutError:
                pass


async def send_command(data: bytes) -> str:
    """Отправляет пакет в люстру. Возвращает статус для HTTP-ответа."""
    if client is None or not client.is_connected:
        return "NOT CONNECTED"
    async with write_lock:  # не смешиваем пакеты при параллельных запросах
        try:
            await asyncio.wait_for(
                client.write_gatt_char(CHAR_UUID, data, response=True),
                timeout=WRITE_TIMEOUT,
            )
            return "OK"
        except Exception as e:
            return f"ERROR: {e!r}"


# ─── HTTP ─────────────────────────────────────────────────────
def _clamp_int(params: dict, key: str, default: int) -> int:
    try:
        val = int(params.get(key, [default])[0])
    except (ValueError, TypeError):
        val = default
    return max(0, min(255, val))


async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        # дочитываем заголовки до пустой строки
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line in (b"\r\n", b"\n", b""):
                break

        try:
            path, _, query = request_line.decode("latin-1").split(" ")[1].partition("?")
        except IndexError:
            path, query = "/", ""

        params = parse_qs(query)
        route = path
        if route.startswith("/lamp/"):
            route = route[len("/lamp"):]

        if route == "/on":
            status = await send_command(ON)
        elif route == "/off":
            status = await send_command(OFF)
        elif route == "/brightness":
            status = await send_command(make_brightness(_clamp_int(params, "val", 128)))
        elif route == "/rgb":
            status = await send_command(make_rgb(
                _clamp_int(params, "r", 0),
                _clamp_int(params, "g", 0),
                _clamp_int(params, "b", 0),
            ))
        elif route == "/warmth":
            status = await send_command(make_warmth(_clamp_int(params, "val", 128)))
        elif route == "/status":
            ok = client is not None and client.is_connected
            status = "READY" if ok else "NOT READY"
        else:
            status = None

        if status is None:
            body = b"Unknown command\n"
            head = "HTTP/1.1 404 Not Found"
        else:
            body = (status + "\n").encode()
            head = "HTTP/1.1 200 OK"

        writer.write(
            f"{head}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode() + body
        )
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ─── Запуск ───────────────────────────────────────────────────
async def main() -> None:
    stop_event = asyncio.Event()

    server = await asyncio.start_server(handle_http, "0.0.0.0", PORT)
    print(f"[HTTP] Слушаю 0.0.0.0:{PORT}  →  /lamp/on, /lamp/off, /lamp/status ...")

    ble_task = asyncio.create_task(ble_worker(stop_event))
    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()
        ble_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено")
