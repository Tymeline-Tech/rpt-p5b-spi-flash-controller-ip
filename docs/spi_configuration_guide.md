# SPI Configuration & Command Sequences — `spi_flash_ctrl`

This is the operational guide for software that drives the SPI Flash
Controller IP. Register fields are defined in
[`register_map.md`](register_map.md); this guide covers how to use them.
Every sequence below was checked against `rtl/spi_master.sv` and against the
cocotb regression in `tb/` (`test_read_status_commands.py`,
`test_program_erase.py`, `test_fifo_interrupt_stress.py`), which drives the
controller against a SPI NOR flash model.

## 1. SPI Master Configuration

### 1.1 SPI mode (CPOL / CPHA)

The mode is set in `CTRL.MODE` (bits 2:1). `MODE[1]` is CPOL and `MODE[0]` is
CPHA.

| Mode | CTRL.MODE | CPOL | CPHA | SCLK idle | MOSI changes on | MISO sampled on |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0b00 | 0 | 0 | Low | Falling edge | Rising edge |
| 3 | 0b11 | 1 | 1 | High | Falling edge | Rising edge |

SPI NOR flashes accept Mode 0 and Mode 3, and both are covered by the
regression. Modes 1 and 2 are accepted by the register but not verified; do
not use them.

Behaviour common to both modes:

- Data is MSB first on MOSI and MISO.
- `cs_n` goes low for the command, address and data phases of one transaction
  and returns high at the end of it. Each START is exactly one chip-select
  frame.
- SCLK rests at its CPOL level whenever `cs_n` is high.
- MODE is latched with START. Because every CTRL write also rewrites MODE,
  always write the mode in the same word as START (§1.4).

### 1.2 Clock divider

SCLK is derived from the APB clock `clk`. The engine toggles SCLK every
`CLKDIV.DIV + 1` cycles of `clk`:

```
f_SCLK = f_clk / (2 × (DIV + 1))          DIV = 0 … 255
DIV    = ceil(f_clk / (2 × f_SCLK_max)) − 1
```

Rounding DIV up keeps SCLK at or below the flash's limit.

Some divider values at a 50 MHz APB clock:

| DIV | Divide ratio | f_SCLK | SCLK period |
| --- | --- | --- | --- |
| 0 | 2 | 25.000 MHz | 40 ns |
| 1 | 4 | 12.500 MHz | 80 ns |
| 2 | 6 | 8.333 MHz | 120 ns |
| 3 | 8 | 6.250 MHz | 160 ns |
| 4 | 10 | 5.000 MHz | 200 ns |
| 9 | 20 | 2.500 MHz | 400 ns |
| 24 | 50 | 1.000 MHz | 1 µs |
| 49 | 100 | 500 kHz | 2 µs |
| 124 | 250 | 200 kHz | 5 µs |
| 255 | 512 | 97.656 kHz | 10.24 µs |

Choosing DIV:

- Read (0x03) is usually specified at a lower maximum frequency than Fast Read
  (0x0B), commonly 33–50 MHz against 80 MHz or more. Check your flash's
  datasheet.
- At a 50 MHz APB clock this controller tops out at 25 MHz SCLK, which is
  within every common SPI NOR's limit for both commands. The regression runs
  at `DIV = 1`.
- CLKDIV is latched with START, so it can be changed between transactions.

### 1.3 FIFOs

| FIFO | Depth | Filled by | Drained by |
| --- | --- | --- | --- |
| TX | 16 bytes | Software, writes to DATA | Engine: Page Program payload, or one dummy per Read / Fast Read beat |
| RX | 16 bytes | Engine: Read, Fast Read, Read Status | Software, reads from DATA |

- A write to DATA while `STATUS.TXF = 1` is dropped silently.
- A read from DATA while `STATUS.RXE = 1` returns stale data and pops nothing.
- Drain the RX FIFO before starting any read command. A read started with a
  full RX FIFO skips its data phase (see register_map.md §4.3).

### 1.4 C helpers used in the examples

