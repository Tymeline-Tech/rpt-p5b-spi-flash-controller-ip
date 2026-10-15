// Smoke testbench for spi_flash_ctrl after FIFO + APB register implementation
// Checks idle SPI pins, APB ready, register R/W, interrupt clear, and TX FIFO.
`timescale 1ns/1ps

module tb_stub_smoke;
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
    logic [31:0] rdata;

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
        $dumpfile("artifacts/tb_stub_smoke.vcd");
        $dumpvars(0, tb_stub_smoke);
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

    task automatic apb_read(input logic [31:0] addr_i, output logic [31:0] data_o);
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
            data_o = prdata;
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
        rdata   = 32'h0;

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
        if (pready !== 1'b1) begin
            $error("Idle: pready != 1");
            errors = errors + 1;
        end

        // STATUS after reset: RX empty + TX empty set; not full; IRQ clear
        // bits: [3]=RXE, [4]=TXE → 0x18
        apb_read(32'h0000_0004, rdata);
        if (rdata !== 32'h0000_0018) begin
            $error("STATUS: expected 0x18 (rx_empty|tx_empty), got %h", rdata);
            errors = errors + 1;
        end

        // Program command / address / clkdiv and read back
        apb_write(32'h0000_0008, 32'h0000_0003); // CMD = READ
        apb_write(32'h0000_000C, 32'h00AB_CDEF); // ADDR
        apb_write(32'h0000_0014, 32'h0000_0004); // CLKDIV
        apb_write(32'h0000_0000, 32'h0000_0004); // CTRL: mode=2'b10 (no start)

        apb_read(32'h0000_0008, rdata);
        if (rdata !== 32'h0000_0003) begin
            $error("CMD readback mismatch: %h", rdata);
            errors = errors + 1;
        end
        apb_read(32'h0000_000C, rdata);
        if (rdata !== 32'h00AB_CDEF) begin
            $error("ADDR readback mismatch: %h", rdata);
            errors = errors + 1;
        end
        apb_read(32'h0000_0014, rdata);
        if (rdata !== 32'h0000_0004) begin
            $error("CLKDIV readback mismatch: %h", rdata);
            errors = errors + 1;
        end
        apb_read(32'h0000_0000, rdata);
        if (rdata !== 32'h0000_0004) begin
            $error("CTRL readback mismatch: %h", rdata);
            errors = errors + 1;
        end

        // Push one byte into TX FIFO via DATA
        apb_write(32'h0000_0010, 32'h0000_00A5);
        apb_read(32'h0000_0004, rdata);
        if ((rdata & 32'h0000_0004) !== 32'h0) begin
            $error("STATUS: TX should not be full after 1 write");
            errors = errors + 1;
        end

        // Write to STATUS clears IRQ (already clear — exercise path)
        apb_write(32'h0000_0004, 32'hFFFF_FFFF);
        if (irq !== 1'b0) begin
            $error("IRQ should remain clear after STATUS write");
            errors = errors + 1;
        end

        // Unmapped address should raise perror during access
        @(posedge clk);
        psel    = 1'b1;
        pwrite  = 1'b0;
        paddr   = 32'h0000_00FF;
        penable = 1'b0;
        @(posedge clk);
        penable = 1'b1;
        @(posedge clk);
        if (perror !== 1'b1) begin
            $error("Unmapped APB addr should assert perror");
            errors = errors + 1;
        end
        psel    = 1'b0;
        penable = 1'b0;

        repeat (4) @(posedge clk);

        if (errors == 0) begin
            $display("PASS: spi_flash_ctrl FIFO/APB smoke test");
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
