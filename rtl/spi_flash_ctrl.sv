// Minimal synthesizable stub for toolchain baseline (lint / sim / synth).
// Full APB + SPI NOR controller functionality lands in subsequent stories.
module spi_flash_ctrl (
    input  logic        clk,
    input  logic        rst_n,
    // APB slave (stub ports for structural baseline)
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [31:0] paddr,
    input  logic [31:0] pwdata,
    output logic [31:0] prdata,
    output logic        pready,
    output logic        pslverr,
    // SPI master (single-lane)
    output logic        sclk,
    output logic        cs_n,
    output logic        mosi,
    input  logic        miso,
    // Interrupt
    output logic        irq
);

  // Absorb unused inputs so -Wall lint stays clean for this structural stub.
  logic unused_ok;
  assign unused_ok = clk ^ rst_n ^ psel ^ penable ^ pwrite
                     ^ ^paddr ^ ^pwdata ^ miso;

  // Tie-offs keep the module synthesizable until functional RTL fills in.
  // prdata carries unused_ok so inputs remain live under -Wall lint.
  assign prdata  = {31'h0, unused_ok};
  assign pready  = 1'b1;
  assign pslverr = 1'b0;
  assign sclk    = 1'b0;
  assign cs_n    = 1'b1;
  assign mosi    = 1'b0;
  assign irq     = 1'b0;

endmodule