```c
#include <stdint.h>
#include <stddef.h>

#define SPIF_BASE        0x40010000u            /* SoC-specific */
#define SPIF_REG(off)    (*(volatile uint32_t *)(SPIF_BASE + (off)))

#define SPIF_CTRL        SPIF_REG(0x00)
#define SPIF_STATUS      SPIF_REG(0x04)
#define SPIF_CMD         SPIF_REG(0x08)
#define SPIF_ADDR        SPIF_REG(0x0C)
#define SPIF_DATA        SPIF_REG(0x10)
#define SPIF_CLKDIV      SPIF_REG(0x14)

#define CTRL_START       (1u << 0)
#define CTRL_MODE(m)     (((uint32_t)(m) & 0x3u) << 1)   /* m = 0 or 3 */

#define STATUS_BUSY      (1u << 0)
#define STATUS_IRQ       (1u << 1)
#define STATUS_TXF       (1u << 2)
#define STATUS_RXE       (1u << 3)

/* SPI NOR opcodes supported by the controller */
#define OP_READ          0x03u
#define OP_FAST_READ     0x0Bu
#define OP_PAGE_PROGRAM  0x02u
#define OP_SECTOR_ERASE  0x20u
#define OP_READ_STATUS   0x05u
#define OP_WRITE_ENABLE  0x06u

/* Flash status register bits (standard SPI NOR) */
#define SR_WIP           (1u << 0)   /* write in progress */
#define SR_WEL           (1u << 1)   /* write enable latch */

static uint32_t spif_mode = 0;       /* 0 or 3 */

/* Configure mode and divider. Takes effect at the next START. */
void spif_configure(unsigned mode, uint8_t div)
{
    spif_mode = (mode == 3u) ? 3u : 0u;
    SPIF_CLKDIV = div;
    SPIF_CTRL   = CTRL_MODE(spif_mode);              /* no START */
}

/* Divider for a target maximum SCLK, rounded so SCLK never exceeds it. */
uint8_t spif_div_for(uint32_t f_clk_hz, uint32_t f_sclk_max_hz)
{
    uint32_t div = (f_clk_hz + 2u * f_sclk_max_hz - 1u) / (2u * f_sclk_max_hz);
    div = (div == 0u) ? 0u : div - 1u;
    return (div > 255u) ? 255u : (uint8_t)div;
}

static void spif_wait_idle(void)
{
    while (SPIF_STATUS & STATUS_BUSY) { }
}

static void spif_drain_rx(void)
{
    while (!(SPIF_STATUS & STATUS_RXE)) { (void)SPIF_DATA; }
}

/* Start the programmed transaction and wait for it (polling).
 * Interrupt-driven code would return here and wait for the irq pin instead. */
static void spif_start_and_wait(void)
{
    SPIF_CTRL = CTRL_MODE(spif_mode) | CTRL_START;
    spif_wait_idle();
    SPIF_STATUS = 0;                                 /* any write clears IRQ */
}
```

Example: run the bus at no more than 20 MHz from a 50 MHz APB clock in Mode 0.

```c
spif_configure(0, spif_div_for(50000000u, 20000000u));   /* DIV = 1 → 12.5 MHz */
```

`spif_div_for` returns `DIV = 1` here: `DIV = 0` would give 25 MHz, above the
20 MHz limit.

### 1.5 Completion and interrupts

Every transaction ends the same way. `STATUS.BUSY` falls, then `STATUS.IRQ`
and the `irq` pin rise and stay high until software writes STATUS. This holds
for command-only transactions such as Write Enable.

- **Polling:** wait for BUSY = 0, then write STATUS to clear IRQ.
- **Interrupt:** start the transaction and return. In the handler, write
  STATUS to clear IRQ, then read RX data or start the next step.

A START written while BUSY = 1 is ignored without any error, so always wait
for completion before starting the next command.

Transaction done is not the same as flash operation done. After Page Program
or Sector Erase, the flash keeps working internally for microseconds to
milliseconds. Poll the flash's WIP bit with Read Status (§2.5) before issuing
the next program, erase or read.

## 2. Supported Commands

Prototypes:

```c
void    spif_write_enable(void);                                       /* 0x06 */
uint8_t spif_read_status(void);                                        /* 0x05 */
void    spif_read(uint32_t addr, uint8_t *buf, size_t len);            /* 0x03, len 1..16 */
void    spif_fast_read(uint32_t addr, uint8_t *buf, size_t len);       /* 0x0B, len 1..16 */
void    spif_page_program(uint32_t addr, const uint8_t *buf, size_t len); /* 0x02, len 1..16 */
void    spif_sector_erase(uint32_t addr);                              /* 0x20 */
void    spif_wait_wip_clear(void);
```

