// RX FIFO — 16-entry x 8-bit circular buffer with full/empty status
`timescale 1ns/1ps

module spi_rx_fifo #(
    parameter int DEPTH = 16,
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,

    // Write port (from SPI master)
    input  logic             wr_valid,
    input  logic [WIDTH-1:0] wr_data,
    output logic             wr_ready,

    // Read port (to APB / reg block)
    input  logic             rd_ready,
    output logic [WIDTH-1:0] rd_data,
    output logic             rd_valid,

    // Status
    output logic             full,
    output logic             empty
);

    // 5-bit pointers for DEPTH=16 (MSB distinguishes full vs empty)
    localparam int PTR_W  = $clog2(DEPTH) + 1;
    localparam int ADDR_W = $clog2(DEPTH);

    logic [WIDTH-1:0] mem [DEPTH];
    logic [PTR_W-1:0] wr_ptr;
    logic [PTR_W-1:0] rd_ptr;
    logic [ADDR_W-1:0] wr_idx;
    logic [ADDR_W-1:0] rd_idx;

    logic             wr_fire;
    logic             rd_fire;

    assign empty  = (wr_ptr == rd_ptr);
    // Full when write pointer has wrapped exactly DEPTH ahead of read pointer
    assign full   = (wr_ptr == (rd_ptr + PTR_W'(DEPTH)));

    assign wr_ready = ~full;
    assign rd_valid = ~empty;

    assign wr_fire = wr_valid & wr_ready;
    assign rd_fire = rd_ready & rd_valid;

    assign wr_idx = wr_ptr[ADDR_W-1:0];
    assign rd_idx = rd_ptr[ADDR_W-1:0];

    // First-word fall-through read data
    always_comb begin
        rd_data = mem[rd_idx];
    end

    integer i;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            for (i = 0; i < DEPTH; i = i + 1) begin
                mem[i] <= '0;
            end
        end else begin
            if (wr_fire) begin
                mem[wr_idx] <= wr_data;
                wr_ptr <= wr_ptr + PTR_W'(1);
            end
            if (rd_fire) begin
                rd_ptr <= rd_ptr + PTR_W'(1);
            end
        end
    end

endmodule
