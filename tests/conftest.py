import sys
import types
from typing import Any, cast


def _ensure_usb() -> None:
    try:
        import usb.core  # noqa: F401
        import usb.util  # noqa: F401
    except ModuleNotFoundError:
        usb_module = cast(Any, types.ModuleType("usb"))
        core_module = cast(Any, types.ModuleType("usb.core"))
        util_module = cast(Any, types.ModuleType("usb.util"))

        class USBError(Exception):
            def __init__(self, *args, errno: int | None = None, **kwargs):
                super().__init__(*args)
                self.errno = errno

        def find(**kwargs):  # noqa: D401 - stub
            return None

        def claim_interface(*args, **kwargs):  # noqa: D401 - stub
            return None

        def release_interface(*args, **kwargs):  # noqa: D401 - stub
            return None

        def endpoint_direction(address: int) -> int:
            return address & 0x80

        core_module.USBError = USBError
        core_module.find = find
        core_module.NoBackendError = USBError

        util_module.claim_interface = claim_interface
        util_module.release_interface = release_interface
        util_module.endpoint_direction = endpoint_direction
        util_module.get_string = lambda *args, **kwargs: "stub"
        util_module.ENDPOINT_OUT = 0x00
        util_module.ENDPOINT_IN = 0x80

        usb_module.core = core_module
        usb_module.util = util_module

        sys.modules.setdefault("usb", usb_module)
        sys.modules.setdefault("usb.core", core_module)
        sys.modules.setdefault("usb.util", util_module)


def _ensure_hid() -> None:
    try:
        import hid  # noqa: F401
    except ModuleNotFoundError:
        hid_module = cast(Any, types.ModuleType("hid"))

        class _Device:
            def __init__(self, *args, **kwargs):
                pass

            def close(self):  # noqa: D401 - stub
                return None

            def write(self, *_args, **_kwargs):
                return len(_args[0]) if _args else 0

            def read(self, *_args, **_kwargs):
                return []

        hid_module.device = _Device
        hid_module.enumerate = lambda *args, **kwargs: []
        sys.modules.setdefault("hid", hid_module)


def _ensure_crypto() -> None:
    try:
        from Crypto.Cipher import DES  # noqa: F401
    except ModuleNotFoundError:
        crypto_module = cast(Any, types.ModuleType("Crypto"))
        cipher_module = cast(Any, types.ModuleType("Crypto.Cipher"))

        class _DummyCipher:
            def encrypt(self, data: bytes) -> bytes:
                return data

            def decrypt(self, data: bytes) -> bytes:
                return data

        class _DES:
            MODE_CBC = 1

            @staticmethod
            def new(key: bytes, mode: int, iv: bytes) -> _DummyCipher:
                return _DummyCipher()

        cipher_module.DES = _DES
        crypto_module.Cipher = cipher_module

        sys.modules.setdefault("Crypto", crypto_module)
        sys.modules.setdefault("Crypto.Cipher", cipher_module)


def pytest_configure(config):
    _ensure_usb()
    _ensure_hid()
    _ensure_crypto()