### 2.1 Write Enable (0x06)

Sets the flash's Write Enable Latch (WEL). The flash requires it before every
Page Program and Sector Erase, and clears WEL itself when the operation
completes.

| Step | Access |
| --- | --- |
| 1 | Wait for STATUS.BUSY = 0 |
| 2 | Write CMD = 0x06 |
| 3 | Write CTRL = MODE \| START |
| 4 | Wait for completion; write STATUS to clear IRQ |

Frame on the bus: one byte, `06`. No address and no data.

```c
void spif_write_enable(void)
{
    spif_wait_idle();
    SPIF_CMD = OP_WRITE_ENABLE;
    spif_start_and_wait();
}
```

### 2.2 Read (0x03)

Reads 1 to 16 bytes from `addr`. The read length equals the number of dummy
bytes in the TX FIFO.

| Step | Access |
| --- | --- |
| 1 | Wait for STATUS.BUSY = 0; drain the RX FIFO |
| 2 | Write CMD = 0x03, ADDR = address |
| 3 | Write DATA = 0x00 once per byte to read (N writes, N ≤ 16) |
| 4 | Write CTRL = MODE \| START |
| 5 | Wait for completion; write STATUS to clear IRQ |
| 6 | Read DATA N times (each read pops one byte from the RX FIFO) |

Frame on the bus: `03 A23–A16 A15–A8 A7–A0`, then N data bytes clocked in on
MISO.

```c
void spif_read(uint32_t addr, uint8_t *buf, size_t len)
{
    spif_wait_idle();
    spif_drain_rx();
    SPIF_CMD  = OP_READ;
    SPIF_ADDR = addr & 0xFFFFFFu;
    for (size_t i = 0; i < len; i++) SPIF_DATA = 0x00;   /* one dummy per byte */
    spif_start_and_wait();
    for (size_t i = 0; i < len; i++) buf[i] = (uint8_t)SPIF_DATA;
}
```

`len` must be between 1 and 16. With 0 dummies the transaction never
completes; see register_map.md §4.3.

### 2.3 Fast Read (0x0B)

Same as Read, but the engine inserts one dummy byte (0x00, eight SCLK cycles)
after the address, so the flash can run at its higher Fast Read frequency.
Software does nothing extra for that dummy byte: the TX dummies still set the
data length.

| Step | Access |
| --- | --- |
| 1–6 | As Read, with CMD = 0x0B |

Frame on the bus: `0B A23–A16 A15–A8 A7–A0 00`, then N data bytes.

```c
void spif_fast_read(uint32_t addr, uint8_t *buf, size_t len)
{
    spif_wait_idle();
    spif_drain_rx();
    SPIF_CMD  = OP_FAST_READ;
    SPIF_ADDR = addr & 0xFFFFFFu;
    for (size_t i = 0; i < len; i++) SPIF_DATA = 0x00;
    spif_start_and_wait();
    for (size_t i = 0; i < len; i++) buf[i] = (uint8_t)SPIF_DATA;
}
```

### 2.4 Page Program (0x02)

Programs 1 to 16 bytes at `addr`. The flash must be write-enabled first, and
the target bytes must already be erased (0xFF).

| Step | Access |
| --- | --- |
| 1 | Write Enable (§2.1) |
| 2 | Wait for STATUS.BUSY = 0 |
| 3 | Write CMD = 0x02, ADDR = address |
| 4 | Write DATA once per payload byte (N ≤ 16, all before START) |
| 5 | Write CTRL = MODE \| START |
| 6 | Wait for completion; write STATUS to clear IRQ |
| 7 | Poll Read Status until WIP = 0 (§2.5) |

Frame on the bus: `02 A23–A16 A15–A8 A7–A0 D0 … D(N−1)`. The data phase ends
when the TX FIFO is empty.

Rules from the flash, not the controller:

- A program must not cross a 256-byte page boundary. If it does, most SPI NOR
  parts wrap within the page and overwrite its start. Keep
  `(addr & 0xFF) + len <= 256`.
