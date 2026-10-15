// SPI Master Engine — interface stub (placeholder logic)
// Holds CS_N inactive (high) and SCLK low; no active timing generation.
`timescale 1ns/1ps

module spi_master (
    input  logic        clk,
    input  logic        rst_n,

    // Control from register block
    input  logic        start,
    input  logic [7:0]  cmd_byte,
    input  logic [23:0] addr_word,
    input  logic [7:0]  clk_div,
    input  logic [1:0]  spi_mode,

    // TX FIFO read interface
    input  logic [7:0]  tx_rd_data,
    input  logic        tx_rd_empty,
    output logic        tx_rd_en,

    // RX FIFO write interface
    output logic [7:0]  rx_wr_data,
    output logic        rx_wr_en,
    input  logic        rx_wr_full,

    // Status feedback
    output logic        busy,
    output logic        done,
    output logic [7:0]  rx_data,
    output logic        rx_valid,

    // SPI pins
    output logic        sclk_out,
    output logic        mosi_out,
    input  logic        miso_in,
    output logic        cs_n_out
);

    // Safe idle SPI bus: CS inactive, clock low (mode-0 idle)
    assign cs_n_out  = 1'b1;
    assign sclk_out  = 1'b0;
    assign mosi_out  = 1'b0;

    // No RX activity in stub
    assign rx_data   = 8'h00;
    assign rx_valid  = 1'b0;
    assign rx_wr_data = 8'h00;
    assign rx_wr_en   = 1'b0;

    // Not busy / not done; do not consume TX FIFO
    assign busy      = 1'b0;
    assign done      = 1'b0;
    assign tx_rd_en  = 1'b0;

    // Consume unused inputs (avoids latches and Verilator UNUSED warnings)
    logic unused_ok;
    always_comb begin
        unused_ok = ^{clk, rst_n, start, cmd_byte, addr_word, clk_div, spi_mode,
                      tx_rd_data, tx_rd_empty, rx_wr_full, miso_in};
    end

endmodule
