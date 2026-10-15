"""SPI NOR flash behavioral model — core memory and state logic.

Provides a cycle-accurate Python class representing an external SPI NOR flash
device for independent verification of ``spi_flash_ctrl``. This module owns
the internal memory array, the SPI transaction state machine, and Write Enable
(WEL) latch logic. SPI signal sampling / command decode and MISO drive are
added in later steps.
"""

from enum import Enum, auto

# 128 KiB device image
MEMORY_SIZE = 128 * 1024

# Supported SPI NOR opcodes (project command set)
CMD_READ = 0x03
CMD_FAST_READ = 0x0B
CMD_PAGE_PROGRAM = 0x02
CMD_SECTOR_ERASE = 0x20
CMD_READ_STATUS = 0x05
CMD_WRITE_ENABLE = 0x06

# Status register bits (JEDEC-style)
SR_WIP = 0x01  # bit 0 — write in progress
SR_WEL = 0x02  # bit 1 — write enable latch


class FlashState(Enum):
    """Master SPI frame state machine tracked by the flash model."""

    IDLE = auto()
    COMMAND = auto()
    ADDRESS = auto()
    DATA = auto()


class SpiNorFlash:
    """Behavioral SPI NOR flash: memory array, WEL, and SPI state machine.

    Parameters
    ----------
    None — constructed with a fixed 128 KiB array and WEL cleared.
    """

    def __init__(self):
        self.memory = bytearray(128 * 1024)
        self.wel = 0
        self.wip = 0
        self.state = FlashState.IDLE
        # Transaction context (filled by later SPI decode steps)
        self.command = 0
        self.address = 0
        self.addr_byte_count = 0
        self.dummy_cycles_remaining = 0

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _clamp_addr(self, addr: int) -> int:
        """Wrap address into the 128 KiB device space."""
        return int(addr) & (MEMORY_SIZE - 1)

    def read_byte(self, addr: int) -> int:
        """Read one byte from internal memory at ``addr``."""
        return self.memory[self._clamp_addr(addr)]

    def write_byte(self, addr: int, data: int) -> None:
        """Write one byte into internal memory at ``addr`` (raw store)."""
        self.memory[self._clamp_addr(addr)] = int(data) & 0xFF

    def read_bytes(self, addr: int, length: int) -> bytearray:
        """Read ``length`` consecutive bytes starting at ``addr``."""
        start = self._clamp_addr(addr)
        length = int(length)
        if length < 0:
            raise ValueError("length must be non-negative")
        out = bytearray(length)
        for i in range(length):
            out[i] = self.memory[(start + i) & (MEMORY_SIZE - 1)]
        return out

    def write_bytes(self, addr: int, data) -> None:
        """Write a sequence of bytes into memory starting at ``addr``."""
        start = self._clamp_addr(addr)
        for i, byte in enumerate(data):
            self.memory[(start + i) & (MEMORY_SIZE - 1)] = int(byte) & 0xFF

    # ------------------------------------------------------------------
    # Write Enable (WEL) latch
    # ------------------------------------------------------------------

    def set_write_enable(self) -> None:
        """Set the Write Enable Latch (WEL=1), as after command 0x06."""
        self.wel = 1

    def clear_write_enable(self) -> None:
        """Clear WEL (after successful program/erase, or explicit disable)."""
        self.wel = 0

    def write_enabled(self) -> bool:
        """Return True when program/erase operations are allowed."""
        return bool(self.wel)

    def status_register(self) -> int:
        """Compose the status register byte (WIP | WEL)."""
        sr = 0
        if self.wip:
            sr |= SR_WIP
        if self.wel:
            sr |= SR_WEL
        return sr

    # ------------------------------------------------------------------
    # SPI master state machine
    # ------------------------------------------------------------------

    def reset_transaction(self) -> None:
        """Return to IDLE and clear per-transaction context (CSN deassert)."""
        self.state = FlashState.IDLE
        self.command = 0
        self.address = 0
        self.addr_byte_count = 0
        self.dummy_cycles_remaining = 0

    def begin_transaction(self) -> None:
        """Enter COMMAND on chip-select assert (start of a new SPI frame)."""
        self.state = FlashState.COMMAND
        self.command = 0
        self.address = 0
        self.addr_byte_count = 0
        self.dummy_cycles_remaining = 0

    def advance_to_address(self) -> None:
        """Transition COMMAND → ADDRESS for opcodes that take a 24-bit address."""
        if self.state != FlashState.COMMAND:
            raise RuntimeError(
                f"advance_to_address from invalid state {self.state.name}"
            )
        self.state = FlashState.ADDRESS
        self.addr_byte_count = 0
        self.address = 0

    def advance_to_data(self, dummy_cycles: int = 0) -> None:
        """Transition to DATA, optionally after Fast Read dummy cycles."""
        if self.state not in (FlashState.COMMAND, FlashState.ADDRESS):
            raise RuntimeError(
                f"advance_to_data from invalid state {self.state.name}"
            )
        self.dummy_cycles_remaining = int(dummy_cycles)
        self.state = FlashState.DATA

    def apply_write_enable_command(self) -> None:
        """Handle Write Enable (0x06): set WEL while in COMMAND/IDLE path."""
        self.set_write_enable()
        self.command = CMD_WRITE_ENABLE