- Programming can only change bits from 1 to 0. Erase first.

```c
void spif_page_program(uint32_t addr, const uint8_t *buf, size_t len)
{
    spif_write_enable();
    spif_wait_idle();
    SPIF_CMD  = OP_PAGE_PROGRAM;
    SPIF_ADDR = addr & 0xFFFFFFu;
    for (size_t i = 0; i < len; i++) SPIF_DATA = buf[i];  /* len <= 16 */
    spif_start_and_wait();
    spif_wait_wip_clear();
}
```

Programming a whole 256-byte page takes 16 such calls of 16 bytes each.

### 2.5 Read Status Register (0x05)

Returns one byte, the flash status register. Bit 0 is WIP (write in progress)
and bit 1 is WEL (write enable latch) on standard SPI NOR parts.

| Step | Access |
| --- | --- |
| 1 | Wait for STATUS.BUSY = 0; drain the RX FIFO |
| 2 | Write CMD = 0x05 (ADDR is not used) |
| 3 | Write CTRL = MODE \| START |
| 4 | Wait for completion; write STATUS to clear IRQ |
| 5 | Read DATA once |

No TX dummy is needed. Read Status always returns exactly one byte.

Frame on the bus: `05`, then one status byte.

```c
uint8_t spif_read_status(void)
{
    spif_wait_idle();
    spif_drain_rx();
    SPIF_CMD = OP_READ_STATUS;
    spif_start_and_wait();
    return (uint8_t)SPIF_DATA;
}

void spif_wait_wip_clear(void)
{
    while (spif_read_status() & SR_WIP) { }
}
```

### 2.6 Sector Erase (0x20)

Erases the 4 KB sector containing `addr` (all bytes become 0xFF). Needs Write
Enable first.

| Step | Access |
| --- | --- |
| 1 | Write Enable (§2.1) |
| 2 | Wait for STATUS.BUSY = 0 |
| 3 | Write CMD = 0x20, ADDR = any address inside the sector |
| 4 | Write CTRL = MODE \| START |
| 5 | Wait for completion; write STATUS to clear IRQ |
| 6 | Poll Read Status until WIP = 0. A sector erase typically takes tens to hundreds of milliseconds |

Frame on the bus: `20 A23–A16 A15–A8 A7–A0`. No data. The TX FIFO must be
empty: the engine has no data phase for this opcode, so leftover TX bytes stay
in the FIFO and become the payload or dummies of the next command.

```c
void spif_sector_erase(uint32_t addr)
{
    spif_write_enable();
    spif_wait_idle();
    SPIF_CMD  = OP_SECTOR_ERASE;
    SPIF_ADDR = addr & 0xFFF000u;
    spif_start_and_wait();
    spif_wait_wip_clear();
}
```

## 3. Typical flow: erase, program, verify

```c
uint8_t page[16] = { /* payload */ };
uint8_t check[16];

spif_configure(0, spif_div_for(50000000u, 20000000u));
spif_sector_erase(0x001000);
spif_page_program(0x001000, page, sizeof page);
spif_read(0x001000, check, sizeof check);
/* compare page[] and check[] */
```

The regression covers the parts of this flow in Mode 0 and Mode 3:

- `test_program_erase.py` checks that Write Enable sets WEL and that Page
  Program writes the bytes and clears WEL. It also checks that Sector Erase
  turns its 4 KB sector to 0xFF and leaves the next sector alone. Both checks
  read the flash model directly.
- `test_read_status_commands.py` checks Read and Fast Read data through the RX
  FIFO.

## 4. Limits of this version

| Limit | Value | Source |
| --- | --- | --- |
| Opcodes | 0x03, 0x0B, 0x02, 0x20, 0x05, 0x06 | `spi_master.sv` command decode |
| Address width | 24 bits (16 MB) | ADDR[23:0] |
| Bytes per Read / Fast Read / Program | 1–16 per START | FIFO depth |
| SCLK | f_clk / 2 to f_clk / 512 | CLKDIV |
| Lanes | Single (MOSI/MISO). No dual or quad I/O | Top-level ports |
| Flash busy handling | Software polls WIP; the controller does not | No auto-poll in RTL |
