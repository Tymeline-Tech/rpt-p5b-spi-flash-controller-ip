// SPI Flash Controller top-level — functional interconnect
// Instantiates spi_reg_block, spi_tx_fifo, spi_rx_fifo, and spi_master,
// wiring APB (host) control through the register block to the SPI engine
// and data through the TX/RX FIFOs (MOSI from TX FIFO, MISO to RX FIFO).
`timescale 1ns/1ps

module spi_flash_ctrl (
    input  logic        clk,
    input  logic        rst_n,

    // APB3 slave (host)
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [31:0] paddr,
    input  logic [31:0] pwdata,
    output logic        pready,
    output logic [31:0] prdata,
    output logic        perror,

    // Interrupt (from APB register block)
    output logic        irq,

    // SPI master (external flash)
    output logic        sclk,
    output logic        mosi,
    input  logic        miso,
    output logic        cs_n
);

    // -------------------------------------------------------------------------
    // APB block → SPI engine control / status
    // -------------------------------------------------------------------------
    logic        start;
    logic [7:0]  spi_cmd;
    logic [23:0] spi_addr;
    logic [7:0]  clk_div;
    logic [1:0]  spi_mode;
    logic        busy;
    logic        spi_complete;       // spi_txn_complete from SPI engine → APB
    logic        spi_txn_complete;

    assign spi_txn_complete = spi_complete;

    // -------------------------------------------------------------------------
    // APB side of FIFOs: tx_write/tx_data into TX; rx_read/rx_data from RX
    // -------------------------------------------------------------------------
    logic [7:0]  tx_data;
    logic        tx_write;
    logic        tx_full;
    logic [7:0]  rx_data;
    logic        rx_read;
    logic        rx_empty;

    // -------------------------------------------------------------------------
    // SPI engine side of FIFOs (valid/ready) — MOSI from TX, MISO to RX
    // -------------------------------------------------------------------------
    logic [7:0]  tx_rd_data;
    logic        tx_rd_ready;
    logic        tx_empty;
    logic        tx_rd_valid;

    logic [7:0]  rx_wr_data;
    logic        rx_wr_valid;
    logic        rx_full;
    logic        rx_wr_ready;

    // -------------------------------------------------------------------------
    // APB register block (master control) + IRQ to top-level
    // -------------------------------------------------------------------------
    spi_reg_block u_reg_block (
        .clk              (clk),
        .rst_n            (rst_n),
        .psel             (psel),
        .penable          (penable),
        .pwrite           (pwrite),
        .paddr            (paddr),
        .pwdata           (pwdata),
        .pready           (pready),
        .prdata           (prdata),
        .perror           (perror),
        .start            (start),
        .cmd              (spi_cmd),
        .addr             (spi_addr),
        .clk_div          (clk_div),
        .spi_mode         (spi_mode),
        .tx_wr_data       (tx_data),
        .tx_wr_en         (tx_write),
        .tx_full          (tx_full),
        .tx_empty         (tx_empty),
        .rx_rd_data       (rx_data),
        .rx_rd_en         (rx_read),
        .rx_empty         (rx_empty),
        .rx_full          (rx_full),
        .busy             (busy),
        .spi_txn_complete (spi_txn_complete),
        .irq              (irq)
    );

    // -------------------------------------------------------------------------
    // TX FIFO: APB write port → SPI master read port (16 x 8) → MOSI
    // -------------------------------------------------------------------------
    spi_tx_fifo #(
        .DEPTH (16),
        .WIDTH (8)
    ) u_tx_fifo (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_valid (tx_write),
        .wr_data  (tx_data),
        // ~full; STATUS already exposes TXF/TXE — leave complement unconnected
        /* verilator lint_off PINCONNECTEMPTY */
        .wr_ready (),
        /* verilator lint_on PINCONNECTEMPTY */
        .rd_ready (tx_rd_ready),
        .rd_data  (tx_rd_data),
        .rd_valid (tx_rd_valid),
        .full     (tx_full),
        .empty    (tx_empty)
    );

    // -------------------------------------------------------------------------
    // RX FIFO: SPI master write port (MISO) → APB read port (16 x 8)
    // -------------------------------------------------------------------------
    spi_rx_fifo #(
        .DEPTH (16),
        .WIDTH (8)
    ) u_rx_fifo (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_valid (rx_wr_valid),
        .wr_data  (rx_wr_data),
        .wr_ready (rx_wr_ready),
        .rd_ready (rx_read),
        .rd_data  (rx_data),
        // ~empty; STATUS already exposes RXE/RXF — leave complement unconnected
        /* verilator lint_off PINCONNECTEMPTY */
        .rd_valid (),
        /* verilator lint_on PINCONNECTEMPTY */
        .full     (rx_full),
        .empty    (rx_empty)
    );

    // -------------------------------------------------------------------------
    // SPI master engine: control from APB block; data via TX/RX FIFOs
    // -------------------------------------------------------------------------
    spi_master u_spi_master (
        .clk              (clk),
        .rst_n            (rst_n),
        .start            (start),
        .cmd_byte         (spi_cmd),
        .addr_word        (spi_addr),
        .clk_div          (clk_div),
        .spi_mode         (spi_mode),
        .tx_rd_data       (tx_rd_data),
        .tx_rd_valid      (tx_rd_valid),
        .tx_rd_ready      (tx_rd_ready),
        .rx_wr_data       (rx_wr_data),
        .rx_wr_valid      (rx_wr_valid),
        .rx_wr_ready      (rx_wr_ready),
        .busy             (busy),
        .spi_txn_complete (spi_complete),
        .sclk_out         (sclk),
        .mosi_out         (mosi),
        .miso_in          (miso),
        .cs_n_out         (cs_n)
    );

endmodule
