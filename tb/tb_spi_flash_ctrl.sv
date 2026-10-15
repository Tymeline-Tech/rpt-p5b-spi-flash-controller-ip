// Stub-level smoke testbench for spi_flash_ctrl
// Checks idle SPI pins, APB immediate ready, and FIFO empty defaults.
`timescale 1ns/1ps

module tb_spi_flash_ctrl;
    logic        clk;
    logic        rst_n;

    logic        psel;
    logic        penable;
    logic        pwrite;
    logic [31:0] paddr;
    logic [31:0] pwdata;
    logic        pready;
    logic [31:0] prdata;
    logic        perror;

    logic        irq;
    logic        sclk;
    logic        mosi;
    logic        miso;
    logic        cs_n;

    integer      errors;

    spi_flash_ctrl dut (
        .clk     (clk),
        .rst_n   (rst_n),
        .psel    (psel),
        .penable (penable),
        .pwrite  (pwrite),
        .paddr   (paddr),
        .pwdata  (pwdata),
        .pready  (pready),
        .prdata  (prdata),
        .perror  (perror),
        .irq     (irq),
        .sclk    (sclk),
        .mosi    (mosi),
        .miso    (miso),
        .cs_n    (cs_n)
    );

    // 100 MHz clock
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    // Waveform dump for failure triage
    initial begin
        $dumpfile("artifacts/tb_spi_flash_ctrl.vcd");
        $dumpvars(0, tb_spi_flash_ctrl);
    end

    // Assertions (enabled under Verilator --assert)
    always_ff @(posedge clk) begin
        if (rst_n) begin
            assert (cs_n === 1'b1)
                else $error("cs_n must remain inactive (high) in stub");
            assert (sclk === 1'b0)
                else $error("sclk must remain low in stub");
            assert (pready === 1'b1)
                else $error("pready must be tied high in stub");
            assert (perror === 1'b0)
                else $error("perror must be tied low in stub");
        end
    end

    task automatic apb_write(input logic [31:0] addr_i, input logic [31:0] data_i);
        begin
            @(posedge clk);
            psel    = 1'b1;
            pwrite  = 1'b1;
            paddr   = addr_i;
            pwdata  = data_i;
            penable = 1'b0;
            @(posedge clk);
            penable = 1'b1;
            @(posedge clk);
            if (pready !== 1'b1) begin
                $error("APB write: pready not high");
                errors = errors + 1;
            end
            psel    = 1'b0;
            penable = 1'b0;
            pwrite  = 1'b0;
        end
    endtask

    task automatic apb_read(input logic [31:0] addr_i);
        begin
            @(posedge clk);
            psel    = 1'b1;
            pwrite  = 1'b0;
            paddr   = addr_i;
            pwdata  = 32'h0;
            penable = 1'b0;
            @(posedge clk);
            penable = 1'b1;
            @(posedge clk);
            if (pready !== 1'b1) begin
                $error("APB read: pready not high");
                errors = errors + 1;
            end
            if (prdata !== 32'h0) begin
                $error("APB read: stub prdata expected 0, got %h", prdata);
                errors = errors + 1;
            end
            psel    = 1'b0;
            penable = 1'b0;
        end
    endtask

    initial begin
        errors  = 0;
        rst_n   = 1'b0;
        psel    = 1'b0;
        penable = 1'b0;
        pwrite  = 1'b0;
        paddr   = 32'h0;
        pwdata  = 32'h0;
        miso    = 1'b0;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // Idle SPI bus checks
        if (cs_n !== 1'b1) begin
            $error("Idle: cs_n != 1");
            errors = errors + 1;
        end
        if (sclk !== 1'b0) begin
            $error("Idle: sclk != 0");
            errors = errors + 1;
        end
        if (mosi !== 1'b0) begin
            $error("Idle: mosi != 0");
            errors = errors + 1;
        end
        if (irq !== 1'b0) begin
            $error("Idle: irq != 0");
            errors = errors + 1;
        end

        // APB stub transactions
        apb_write(32'h0000_0000, 32'hDEAD_BEEF);
        apb_read (32'h0000_0004);
        apb_write(32'h0000_0008, 32'h0000_0003); // READ cmd placeholder
        apb_read (32'h0000_000C);

        repeat (4) @(posedge clk);

        if (errors == 0) begin
            $display("PASS: spi_flash_ctrl stub smoke test");
            $finish;
        end else begin
            $display("FAIL: %0d error(s)", errors);
            $fatal(1);
        end
    end

    // Timeout watchdog
    initial begin
        #10000;
        $error("Timeout");
        $fatal(1);
    end

endmodule
