// APB Register Block — interface stub (placeholder logic)
// APB3 slave with immediate ready; control outputs tied off.
`timescale 1ns/1ps

module spi_reg_block (
    input  logic        clk,
    input  logic        rst_n,

    // APB3 slave
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [31:0] paddr,
    input  logic [31:0] pwdata,
    output logic        pready,
    output logic [31:0] prdata,
    output logic        perror,

    // SPI engine control
    output logic        start,
    output logic [7:0]  cmd,
    output logic [23:0] addr,
    output logic [7:0]  clk_div,
    output logic [1:0]  spi_mode,

    // TX FIFO write side
    output logic [7:0]  tx_wr_data,
    output logic        tx_wr_en,
    input  logic        tx_full,

    // RX FIFO read side
    input  logic [7:0]  rx_rd_data,
    output logic        rx_rd_en,
    input  logic        rx_empty,

    // Status from SPI engine / interrupt
    input  logic        busy,
    input  logic        done,
    output logic        irq
);

    // Immediate APB completion, zero read data, no error
    assign pready = 1'b1;
    assign prdata = 32'h0;
    assign perror = 1'b0;

    // Internal control outputs quiescent
    assign start      = 1'b0;
    assign cmd        = 8'h0;
    assign addr       = 24'h0;
    assign clk_div    = 8'h0;
    assign spi_mode   = 2'b00;
    assign tx_wr_data = 8'h0;
    assign tx_wr_en   = 1'b0;
    assign rx_rd_en   = 1'b0;
    assign irq        = 1'b0;

    // Consume unused inputs (no latches / unused warnings)
    logic unused_ok;
    always_comb begin
        unused_ok = ^{clk, rst_n, psel, penable, pwrite, paddr, pwdata,
                      tx_full, rx_rd_data, rx_empty, busy, done};
    end

endmodule
