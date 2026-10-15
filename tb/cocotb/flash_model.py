"""SPI NOR flash behavioral model — memory, SPI decode, and MISO drive.

Provides a cycle-accurate Python class representing an external SPI NOR flash
device for independent verification of ``spi_flash_ctrl``. This module owns
the internal memory array, the SPI transaction state machine, Write Enable
(WEL) latch logic, SCLK/MOSI bit assembly with command decoding, and MISO
shift-out for Read (0x03), Fast Read (0x0B), and Read Status (0x05).
"""

from enum import Enum, auto

# 128 KiB device image
MEMORY_SIZE = 128 * 1024

# 4 KiB sector size for opcode 0x20 (Sector Erase)
SECTOR_SIZE = 4 * 1024

# 256-byte page for Page Program address wrap
PAGE_SIZE = 256

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

# Fast Read: one dummy byte = 8 SCLK cycles after the 24-bit address
FAST_READ_DUMMY_CYCLES = 8


class FlashState(Enum):
    """Master SPI frame state machine tracked by the flash model."""

    IDLE = auto()
    COMMAND = auto()
    ADDRESS = auto()
    DATA = auto()


class SpiNorFlash:
    """Behavioral SPI NOR flash: memory, WEL, SPI sampling, decode, and MISO.

    Parameters
    ----------
    None — constructed with a fixed 128 KiB array and WEL cleared.
    """

    def __init__(self):
        self.memory = bytearray(128 * 1024)
        self.wel = 0
        self.wip = 0
        self.state = FlashState.IDLE
        # Transaction context
        self.command = 0
        self.address = 0
        self.addr_byte_count = 0
        self.dummy_cycles_remaining = 0
        # SCLK/MOSI bit assembly (MSB-first; sample on rising SCLK)
        self._prev_sclk = 0
        self._bit_count = 0
        self._shift_in = 0
        # Page Program: armed for the rest of the CS frame after WEL accepted
        self._pp_armed = False
        # MISO shift-out (MSB-first; one bit per rising SCLK in DATA)
        self._miso = 0
        self._miso_sr = 0
        self._miso_bits = 0

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
        self._bit_count = 0
        self._shift_in = 0
        self._pp_armed = False
        self._clear_miso()
        # Leave _prev_sclk as-is so the next CS frame sees a correct edge.

    def begin_transaction(self) -> None:
        """Enter COMMAND on chip-select assert (start of a new SPI frame)."""
        self.state = FlashState.COMMAND
        self.command = 0
        self.address = 0
        self.addr_byte_count = 0
        self.dummy_cycles_remaining = 0
        self._bit_count = 0
        self._shift_in = 0
        self._pp_armed = False
        self._clear_miso()

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

    # ------------------------------------------------------------------
    # MISO drive (Read / Fast Read / Read Status)
    # ------------------------------------------------------------------

    def get_miso(self) -> int:
        """Return the current MISO output bit (0 or 1).

        During Read (0x03), Fast Read (0x0B), and Read Status (0x05) data
        phases, this is the bit currently being shifted out MSB-first. Outside
        an active shift-out the line idles at 0.
        """
        return int(self._miso) & 1

    def _clear_miso(self) -> None:
        """Idle the MISO shift-out path (CSN boundary / new frame)."""
        self._miso = 0
        self._miso_sr = 0
        self._miso_bits = 0

    def _miso_command_active(self) -> bool:
        """True when the current opcode streams bytes out on MISO."""
        return self.command in (CMD_READ, CMD_FAST_READ, CMD_READ_STATUS)

    def _queue_miso_byte(self) -> None:
        """Load the next status or memory byte into the MISO shift register."""
        if self.command == CMD_READ_STATUS:
            value = self.status_register()
        elif self.command in (CMD_READ, CMD_FAST_READ):
            value = self.read_byte(self.address)
            self.address = (self.address + 1) & 0xFFFFFF
        else:
            return
        self._miso_sr = int(value) & 0xFF
        self._miso_bits = 8

    def _clock_miso(self) -> None:
        """Present one MISO bit and advance the shift register (rising SCLK)."""
        if self._miso_bits == 0:
            self._queue_miso_byte()
        if self._miso_bits == 0:
            self._miso = 0
            return
        self._miso = (self._miso_sr >> 7) & 1
        self._miso_sr = (self._miso_sr << 1) & 0xFF
        self._miso_bits -= 1

    # ------------------------------------------------------------------
    # SCLK / MOSI sampling and command decoding
    # ------------------------------------------------------------------

    def process_sclk_mosi(self, sclk_val, mosi_val) -> None:
        """Process one SCLK sample with MOSI; call on every SCLK delta.

        Samples MOSI on the rising edge of SCLK (correct for SPI modes 0 and
        3), assembles bits MSB-first into bytes, and advances the SPI state
        machine: Command → Address → Data/Status. Handles:

        * ``0x06`` Write Enable — sets ``self.wel = 1``
        * ``0x20`` Sector Erase — erases a 4 KiB sector if WEL, then clears WEL
        * ``0x02`` Page Program — programs data bytes if WEL was set, then
          clears WEL (armed for the remainder of the CS frame)
        * ``0x03`` / ``0x0B`` Read / Fast Read — address then data (Fast Read
          consumes ``FAST_READ_DUMMY_CYCLES`` clocks before data); MISO
          shifts out memory bytes during DATA
        * ``0x05`` Read Status — enters DATA and shifts the status byte on MISO
        """
        sclk = int(sclk_val) & 1
        mosi = int(mosi_val) & 1
        rising = self._prev_sclk == 0 and sclk == 1
        self._prev_sclk = sclk

        if not rising or self.state is FlashState.IDLE:
            return

        # Fast Read dummy clocks: count rising edges, do not assemble bytes
        # or drive MISO data yet.
        if (
            self.state is FlashState.DATA
            and self.dummy_cycles_remaining > 0
        ):
            self.dummy_cycles_remaining -= 1
            return

        # Drive MISO before MOSI assembly so the edge that completes the
        # command/address byte does not consume a data bit (state is still
        # COMMAND/ADDRESS until _on_byte_received runs below).
        if self.state is FlashState.DATA and self._miso_command_active():
            self._clock_miso()

        # Shift in MSB first.
        self._shift_in = ((self._shift_in << 1) | mosi) & 0xFF
        self._bit_count += 1
        if self._bit_count < 8:
            return

        byte_val = self._shift_in
        self._bit_count = 0
        self._shift_in = 0
        self._on_byte_received(byte_val)

    def _on_byte_received(self, byte_val: int) -> None:
        """Dispatch a completed MOSI byte according to the SPI state machine."""
        if self.state is FlashState.COMMAND:
            self._decode_command_byte(byte_val)
        elif self.state is FlashState.ADDRESS:
            self._accumulate_address_byte(byte_val)
        elif self.state is FlashState.DATA:
            self._handle_data_byte(byte_val)

    def _decode_command_byte(self, cmd: int) -> None:
        """Identify the opcode and transition Command → Address / Data."""
        self.command = int(cmd) & 0xFF

        if self.command == CMD_WRITE_ENABLE:
            self.wel = 1
            # Command-only; remain in COMMAND until CSN deassert.
            return

        if self.command == CMD_READ_STATUS:
            self.advance_to_data(dummy_cycles=0)
            return

        if self.command in (
            CMD_READ,
            CMD_FAST_READ,
            CMD_PAGE_PROGRAM,
            CMD_SECTOR_ERASE,
        ):
            self.advance_to_address()
            return

        # Unsupported opcode: stay in COMMAND (bits still framed).

    def _accumulate_address_byte(self, byte_val: int) -> None:
        """Collect a 24-bit address MSB-first; then enter DATA or erase."""
        self.address = ((self.address << 8) | (int(byte_val) & 0xFF)) & 0xFFFFFF
        self.addr_byte_count += 1
        if self.addr_byte_count < 3:
            return

        if self.command == CMD_SECTOR_ERASE:
            if self.wel:
                self._sector_erase(self.address)
                self.wel = 0
            # No data phase after sector erase.
            self.state = FlashState.DATA
            self.dummy_cycles_remaining = 0
            return

        if self.command == CMD_FAST_READ:
            self.advance_to_data(dummy_cycles=FAST_READ_DUMMY_CYCLES)
            return

        if self.command == CMD_PAGE_PROGRAM:
            # Accept PP if WEL is set; clear WEL once the op is accepted.
            self._pp_armed = bool(self.wel)
            if self._pp_armed:
                self.wel = 0
            self.advance_to_data(dummy_cycles=0)
            return

        # CMD_READ and any other addressed opcode.
        self.advance_to_data(dummy_cycles=0)

    def _handle_data_byte(self, byte_val: int) -> None:
        """Consume a data-phase MOSI byte (Page Program writes; reads ignore)."""
        if self.command == CMD_PAGE_PROGRAM and self._pp_armed:
            addr = self._clamp_addr(self.address)
            # NOR flash program can only clear bits (AND with existing data).
            self.memory[addr] = self.memory[addr] & (int(byte_val) & 0xFF)
            # Advance within the current 256-byte page (typical NOR wrap).
            page_base = addr & ~(PAGE_SIZE - 1)
            next_off = ((addr + 1) & (PAGE_SIZE - 1))
            self.address = page_base | next_off
            return

        # CMD_READ / CMD_FAST_READ / CMD_READ_STATUS: MOSI don't-care during
        # DATA; address and status streaming are owned by the MISO path.
        # Post-erase DATA: ignore further MOSI bytes.

    def _sector_erase(self, addr: int) -> None:
        """Erase the 4 KiB sector containing ``addr`` (set bytes to 0xFF)."""
        base = self._clamp_addr(addr) & ~(SECTOR_SIZE - 1)
        for i in range(SECTOR_SIZE):
            self.memory[(base + i) & (MEMORY_SIZE - 1)] = 0xFF
