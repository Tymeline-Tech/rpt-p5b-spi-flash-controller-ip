// Icarus/cocotb wrapper: dumps waves for failure triage.
`timescale 1ns/1ps

module tb_spi_flash_ctrl;
  logic        clk;
  logic        rst_n;
  logic        psel;
  logic        penable;
  logic        pwrite;
  logic [31:0] paddr;
  logic [31:0] pwdata;
  logic [31:0] prdata;
  logic        pready;
  logic        pslverr;
  logic        sclk;
  logic        cs_n;
  logic        mosi;
  logic        miso;
  logic        irq;

  initial begin
    $dumpfile("spi_flash_ctrl.vcd");
    $dumpvars(0, tb_spi_flash_ctrl);
  end

  spi_flash_ctrl dut (
      .clk    (clk),
      .rst_n  (rst_n),
      .psel   (psel),
      .penable(penable),
      .pwrite (pwrite),
      .paddr  (paddr),
      .pwdata (pwdata),
      .prdata (prdata),
      .pready (pready),
      .pslverr(pslverr),
      .sclk   (sclk),
      .cs_n   (cs_n),
      .mosi   (mosi),
      .miso   (miso),
      .irq    (irq)
  );
endmodule
