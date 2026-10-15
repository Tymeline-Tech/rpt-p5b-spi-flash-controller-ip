# APB Register Map — `spi_flash_ctrl`

This is the host-facing reference for the SPI Flash Controller IP. Every
statement below was checked against `rtl/spi_reg_block.sv`,
`rtl/spi_master.sv` and the top-level wiring in `rtl/spi_flash_ctrl.sv` at the
commit this document ships with. If the RTL changes, update this file in the
same change.

The machine-readable version of the same map is
[`register_map.json`](register_map.json).

## 1. Bus interface

| Item | Value |
| --- | --- |
| Protocol | AMBA APB3 slave |
| Clock / reset | `clk` (PCLK), `rst_n` (PRESETn, active low, asynchronous assert) |
| Data width | 32 bits (`pwdata`, `prdata`) |
| Address decode | `paddr[7:0]` selects the register; `paddr[31:8]` must be 0 |
| Wait states | None. `pready` is tied to 1 |
| Error response | `perror` (PSLVERR) is high during the access phase of any access to an unmapped offset or with `paddr[31:8] != 0` |
| Byte strobes | Not supported (APB3 has no PSTRB). Every write is a full-word write |
| Interrupt | `irq`, level-high, equal to `STATUS.IRQ` |

Accesses complete in the APB access phase (`psel & penable`). A write to an
unmapped offset has no effect and returns `perror = 1`. A read from an
unmapped offset returns `0x0000_0000` with `perror = 1`.

## 2. Register summary

| Offset | Name | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 0x00 | CTRL | RW | 0x0000_0000 | Start pulse and SPI mode |
| 0x04 | STATUS | RO, write clears IRQ | see below | Engine and FIFO status, interrupt pending |
| 0x08 | CMD | RW | 0x0000_0000 | SPI opcode for the next transaction |
| 0x0C | ADDR | RW | 0x0000_0000 | 24-bit flash address for the next transaction |
| 0x10 | DATA | W: push TX FIFO / R: pop RX FIFO | — | FIFO data port |
| 0x14 | CLKDIV | RW | 0x0000_0000 | SCLK divider for the next transaction |

Offsets not in this table (including non-word-aligned offsets such as 0x01)
are unmapped.

## 3. Register details

In the tables below:

- **RW**: read/write.
- **RO**: read-only; writes are ignored.
- **WO-P**: write-only pulse; reads return 0.
- **RAZ/WI**: reads as zero, writes ignored.

### 3.1 CTRL — 0x00

| Bits | Field | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 31:3 | — | RAZ/WI | 0 | Reserved |
| 2:1 | MODE | RW | 0b00 | SPI mode. `0b00` = Mode 0 (CPOL 0, CPHA 0), `0b11` = Mode 3 (CPOL 1, CPHA 1). `MODE[1]` drives CPOL and `MODE[0]` drives CPHA. Only Modes 0 and 3 are verified; see §4.4 |
| 0 | START | WO-P | 0 | Writing 1 starts a transaction with the current CMD, ADDR, CLKDIV, MODE and FIFO contents. Reads return 0 |

Side effects:

- Every write to CTRL updates MODE from `pwdata[2:1]`, including a write that
  only sets START. Always write the mode you want together with START.
- START is registered: the SPI engine sees it one clock after the APB access.
- START is honoured only while the engine is idle (`STATUS.BUSY = 0`). A START
  written while busy is dropped silently; there is no error and no queueing.

### 3.2 STATUS — 0x04

| Bits | Field | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 31:4 | — | RAZ/WI | 0 | Reserved |
| 3 | RXE | RO | 1 | RX FIFO empty |
| 2 | TXF | RO | 0 | TX FIFO full |
| 1 | IRQ | RO, cleared by any write to STATUS | 0 | Transaction-complete interrupt pending. Mirrors the `irq` pin |
| 0 | BUSY | RO | 0 | SPI engine busy (any state other than idle) |

Side effects:

- **IRQ is set on event, cleared on write.** IRQ is set for one engine cycle
  when a transaction reaches its DONE state. It stays set until software
  writes STATUS. The written value is ignored: writing `0x0` clears IRQ just
  as `0x2` does, so this is "write-any-to-clear", not write-1-to-clear.
- If a transaction completes in the same cycle as a STATUS write, the
  completion wins and IRQ stays set.
- The reset value of RXE is 1 because both FIFOs reset empty.

### 3.3 CMD — 0x08

| Bits | Field | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 31:8 | — | RAZ/WI | 0 | Reserved |
| 7:0 | OPCODE | RW | 0x00 | SPI NOR opcode sent in the command phase |

The engine recognises six opcodes and derives the transaction shape from them:

| Opcode | Command | Address phase | Data phase |
| --- | --- | --- | --- |
| 0x03 | Read | 3 bytes | RX, one byte per TX dummy byte (§4.3) |
| 0x0B | Fast Read | 3 bytes + 1 dummy byte (0x00) | RX, one byte per TX dummy byte |
| 0x02 | Page Program | 3 bytes | TX, all bytes in the TX FIFO |
| 0x20 | Sector Erase (4 KB) | 3 bytes | None |
| 0x05 | Read Status Register | None | RX, exactly 1 byte |
| 0x06 | Write Enable | None | None |

Any other opcode is sent as a command-only transaction (one byte, no address,
no data). This lets the FSM always complete; it is not a supported way to
issue other flash commands.

CMD is latched by the engine when START is accepted. Writing CMD while BUSY is
1 changes only the next transaction.

