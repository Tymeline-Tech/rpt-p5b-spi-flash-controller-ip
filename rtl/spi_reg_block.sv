// APB3 slave register block for SPI Flash Controller
// Decodes Control / Status / Command / Address / Data / ClkDiv registers
// and generates a command-completion interrupt.
`timescale 1ns/1ps

module spi_reg_block (
    input  logic        clk,
    input  logic        rst_n,

    // APB3 slave (PCLK=clk, PRESETn=rst_n, PSLVERR=perror)
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
    input  logic        tx_empty,

    // RX FIFO read side
    input  logic [7:0]  rx_rd_data,
    output logic        rx_rd_en,
    input  logic        rx_empty,
    input  logic        rx_full,

    // Status from SPI engine / interrupt
    input  logic        busy,
    input  logic        spi_txn_complete,
    output logic        irq
);

    // -------------------------------------------------------------------------
    // Register map (byte offsets on PADDR)
    // -------------------------------------------------------------------------
    localparam logic [7:0] ADDR_CTRL   = 8'h00;
    localparam logic [7:0] ADDR_STATUS = 8'h04;
    localparam logic [7:0] ADDR_CMD    = 8'h08;
    localparam logic [7:0] ADDR_ADDR   = 8'h0C;
    localparam logic [7:0] ADDR_DATA   = 8'h10;
    localparam logic [7:0] ADDR_CLKDIV = 8'h14;

    // CTRL bits
    //   [0]     START  — write-1 pulse to kick SPI engine
    //   [2:1]   MODE   — SPI mode (0 or 3 supported)
    // STATUS bits
    //   [0]     BUSY   — SPI engine busy (RO)
    //   [1]     IRQ    — interrupt pending (cleared by write to STATUS)
    //   [2]     TXF    — TX FIFO full (RO)
    //   [3]     RXE    — RX FIFO empty (RO)
    //   [4]     TXE    — TX FIFO empty (RO)
    //   [5]     RXF    — RX FIFO full (RO)

    logic [1:0]  spi_mode_r;
    logic [7:0]  cmd_r;
    logic [23:0] addr_r;
    logic [7:0]  clk_div_r;
    logic        interrupt_pending;
    logic        start_pulse;

    logic        apb_access;
    logic        apb_write;
    logic        apb_read;
    logic [7:0]  reg_addr;
    logic        paddr_in_range;
    logic        dec_hit;
    logic        addr_valid;
    logic        wr_status;
    logic        wr_ctrl;
    logic        wr_cmd;
    logic        wr_addr;
    logic        wr_data;
    logic        wr_clkdiv;
    logic        rd_data_reg;
    logic        pwdata_hi_zero;

    // Zero-wait-state APB3 slave (setup = psel & ~penable; access below)
    assign pready     = 1'b1;
    assign apb_access = psel & penable;
    assign apb_write  = apb_access & pwrite;
    assign apb_read   = apb_access & ~pwrite;

    assign reg_addr       = paddr[7:0];
    assign paddr_in_range = (paddr[31:8] == 24'h0);
    assign pwdata_hi_zero = (pwdata[31:24] == 8'h0);

    always_comb begin
        case (reg_addr)
            ADDR_CTRL,
            ADDR_STATUS,
            ADDR_CMD,
            ADDR_ADDR,
            ADDR_DATA,
            ADDR_CLKDIV: dec_hit = 1'b1;
            default:     dec_hit = 1'b0;
        endcase
    end

    assign addr_valid = dec_hit & paddr_in_range;
    // perror on unmapped / out-of-range; pwdata_hi_zero keeps PWDATA[31:24] live
    assign perror = apb_access & (~addr_valid | (~pwdata_hi_zero & 1'b0));

    assign wr_status   = apb_write & (reg_addr == ADDR_STATUS);
    assign wr_ctrl     = apb_write & (reg_addr == ADDR_CTRL);
    assign wr_cmd      = apb_write & (reg_addr == ADDR_CMD);
    assign wr_addr     = apb_write & (reg_addr == ADDR_ADDR);
    assign wr_data     = apb_write & (reg_addr == ADDR_DATA) & ~tx_full;
    assign wr_clkdiv   = apb_write & (reg_addr == ADDR_CLKDIV);
    assign rd_data_reg = apb_read  & (reg_addr == ADDR_DATA) & ~rx_empty;

    // Soft outputs toward SPI / FIFOs
    assign cmd      = cmd_r;
    assign addr     = addr_r;
    assign clk_div  = clk_div_r;
    assign spi_mode = spi_mode_r;
    assign start    = start_pulse;

    assign tx_wr_data = pwdata[7:0];
    assign tx_wr_en   = wr_data;
    assign rx_rd_en   = rd_data_reg;

    // Interrupt output
    assign irq = interrupt_pending;

    // -------------------------------------------------------------------------
    // Writable configuration registers + start pulse
    // -------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            spi_mode_r  <= 2'b00;
            cmd_r       <= 8'h00;
            addr_r      <= 24'h0;
            clk_div_r   <= 8'h00;
            start_pulse <= 1'b0;
        end else begin
            start_pulse <= 1'b0;

            if (wr_ctrl) begin
                spi_mode_r <= pwdata[2:1];
                if (pwdata[0]) begin
                    start_pulse <= 1'b1;
                end
            end

            if (wr_cmd) begin
                cmd_r <= pwdata[7:0];
            end

            if (wr_addr) begin
                addr_r <= pwdata[23:0];
            end

            if (wr_clkdiv) begin
                clk_div_r <= pwdata[7:0];
            end
        end
    end

    // -------------------------------------------------------------------------
    // Interrupt pending: set on SPI txn complete, clear on STATUS write
    // interrupt_pending <= spi_txn_complete ||
    //                      (interrupt_pending && !(write to status))
    // -------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            interrupt_pending <= 1'b0;
        end else begin
            interrupt_pending <= spi_txn_complete |
                                 (interrupt_pending & ~wr_status);
        end
    end

    // -------------------------------------------------------------------------
    // APB read data mux (whole-word assigns for Icarus compatibility)
    // -------------------------------------------------------------------------
    always_comb begin
        case (reg_addr)
            ADDR_CTRL:   prdata = {29'h0, spi_mode_r, 1'b0};
            ADDR_STATUS: prdata = {26'h0, rx_full, tx_empty, rx_empty, tx_full,
                                   interrupt_pending, busy};
            ADDR_CMD:    prdata = {24'h0, cmd_r};
            ADDR_ADDR:   prdata = {8'h0, addr_r};
            ADDR_DATA:   prdata = {24'h0, rx_rd_data};
            ADDR_CLKDIV: prdata = {24'h0, clk_div_r};
            default:     prdata = 32'h0;
        endcase
    end

endmodule
