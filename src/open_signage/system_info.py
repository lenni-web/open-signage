from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

from .database import data_dir


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip("\x00\n ")
    except OSError:
        return None


def _run_json(command: list[str]) -> list[dict]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return json.loads(result.stdout)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        return []


def _run_text(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None


def _wireless_ssid(interface: str) -> str | None:
    link = _run_text(["iw", "dev", interface, "link"])
    if not link:
        return None
    for line in link.splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID: "):
            return stripped.removeprefix("SSID: ").strip() or None
    return None


def _memory() -> dict:
    values: dict[str, int] = {}
    text = _read_text("/proc/meminfo")
    if text:
        for line in text.splitlines():
            key, _, raw = line.partition(":")
            if raw:
                values[key] = int(raw.strip().split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"total_bytes": total, "used_bytes": max(0, total - available)}


def _uptime_seconds() -> int | None:
    text = _read_text("/proc/uptime")
    if not text:
        return None
    try:
        return int(float(text.split()[0]))
    except (ValueError, IndexError):
        return None


def _temperature_celsius() -> float | None:
    text = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if not text:
        return None


def _operating_system() -> str:
    text = _read_text("/etc/os-release")
    if text:
        for line in text.splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.partition("=")[2].strip().strip('"')
    return platform.platform()
    try:
        return round(float(text) / 1000, 1)
    except ValueError:
        return None


def _network() -> dict:
    routes = _run_json(["ip", "-j", "route", "show", "default"])
    gateways = {route.get("dev"): route.get("gateway") for route in routes}
    result = {"wlan": [], "ethernet": []}

    for interface in _run_json(["ip", "-j", "address", "show"]):
        name = interface.get("ifname", "")
        if name == "lo":
            continue
        if name.startswith(("wl", "wlan")):
            category = "wlan"
        elif name.startswith(("eth", "en")):
            category = "ethernet"
        else:
            continue

        addresses = [
            address.get("local")
            for address in interface.get("addr_info", [])
            if address.get("family") in {"inet", "inet6"} and address.get("local")
        ]
        item = {
            "name": name,
            "connected": interface.get("operstate") == "UP" and bool(addresses),
            "addresses": addresses,
            "mac": interface.get("address"),
            "gateway": gateways.get(name),
        }
        if category == "wlan":
            item["ssid"] = _wireless_ssid(name)
        result[category].append(item)
    return result


def collect_system_info() -> dict:
    disk = shutil.disk_usage(data_dir())
    load = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "hostname": socket.gethostname(),
        "model": _read_text("/proc/device-tree/model") or platform.machine(),
        "operating_system": _operating_system(),
        "kernel": platform.release(),
        "uptime_seconds": _uptime_seconds(),
        "temperature_celsius": _temperature_celsius(),
        "load_average": list(load) if load else None,
        "memory": _memory(),
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "network": _network(),
    }