### 3.4 ADDR — 0x0C

| Bits | Field | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 31:24 | — | RAZ/WI | 0 | Reserved. Ignored on write |
| 23:0 | ADDRESS | RW | 0x000000 | Flash byte address, sent MSB first in the address phase |

ADDR is latched when START is accepted. It is not incremented by the
controller; software sets it for each transaction.

### 3.5 DATA — 0x10

| Direction | Bits | Behaviour |
| --- | --- | --- |
| Write | 7:0 | Pushes `pwdata[7:0]` into the 16-entry TX FIFO. `pwdata[31:8]` is ignored |
| Read | 7:0 | Returns the byte at the head of the 16-entry RX FIFO and pops it. `prdata[31:8]` read as 0 |

Side effects and limits:

- **Write when TX full:** if `STATUS.TXF = 1`, the byte is dropped silently.
  There is no `perror`. Check TXF before pushing.
- **Read when RX empty:** if `STATUS.RXE = 1`, nothing is popped. The RX FIFO is
  first-word fall-through, so the value returned is the stale byte in the
  next slot (0 after reset), not new data. Check RXE before reading.
- The TX FIFO feeds two things: the payload of Page Program, and the dummy
  bytes that set the length of Read / Fast Read (§4.3).

### 3.6 CLKDIV — 0x14

| Bits | Field | Access | Reset | Description |
| --- | --- | --- | --- | --- |
| 31:8 | — | RAZ/WI | 0 | Reserved |
| 7:0 | DIV | RW | 0x00 | SCLK divider |

The engine toggles SCLK every `DIV + 1` cycles of `clk`, so

```
f_SCLK = f_clk / (2 × (DIV + 1))
```

`DIV = 0` gives the fastest clock, `f_clk / 2`. `DIV = 255` gives
`f_clk / 512`. CLKDIV is latched when START is accepted. Full frequency
tables are in [`spi_configuration_guide.md`](spi_configuration_guide.md).

## 4. Interaction rules

### 4.1 Starting a transaction

1. Wait for `STATUS.BUSY = 0`.
2. Write CMD, ADDR (if the opcode has an address) and CLKDIV (if it changed).
3. Push TX bytes to DATA if the opcode needs them (Page Program payload, or
   Read / Fast Read dummies).
4. Write CTRL with `START = 1` and the wanted MODE.

### 4.2 Completion — "Command Start" and "Command Done"

- **Command start** is CTRL.START. It is a one-shot pulse; there is no
  "command running" bit to clear.
- **Command done** is signalled two ways, and software may use either:
  - **Polling:** `STATUS.BUSY` rises within a few cycles of START and falls
    when the transaction ends.
  - **Interrupt:** `STATUS.IRQ` (and the `irq` pin) is set at the end of every
    transaction, including command-only ones such as Write Enable. Clear it by
    writing STATUS.
- Done means the SPI transfer is finished and `cs_n` is high again. It does
  **not** mean the flash has finished an internal program or erase. For those,
  poll the flash's own Write-In-Progress bit with Read Status (0x05); see the
  configuration guide.

### 4.3 How data length is set

| Command | Length rule |
| --- | --- |
| Page Program (0x02) | The data phase sends bytes until the TX FIFO is empty. Push the whole payload (up to 16 bytes) before START |
| Read (0x03), Fast Read (0x0B) | The data phase receives one byte for every byte in the TX FIFO. Push N dummy bytes (any value; 0x00 is conventional) to read N bytes, N ≤ 16 |
| Read Status (0x05) | Always 1 byte |

If the RX FIFO fills during a read, the engine holds SCLK until a byte is
popped. A read longer than 16 bytes therefore needs software to drain DATA
while BUSY is 1. Only reads of up to 16 bytes are covered by the regression.

Two hazards follow from these rules. Both come from `spi_master.sv` and are
not checked by the hardware:

- **Read or Fast Read with an empty TX FIFO never completes.** The engine
  enters the data phase but has no dummy byte to start a beat, so BUSY stays
  1 and no interrupt is raised. Only reset recovers. Always push at least one
  dummy byte before starting a read.
- **A read started while the RX FIFO is full skips its data phase.** The engine
  goes straight from the address (or command) phase to DONE and raises IRQ,
  but nothing was read. Drain the RX FIFO (`STATUS.RXE = 1`) before starting
  Read, Fast Read or Read Status.

A Page Program started with an empty TX FIFO sends only the opcode and
address, then completes normally.

### 4.4 Modes 1 and 2

MODE accepts `0b01` and `0b10`, and the engine will drive the matching
CPOL/CPHA. These modes are not exercised by the regression and SPI NOR
flashes generally support only Modes 0 and 3. Do not use them.

## 5. Reset values at a glance

| Register | Reset value |
| --- | --- |
| CTRL | 0x0000_0000 (Mode 0) |
| STATUS | 0x0000_0008 (RXE = 1) |
| CMD | 0x0000_0000 |
| ADDR | 0x0000_0000 |
| CLKDIV | 0x0000_0000 (f_clk / 2) |

## 6. Known RTL details worth knowing

- `perror` contains a term `(~pwdata_hi_zero & 1'b0)` that is always 0. It
  exists only to keep `pwdata[31:24]` from being reported unused by lint.
  `pwdata[31:24]` never causes an error.
- The README's register table describes STATUS as "R/W1C". The RTL clears IRQ
  on any write, regardless of the value written (§3.2).
