// SPI Flash Controller top-level — stub interconnect
// Instantiates spi_reg_block, spi_tx_fifo, spi_rx_fifo, and spi_master,
// and wires APB (host) and SPI (flash) pins through those stubs.
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

    // Interrupt
    output logic        irq,

    // SPI master (external flash)
    output logic        sclk,
    output logic        mosi,
    input  logic        miso,
    output logic        cs_n
);

    // -------------------------------------------------------------------------
    // Reg-to-SPI control / status
    // -------------------------------------------------------------------------
    logic        start;
    logic [7:0]  cmd;
    logic [23:0] addr;
    logic [7:0]  clk_div;
    logic [1:0]  spi_mode;
    logic        busy;
    logic        done;

    // -------------------------------------------------------------------------
    // FIFO-to-Reg / Reg-to-FIFO (APB side of FIFOs)
    // -------------------------------------------------------------------------
    logic [7:0]  tx_wr_data;
    logic        tx_wr_en;
    logic        tx_full;
    logic [7:0]  rx_rd_data;
    logic        rx_rd_en;
    logic        rx_empty;

    // -------------------------------------------------------------------------
    // SPI-to-FIFO / FIFO-to-SPI (engine side of FIFOs)
    // -------------------------------------------------------------------------
    logic [7:0]  tx_rd_data;
    logic        tx_rd_en;
    logic        tx_empty;
    logic        tx_rd_valid;
    logic        tx_wr_ready;

    logic [7:0]  rx_wr_data;
    logic        rx_wr_en;
    logic        rx_full;
    logic        rx_wr_ready;
    logic        rx_rd_valid;

    // SPI master byte status (stub; not forwarded to APB yet)
    logic [7:0]  spi_rx_data;
    logic        spi_rx_valid;

    // -------------------------------------------------------------------------
    // APB-to-Reg: top-level APB pins drive the register block
    // -------------------------------------------------------------------------
    spi_reg_block u_reg_block (
        .clk        (clk),
        .rst_n      (rst_n),
        .psel       (psel),
        .penable    (penable),
        .pwrite     (pwrite),
        .paddr      (paddr),
        .pwdata     (pwdata),
        .pready     (pready),
        .prdata     (prdata),
        .perror     (perror),
        .start      (start),
        .cmd        (cmd),
        .addr       (addr),
        .clk_div    (clk_div),
        .spi_mode   (spi_mode),
        .tx_wr_data (tx_wr_data),
        .tx_wr_en   (tx_wr_en),
        .tx_full    (tx_full),
        .rx_rd_data (rx_rd_data),
        .rx_rd_en   (rx_rd_en),
        .rx_empty   (rx_empty),
        .busy             (busy),
        .spi_txn_complete (done),
        .irq              (irq)
    );

    // -------------------------------------------------------------------------
    // TX FIFO: Reg write port <-> SPI master read port (16 x 8)
    // -------------------------------------------------------------------------
    spi_tx_fifo #(
        .DEPTH (16),
        .WIDTH (8)
    ) u_tx_fifo (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_valid (tx_wr_en),
        .wr_data  (tx_wr_data),
        .wr_ready (tx_wr_ready),
        .rd_ready (tx_rd_en),
        .rd_data  (tx_rd_data),
        .rd_valid (tx_rd_valid),
        .full     (tx_full),
        .empty    (tx_empty)
    );

    // -------------------------------------------------------------------------
    // RX FIFO: SPI master write port <-> Reg read port (16 x 8)
    // -------------------------------------------------------------------------
    spi_rx_fifo #(
        .DEPTH (16),
        .WIDTH (8)
    ) u_rx_fifo (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_valid (rx_wr_en),
        .wr_data  (rx_wr_data),
        .wr_ready (rx_wr_ready),
        .rd_ready (rx_rd_en),
        .rd_data  (rx_rd_data),
        .rd_valid (rx_rd_valid),
        .full     (rx_full),
        .empty    (rx_empty)
    );

    // -------------------------------------------------------------------------
    // Top-level SPI pins <-> SPI master; control/FIFO links to reg block
    // -------------------------------------------------------------------------
    spi_master u_spi_master (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .cmd_byte    (cmd),
        .addr_word   (addr),
        .clk_div     (clk_div),
        .spi_mode    (spi_mode),
        .tx_rd_data  (tx_rd_data),
        .tx_rd_empty (tx_empty),
        .tx_rd_en    (tx_rd_en),
        .rx_wr_data  (rx_wr_data),
        .rx_wr_en    (rx_wr_en),
        .rx_wr_full  (rx_full),
        .busy        (busy),
        .done        (done),
        .rx_data     (spi_rx_data),
        .rx_valid    (spi_rx_valid),
        .sclk_out    (sclk),
        .mosi_out    (mosi),
        .miso_in     (miso),
        .cs_n_out    (cs_n)
    );

    // Silence unused intermediate stub handshake / status nets
    logic unused_ok;
    always_comb begin
        unused_ok = ^{tx_wr_ready, tx_rd_valid, rx_wr_ready, rx_rd_valid,
                      spi_rx_data, spi_rx_valid};
    end

endmodule
