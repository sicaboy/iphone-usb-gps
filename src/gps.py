import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import fcntl
import json
import logging
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

from packaging.version import Version
from pymobiledevice3 import usbmux
from pymobiledevice3.exceptions import AlreadyMountedError, PasswordRequiredError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import PersonalizedImageMounter, auto_mount

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
GEOCODER = ROOT / ".build" / "geocode"
STATE = Path.home() / "Library" / "Application Support" / "iphone-usb-gps"
JOURNAL = Path("session.json")
LOG = Path("session.log")
SOCKET = Path("session.sock")
STARTUP_TIMEOUT = 600
REQUEST_TIMEOUT = 25


def error_text(exc):
    if isinstance(exc, PasswordRequiredError):
        return "iPhone 处于锁定状态，请解锁后重试。"
    return str(exc) or type(exc).__name__


def journal():
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {}


def save(data):
    temporary = JOURNAL.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    temporary.replace(JOURNAL)


def worker_running():
    with open("worker.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


async def usb_devices():
    return [device for device in await usbmux.list_devices() if device.is_usb]


async def device_info(device):
    async with await create_using_usbmux(
        serial=device.serial, connection_type="USB", autopair=False
    ) as lockdown:
        values = lockdown.all_values
        return {
            "name": values.get("DeviceName", "Apple 设备"),
            "model": values.get("ProductType", "未知"),
            "ios": lockdown.product_version,
            "build": values.get("BuildVersion", "未知"),
            "paired": lockdown.paired,
            "developer": await lockdown.get_developer_mode_status() if lockdown.paired else None,
        }


async def target(serial=None):
    devices = await usb_devices()
    if serial:
        devices = [device for device in devices if device.matches_udid(serial)]
    if not devices:
        raise RuntimeError("请用 USB 重新连接并解锁目标 iPhone。")
    if len(devices) != 1:
        raise RuntimeError("连接了多个 USB 设备，请只保留目标 iPhone。")
    device = devices[0]
    info = await device_info(device)
    if not info["paired"]:
        raise RuntimeError("请解锁 iPhone，在 Finder 选中设备并确认手机上的「信任此电脑」。")
    if not info["model"].startswith("iPhone") or Version(info["ios"]) < Version("17.4"):
        raise RuntimeError("此工具使用 iPhone（iOS 17.4+）的 USB 用户态 RSD 连接。")
    if not info["developer"]:
        raise RuntimeError("请在 iPhone 设置 → 隐私与安全性 → 开发者模式开启，重启后解锁并确认。")
    return device.serial


@asynccontextmanager
async def location_session(serial):
    async with AsyncExitStack() as stack:
        rsd = await stack.enter_async_context(PreferredRsdTunnel(serial=serial, autopair=False))
        if rsd.udid.replace("-", "") != serial.replace("-", ""):
            raise RuntimeError("RSD 返回的设备与 USB 目标不一致。")
        async with PersonalizedImageMounter(lockdown=rsd) as mounter:
            mounted = await mounter.is_image_mounted(mounter.IMAGE_TYPE)
        if not mounted:
            logging.info("准备 Developer Disk Image")
            try:
                await auto_mount(rsd)
            except AlreadyMountedError:
                logging.info("Developer Disk Image 已存在")
            # Refresh the service list using the existing tunnel's dialer.
            rsd = await stack.enter_async_context(RemoteServiceDiscoveryService(
                rsd.service.address, open_connection=rsd.open_connection
            ))
        dvt = await stack.enter_async_context(DvtProvider(rsd))
        location = await stack.enter_async_context(LocationSimulation(dvt))
        yield dvt, location


def coordinates(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("纬度须在 −90 到 90 之间，经度须在 −180 到 180 之间。")
    return [lat, lon]


def resolve(query):
    query = query.strip().replace("，", ",")
    if not query:
        raise ValueError("请输入地名或纬度,经度。")
    parts = query.split(",")
    if len(parts) == 2:
        try:
            lat, lon = map(float, parts)
        except ValueError:
            if re.fullmatch(r"[\d\s+.,eE-]+", query):
                raise ValueError("坐标格式应为 纬度,经度。") from None
        else:
            return coordinates(lat, lon), None
    try:
        result = subprocess.run(
            [GEOCODER, query], check=True, capture_output=True, text=True, timeout=25
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Apple Maps 无法解析「{query}」，请改用更具体的地名或坐标。") from exc
    place = json.loads(result.stdout)
    return coordinates(place["lat"], place["lon"]), place["name"]


async def apply_position(location, serial, point):
    # Record the attempted target before sending it so an interrupted set can still be cleared.
    data = {"serial": serial, "target": point, "acknowledged": False}
    save(data)
    async with asyncio.timeout(REQUEST_TIMEOUT):
        await location.set(*point)
    save({**data, "acknowledged": True})
    logging.info("DVT set replied, target %s", point)


async def serve(serial, first_point):
    stop = asyncio.Event()
    connected = asyncio.Event()
    lifecycle = asyncio.Lock()
    operations = set()

    async def session():
        async with location_session(serial) as (dvt, location):
            await apply_position(location, serial, first_point)
            connected.set()

            async def handle(reader, writer):
                task = asyncio.current_task()
                operations.add(task)
                try:
                    async with asyncio.timeout(REQUEST_TIMEOUT + 2):
                        request = json.loads(await reader.readline())
                        async with lifecycle:
                            if stop.is_set():
                                raise RuntimeError("会话正在关闭。")
                            command = request["command"]
                            if command == "set":
                                try:
                                    await apply_position(location, serial, coordinates(*request["target"]))
                                except Exception:
                                    stop.set()
                                    raise
                            elif command == "reset":
                                try:
                                    await asyncio.wait_for(location.clear(), REQUEST_TIMEOUT)
                                    logging.info("DVT clear sent")
                                finally:
                                    stop.set()
                            elif command != "status":
                                raise ValueError("未知会话命令。")
                            reply = {"ok": True, "pid": os.getpid(), "target": journal().get("target")}
                except Exception as exc:
                    logging.exception("Session request failed")
                    reply = {"ok": False, "error": error_text(exc)}
                try:
                    writer.write(json.dumps(reply).encode() + b"\n")
                    await writer.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    writer.close()
                    operations.discard(task)

            async with await asyncio.start_unix_server(handle, str(SOCKET)) as server:
                waiting = [asyncio.create_task(stop.wait()), asyncio.create_task(dvt.dtx.wait_disconnected())]
                try:
                    await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in waiting:
                        task.cancel()
                    await asyncio.gather(*waiting, return_exceptions=True)
                    server.close()
                    if operations:
                        await asyncio.gather(*list(operations), return_exceptions=True)
                if not stop.is_set():
                    logging.warning("DVT disconnected; reconnect the same iPhone to run gps-reset")

    task = asyncio.create_task(session())
    ready = asyncio.create_task(connected.wait())
    try:
        done, _ = await asyncio.wait([task, ready], timeout=STARTUP_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise TimeoutError("准备开发者服务超时。")
        await task
    finally:
        ready.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(ready, task, return_exceptions=True)


def rpc(command, **kwargs):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(REQUEST_TIMEOUT + 4)
        client.connect(str(SOCKET))
        client.sendall(json.dumps({"command": command, **kwargs}).encode() + b"\n")
        with client.makefile("rb") as stream:
            line = stream.readline()
    if not line:
        raise RuntimeError("会话连接已关闭。")
    reply = json.loads(line)
    if not reply["ok"]:
        raise RuntimeError(reply["error"])
    return reply


def start(serial, point):
    SOCKET.unlink(missing_ok=True)
    if LOG.exists() and LOG.stat().st_size >= 2 * 1024 * 1024:
        LOG.replace(LOG.with_suffix(".log.1"))
    # The child inherits the held lock, including when the invoking shell is interrupted.
    with LOG.open("a") as log, open("worker.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        child = subprocess.Popen(
            [sys.executable, SCRIPT, "_worker", str(lock.fileno()), serial, json.dumps(point)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            pass_fds=(lock.fileno(),),
        )
    deadline = time.monotonic() + STARTUP_TIMEOUT + 10
    announced = False
    started = time.monotonic()
    while time.monotonic() < deadline:
        if child.poll() is not None:
            lines = LOG.read_text(errors="replace").splitlines()
            detail = lines[-1] if lines else "会话进程已退出"
            raise RuntimeError(f"{detail}\n日志：{STATE / LOG}")
        if SOCKET.exists():
            try:
                return rpc("status")
            except (ConnectionRefusedError, FileNotFoundError):
                pass
        if not announced and time.monotonic() - started > 3:
            print(f"正在准备 RSD/DVT，首次可能需下载开发者镜像。日志 {STATE / LOG}", flush=True)
            announced = True
        time.sleep(0.2)
    raise TimeoutError(f"等待会话就绪超时。日志 {STATE / LOG}")


def set_location(query):
    point, label = resolve(query)
    serial = asyncio.run(asyncio.wait_for(target(journal().get("serial")), 10))
    reply = rpc("set", target=point) if worker_running() else start(serial, point)
    print(f"DVT 已回应设置请求，目标 {point[0]}, {point[1]}，会话 PID {reply['pid']}。")
    if label:
        print(f"Apple Maps 地点匹配：{label}")
    print("请在 iPhone 的 Apple Maps 查看蓝点确认。")


async def clear_reconnected(serial):
    serial = await target(serial)
    async with location_session(serial) as (_, location):
        await location.clear()


def reset():
    saved = journal()
    if not saved and not worker_running():
        print("没有待清除的本工具会话。")
        return
    cleared = False
    if worker_running():
        try:
            rpc("reset")
            cleared = True
        except (OSError, RuntimeError) as exc:
            print(f"原会话清除未完成：{error_text(exc)}", file=sys.stderr)
        deadline = time.monotonic() + 15
        while worker_running() and time.monotonic() < deadline:
            time.sleep(0.1)
        if worker_running():
            raise RuntimeError(f"会话仍在关闭或准备中，请稍后重试 gps-reset。日志 {STATE / LOG}")
    if not cleared:
        saved = journal()
        if not saved:
            print("没有待清除的本工具会话。")
            return
        asyncio.run(asyncio.wait_for(clear_reconnected(saved["serial"]), 60))
    JOURNAL.unlink(missing_ok=True)
    SOCKET.unlink(missing_ok=True)
    print("已发送 DVT 清除请求，本工具会话已关闭。请在 Apple Maps 确认蓝点恢复。")


async def show_devices():
    devices = await asyncio.wait_for(usb_devices(), 5)
    if not devices:
        print("USB 设备：无")
    for device in devices:
        try:
            info = await asyncio.wait_for(device_info(device), 5)
        except Exception as exc:
            print(f"USB 设备已检测到，详情读取失败：{error_text(exc)}")
            continue
        developer = {True: "开启", False: "关闭", None: "未知"}[info["developer"]]
        trust = "已配对" if info["paired"] else "需要信任"
        print(f"USB：{info['name']}（{info['model']}），iOS {info['ios']} ({info['build']})，{trust}，开发者模式{developer}")


def status():
    asyncio.run(show_devices())
    saved = journal()
    if worker_running():
        try:
            reply = rpc("status")
        except (OSError, RuntimeError):
            print("会话：正在准备、关闭或连接异常")
        else:
            print(f"会话：DVT 连接运行中，PID {reply['pid']}")
    elif saved:
        print("会话：已断开，PID 无。可重连同一部 iPhone 后运行 gps-reset。")
    else:
        print("会话：未运行，PID 无")
    if saved:
        lat, lon = saved["target"]
        request = "DVT 已回应" if saved["acknowledged"] else "设置结果未知"
        print(f"目标：{lat}, {lon}（{request}。手机定位请以 Apple Maps 蓝点为准。）")
    if LOG.exists():
        print(f"日志：{STATE / LOG}")


def main():
    command, *arguments = sys.argv[1:]
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chdir(STATE)
    if command == "_worker":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        with os.fdopen(int(arguments[0]), "a"):
            try:
                asyncio.run(serve(arguments[1], json.loads(arguments[2])))
            except Exception as exc:
                logging.exception("Worker stopped")
                logging.error("%s: %s", type(exc).__name__, error_text(exc))
                return 1
        return 0
    parser = argparse.ArgumentParser(prog=f"gps-{command}")
    if command == "set":
        parser.add_argument("location", help="地名或十进制纬度,经度")
        if arguments and re.match(r"^-(?:\d|\.\d)", arguments[0]):
            arguments.insert(0, "--")
    options = parser.parse_args(arguments)
    with open("command.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if command == "set":
            set_location(options.location)
        elif command == "reset":
            reset()
        else:
            status()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(error_text(exc), file=sys.stderr)
        sys.exit(1)
