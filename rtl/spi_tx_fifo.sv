// TX FIFO — interface stub (16-entry depth parameter, placeholder logic)
`timescale 1ns/1ps

module spi_tx_fifo #(
    parameter int DEPTH = 16,
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,

    // Write port (from APB / reg block)
    input  logic             wr_valid,
    input  logic [WIDTH-1:0] wr_data,
    output logic             wr_ready,

    // Read port (to SPI master)
    input  logic             rd_ready,
    output logic [WIDTH-1:0] rd_data,
    output logic             rd_valid,

    // Status
    output logic             full,
    output logic             empty
);

    // Stub: always empty, never full, no data
    assign rd_data  = {WIDTH{1'b0}};
    assign full     = 1'b0;
    assign empty    = 1'b1;
    assign wr_ready = 1'b1;  // accept writes (discarded in stub)
    assign rd_valid = 1'b0;  // nothing to read

    // Keep DEPTH referenced for parameterization / synthesis
    localparam int DEPTH_CHK = DEPTH;

    // Consume unused inputs
    logic unused_ok;
    always_comb begin
        unused_ok = ^{clk, rst_n, wr_valid, wr_data, rd_ready} ^ (DEPTH_CHK[0]);
    end

endmodule
