"""Startup hardware & capability probing for Windows.

Mirrors the macOS ``HardwareCapabilities`` module: inspects CPU, RAM,
Vulkan GPU devices (via ``lexomorph-llm-host.exe --list-devices``), Vulkan
SPIR-V shaders, the local LLM host binary, and Intel NPU availability once
per process (warmed asynchronously at startup).

The UI uses :class:`HardwareProfile` to disable hardware-incompatible
controls (such as Vulkan GPU acceleration on machines without a compatible
GPU/driver, or oversized 8B/9B models on low-RAM PCs) and show clear
explanations instead of letting the user enable broken options.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from . import paths
from .logging_setup import get as get_logger

log = get_logger("hardware")

PROBE_TIMEOUT_SECONDS = 5.0

#: Minimum total RAM (GB) required for each bundled local LLM model.
_MODEL_MIN_RAM_GB: dict[str, int] = {
    "voicescribe": 6,
    "loqira": 6,
    "vanilla08b": 6,
    "lfm25": 8,
    "ministral3b": 8,
    "phi4mini": 8,
    "ruadapt4b": 8,
    "qvikhr4b": 8,
    "qwen35_4b": 8,
    "yandexgpt": 12,
    "gemma4e4b": 12,
    "qwen35_9b": 12,
}


@dataclass(frozen=True)
class CapabilityStatus:
    available: bool
    message: str


@dataclass(frozen=True)
class ModelCompatibility:
    #: "recommended" | "cpu_only" | "unsupported"
    status: str
    reason: str = ""

    @property
    def is_supported(self) -> bool:
        return self.status != "unsupported"


def parse_llm_gpu_device_list(output: str) -> list[str]:
    """Parse ``--list-devices`` output: ``DEVICE <name>\\t<description>``."""
    devices: list[str] = []
    for line in output.splitlines():
        if not line.startswith("DEVICE "):
            continue
        rest = line[len("DEVICE "):]
        parts = rest.split("\t", 1)
        name = parts[0].strip() if parts else ""
        desc = parts[1].strip() if len(parts) > 1 else ""
        label = desc or name
        if label:
            devices.append(label)
    return devices


def _t(ru: str, en: str, lang: str) -> str:
    return ru if lang == "ru" else en


@dataclass(frozen=True)
class HardwareProfile:
    cpu_model: str
    cpu_cores: int
    architecture: str
    ram_gb: int
    vulkan_devices: tuple[str, ...]
    llm_host_available: bool
    vulkan_shaders_available: bool
    npu_name: str = ""

    @staticmethod
    def minimum_ram_gb(model_id: str) -> int:
        return _MODEL_MIN_RAM_GB.get(str(model_id), 8)

    @staticmethod
    def is_large_model(model_id: str) -> bool:
        return HardwareProfile.minimum_ram_gb(model_id) >= 12

    @property
    def vulkan_gpu_available(self) -> bool:
        return self.vulkan_gpu_status("en").available

    @property
    def local_llm_available(self) -> bool:
        return self.local_llm_status("en").available

    def vulkan_gpu_status(self, lang: str = "ru") -> CapabilityStatus:
        if not self.llm_host_available:
            return CapabilityStatus(
                False,
                _t(
                    "Модуль локальных LLM отсутствует в этой сборке. Ускорение на GPU недоступно.",
                    "The local LLM helper is missing in this build. GPU acceleration is unavailable.",
                    lang,
                ),
            )
        if not self.vulkan_shaders_available:
            return CapabilityStatus(
                False,
                _t(
                    "Шейдеры Vulkan не найдены в папке программы — локальные LLM работают на CPU.",
                    "Vulkan shaders were not found in the app directory — local LLMs run on CPU.",
                    lang,
                ),
            )
        if not self.vulkan_devices:
            return CapabilityStatus(
                False,
                _t(
                    "На этом компьютере не обнаружена совместимая видеокарта с поддержкой Vulkan (или отсутствует драйвер Vulkan). Ускорение локальных моделей на GPU недоступно — обработка идёт на CPU или через свой сервер.",
                    "No compatible Vulkan GPU was detected on this PC (or Vulkan driver is missing). Local LLM GPU acceleration is unavailable — processing runs on CPU or via a custom server.",
                    lang,
                ),
            )
        return CapabilityStatus(True, ", ".join(self.vulkan_devices))

    def local_llm_status(self, lang: str = "ru") -> CapabilityStatus:
        if not self.llm_host_available:
            return CapabilityStatus(
                False,
                _t(
                    "Локальный LLM-движок отсутствует в этой сборке. Используйте «Свой сервер» (OpenAI-совместимый API).",
                    "The bundled local LLM engine is missing from this build. Use 'Custom server' (OpenAI-compatible API).",
                    lang,
                ),
            )
        if self.ram_gb < 6:
            return CapabilityStatus(
                False,
                _t(
                    f"Недостаточно оперативной памяти ({self.ram_gb} ГБ, требуется от 6 ГБ) для локальных LLM-моделей. Используйте «Свой сервер».",
                    f"Insufficient RAM ({self.ram_gb} GB, minimum 6 GB required) for local LLM models. Use 'Custom server' instead.",
                    lang,
                ),
            )
        return CapabilityStatus(True, _t(f"{self.ram_gb} ГБ ОЗУ", f"{self.ram_gb} GB RAM", lang))

    def model_compatibility(self, model_id: str, lang: str = "ru",
                            display_name: Optional[str] = None) -> ModelCompatibility:
        local = self.local_llm_status(lang)
        if not local.available:
            return ModelCompatibility("unsupported", local.message)
        required = self.minimum_ram_gb(model_id)
        label = display_name or model_id
        if self.ram_gb < required:
            return ModelCompatibility(
                "unsupported",
                _t(
                    f"Для модели {label} требуется от {required} ГБ ОЗУ (на этом ПК: {self.ram_gb} ГБ). Выберите более лёгкую модель или «Свой сервер».",
                    f"{label} requires at least {required} GB RAM (this PC has {self.ram_gb} GB). Choose a lighter model or 'Custom server'.",
                    lang,
                ),
            )
        if self.is_large_model(model_id) and not self.vulkan_gpu_available:
            return ModelCompatibility(
                "cpu_only",
                _t(
                    f"Совместимый Vulkan GPU не обнаружен — крупная модель {label} будет работать на CPU медленнее. Для быстрого отклика подойдут лёгкие модели или свой сервер.",
                    f"No compatible Vulkan GPU detected — the large {label} model will run noticeably slower on CPU. Consider lighter models or a custom server.",
                    lang,
                ),
            )
        return ModelCompatibility("recommended")

    def punctuation_status(self, lang: str = "ru") -> CapabilityStatus:
        if self.ram_gb < 6:
            return CapabilityStatus(
                False,
                _t(
                    f"Недостаточно оперативной памяти ({self.ram_gb} ГБ, требуется от 6 ГБ) для локальной модели пунктуации.",
                    f"Insufficient RAM ({self.ram_gb} GB, minimum 6 GB required) for local punctuation restoration.",
                    lang,
                ),
            )
        return CapabilityStatus(True, _t("CPU · готово", "CPU · ready", lang))

    @property
    def log_summary(self) -> str:
        gpu_desc = f"Vulkan=[{', '.join(self.vulkan_devices)}]" if self.vulkan_devices else "Vulkan=none"
        npu_desc = f", NPU={self.npu_name}" if self.npu_name else ""
        return (
            f"Hardware probe: {self.cpu_model} ({self.architecture}, {self.cpu_cores} cores, "
            f"{self.ram_gb} GB RAM), {gpu_desc}{npu_desc}, "
            f"llmHost={self.llm_host_available}, shaders={self.vulkan_shaders_available}"
        )


def _detect_ram_gb() -> int:
    if sys.platform == "win32":
        try:
            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return max(1, round(stat.ullTotalPhys / (1024 ** 3)))
        except Exception:
            pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return max(1, round((pages * page_size) / (1024 ** 3)))
    except (AttributeError, OSError, ValueError):
        pass
    return 16


def _probe_vulkan_devices(executable: str, env: dict[str, str]) -> list[str]:
    if not executable or not os.path.isfile(executable):
        return []
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
        "timeout": PROBE_TIMEOUT_SECONDS,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run([executable, "--list-devices"], **kwargs)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return parse_llm_gpu_device_list(proc.stdout or "")


def probe_now() -> HardwareProfile:
    from .llm.host import _engine_environment, bundled_host_available, host_executable

    cpu_model = platform.processor() or platform.machine() or "CPU"
    cores = os.cpu_count() or 1
    arch = platform.machine() or "AMD64"
    ram_gb = _detect_ram_gb()

    llm_host_ok = bundled_host_available()
    env = _engine_environment()
    shader_dir = env.get("SUPERDICTATE_VULKAN_SHADER_DIR", "")
    shaders_ok = bool(shader_dir) and os.path.isfile(os.path.join(shader_dir, "matmul_f32_f32.spv"))
    vulkan_devices = tuple(_probe_vulkan_devices(host_executable(), env)) if llm_host_ok else ()

    npu_name = ""
    try:
        from . import asr
        info = asr.npu_info()
        if isinstance(info, dict):
            npu_name = str(info.get("name") or "Intel NPU")
    except Exception:
        pass

    return HardwareProfile(
        cpu_model=cpu_model,
        cpu_cores=cores,
        architecture=arch,
        ram_gb=ram_gb,
        vulkan_devices=vulkan_devices,
        llm_host_available=llm_host_ok,
        vulkan_shaders_available=shaders_ok,
        npu_name=npu_name,
    )


_lock = threading.Lock()
_cached: Optional[HardwareProfile] = None
_warming = False


def current() -> HardwareProfile:
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
    probed = probe_now()
    with _lock:
        if _cached is None:
            _cached = probed
        return _cached


def warm_up_async(on_complete: Optional[Callable[[HardwareProfile], None]] = None) -> None:
    global _warming
    with _lock:
        if _cached is not None:
            existing = _cached
            should_run = False
        elif _warming:
            existing = None
            should_run = False
        else:
            existing = None
            _warming = True
            should_run = True
    if existing is not None:
        if on_complete is not None:
            on_complete(existing)
        return
    if not should_run:
        return

    def _work() -> None:
        global _cached, _warming
        try:
            profile = probe_now()
            log.info("%s", profile.log_summary)
        except Exception as exc:
            log.debug("Hardware probe failed: %s", exc)
            profile = HardwareProfile(
                cpu_model="CPU", cpu_cores=os.cpu_count() or 1,
                architecture=platform.machine() or "AMD64",
                ram_gb=_detect_ram_gb(), vulkan_devices=(),
                llm_host_available=False, vulkan_shaders_available=False,
            )
        with _lock:
            _cached = profile
            _warming = False
        if on_complete is not None:
            try:
                on_complete(profile)
            except Exception:
                pass

    threading.Thread(target=_work, name="hardware-probe", daemon=True).start()
