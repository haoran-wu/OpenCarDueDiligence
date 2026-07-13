from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from .safety import assert_read_only


class ElmTransport(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def query(self, command: str) -> str: ...


@dataclass
class MockElmTransport:
    responses: dict[str, str] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def query(self, command: str) -> str:
        safe = assert_read_only(command)
        self.commands.append(safe)
        return self.responses.get(safe, "NO DATA\r>")


class BleakElmTransport:
    """Small BLE UART transport for user-configured ELM327 adapters.

    BLE ELM327 clones expose different GATT UUIDs, so callers must select a
    reviewed driver profile. The default is the Nordic UART-style profile used
    by several BLE adapters. No arbitrary command endpoint is exposed.
    """

    def __init__(
        self,
        address: str,
        write_uuid: str,
        notify_uuid: str,
        timeout_seconds: float = 8.0,
    ) -> None:
        from bleak import BleakClient

        self.address = address
        self.write_uuid = write_uuid
        self.notify_uuid = notify_uuid
        self.timeout_seconds = timeout_seconds
        self._client = BleakClient(address)
        self._buffer = bytearray()
        self._response_ready = asyncio.Event()

    async def connect(self) -> None:
        await self._client.connect()

        def on_notify(_: object, data: bytearray) -> None:
            self._buffer.extend(data)
            if b">" in self._buffer:
                self._response_ready.set()

        await self._client.start_notify(self.notify_uuid, on_notify)

    async def close(self) -> None:
        if self._client.is_connected:
            await self._client.stop_notify(self.notify_uuid)
            await self._client.disconnect()

    async def query(self, command: str) -> str:
        safe = assert_read_only(command)
        self._buffer.clear()
        self._response_ready.clear()
        await self._client.write_gatt_char(self.write_uuid, f"{safe}\r".encode(), response=False)
        await asyncio.wait_for(self._response_ready.wait(), timeout=self.timeout_seconds)
        return self._buffer.decode(errors="replace")
