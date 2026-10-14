// Minimal placeholder RTL for Verilator lint baseline.
// Synthesizable stub only — full controller lives in spi_flash_ctrl.
module spi_flash_ctrl_stub (
    input             clk,
    input             rst_n,
    output reg [0:0]  done
);

  always @(posedge clk) begin
    if (!rst_n)
      done <= 1'b0;
    else
      done <= ~done;
  end

endmodule
