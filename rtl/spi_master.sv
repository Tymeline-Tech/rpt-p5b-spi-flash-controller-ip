// SPI Master Engine — transaction state machine (Modes 0/3)
// This step implements the SPI transaction FSM only. Shift registers,
// SCLK generation, and active FIFO handshakes are filled in by later tasks.
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

    // -------------------------------------------------------------------------
    // Supported SPI NOR flash opcodes
    // -------------------------------------------------------------------------
    localparam logic [7:0] CMD_READ      = 8'h03;
    localparam logic [7:0] CMD_FAST_READ = 8'h0B;
    localparam logic [7:0] CMD_PP        = 8'h02;
    localparam logic [7:0] CMD_SE        = 8'h20;
    localparam logic [7:0] CMD_RDSR      = 8'h05;
    localparam logic [7:0] CMD_WREN      = 8'h06;

    localparam logic [1:0] CMD_BYTES  = 2'd1;
    localparam logic [1:0] ADDR_BYTES = 2'd3;
    // Fast Read includes one dummy byte after the 24-bit address
    localparam logic [2:0] FAST_ADDR_BYTES = 3'd4;

    // -------------------------------------------------------------------------
    // 1) Transaction phase enum
    // -------------------------------------------------------------------------
    typedef enum logic [2:0] {
        IDLE       = 3'd0,
        CMD_PHASE  = 3'd1,
        ADDR_PHASE = 3'd2,
        DATA_TX    = 3'd3,
        DATA_RX    = 3'd4,
        DONE       = 3'd5
    } spi_state_e;

    // -------------------------------------------------------------------------
    // 3) Registered state + latched transaction context / byte counters
    // -------------------------------------------------------------------------
    spi_state_e state;
    spi_state_e next_state;

    logic [7:0]  cmd_r;
    logic        has_addr;
    logic        has_tx;
    logic        has_rx;
    logic [2:0]  addr_bytes_total; // 3, or 4 when Fast Read dummy is folded in
    logic [7:0]  rx_bytes_total;   // RDSR default 1; multi-byte reads use TX dummies

    // Bytes completed in the current phase (0-based count of finished bytes)
    logic [7:0]  byte_cnt;

    // Byte-complete pulse — driven by shift-register / clock engine (later task)
    // Held low here so the FSM structure is present without generating SCLK yet.
    logic        byte_done;

    logic        phase_cmd_done;
    logic        phase_addr_done;
    logic        phase_rx_done;
    logic        phase_tx_done;
    logic        enter_addr;
    logic        enter_tx;
    logic        enter_rx;

    assign byte_done = 1'b0;

    // Decode phase requirements from the latched command
    always_comb begin
        has_addr = 1'b0;
        has_tx   = 1'b0;
        has_rx   = 1'b0;
        unique case (cmd_r)
            CMD_READ: begin
                has_addr = 1'b1;
                has_rx   = 1'b1;
            end
            CMD_FAST_READ: begin
                has_addr = 1'b1;
                has_rx   = 1'b1;
            end
            CMD_PP: begin
                has_addr = 1'b1;
                has_tx   = 1'b1;
            end
            CMD_SE: begin
                has_addr = 1'b1;
            end
            CMD_RDSR: begin
                has_rx = 1'b1;
            end
            CMD_WREN: begin
                // command-only
            end
            default: begin
                // Unknown opcode: treat as command-only so the FSM still completes
            end
        endcase
    end

    assign addr_bytes_total = (cmd_r == CMD_FAST_READ) ? FAST_ADDR_BYTES
                                                       : {1'b0, ADDR_BYTES};

    // Phase completion helpers (byte counters + FIFO status)
    assign phase_cmd_done  = byte_done & (byte_cnt == {6'b0, CMD_BYTES} - 8'd1);
    assign phase_addr_done = byte_done & (byte_cnt == {5'b0, addr_bytes_total} - 8'd1);
    // TX: finish current byte and no further TX FIFO data
    assign phase_tx_done   = byte_done & tx_rd_empty;
    // RX: either hit the target count, or (for multi-byte reads) exhaust TX dummies
    assign phase_rx_done   = byte_done & (
                                 (byte_cnt == (rx_bytes_total - 8'd1)) |
                                 ((cmd_r == CMD_READ || cmd_r == CMD_FAST_READ) & tx_rd_empty)
                             );

    assign enter_addr = has_addr;
    assign enter_tx   = has_tx & ~tx_rd_empty;
    assign enter_rx   = has_rx & ~rx_wr_full;

    // -------------------------------------------------------------------------
    // 2) Next-state logic (FIFO flags + byte counters)
    // -------------------------------------------------------------------------
    always_comb begin
        next_state = state;
        unique case (state)
            IDLE: begin
                if (start) begin
                    next_state = CMD_PHASE;
                end
            end

            CMD_PHASE: begin
                if (phase_cmd_done) begin
                    if (enter_addr) begin
                        next_state = ADDR_PHASE;
                    end else if (enter_tx) begin
                        next_state = DATA_TX;
                    end else if (enter_rx) begin
                        next_state = DATA_RX;
                    end else begin
                        next_state = DONE;
                    end
                end
            end

            ADDR_PHASE: begin
                if (phase_addr_done) begin
                    if (enter_tx) begin
                        next_state = DATA_TX;
                    end else if (enter_rx) begin
                        next_state = DATA_RX;
                    end else begin
                        next_state = DONE;
                    end
                end
            end

            DATA_TX: begin
                // Complete after the last TX byte when the FIFO drains
                if (phase_tx_done) begin
                    next_state = DONE;
                end
            end

            DATA_RX: begin
                // Stall while RX FIFO is full; otherwise advance on phase_rx_done
                if (!rx_wr_full && phase_rx_done) begin
                    next_state = DONE;
                end
            end

            DONE: begin
                next_state = IDLE;
            end

            default: begin
                next_state = IDLE;
            end
        endcase
    end

    // Registered state + byte counter / command latch
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state          <= IDLE;
            cmd_r          <= 8'h00;
            byte_cnt       <= 8'h00;
            rx_bytes_total <= 8'h01;
        end else begin
            state <= next_state;

            // Latch command and RX length when leaving IDLE for a new transaction
            if ((state == IDLE) && start) begin
                cmd_r <= cmd_byte;
                // Default one RX byte (RDSR / single-beat reads). Multi-byte
                // reads can extend via TX dummy exhaustion in phase_rx_done;
                // FIFO integration may raise rx_bytes_total later.
                rx_bytes_total <= 8'h01;
                byte_cnt <= 8'h00;
            end else if (state != next_state) begin
                // Clear byte count on every phase transition
                byte_cnt <= 8'h00;
            end else if (byte_done) begin
                byte_cnt <= byte_cnt + 8'd1;
            end
        end
    end

    // Status from FSM
    assign busy = (state != IDLE);
    assign done = (state == DONE);

    // -------------------------------------------------------------------------
    // Pin / FIFO stubs — shift engine and FIFO integration land in later tasks
    // -------------------------------------------------------------------------
    assign cs_n_out  = 1'b1;
    assign sclk_out  = 1'b0;
    assign mosi_out  = 1'b0;

    assign rx_data    = 8'h00;
    assign rx_valid   = 1'b0;
    assign rx_wr_data = 8'h00;
    assign rx_wr_en   = 1'b0;
    assign tx_rd_en   = 1'b0;

    // Inputs reserved for clock gen / shifter (later tasks)
    logic unused_ok;
    always_comb begin
        unused_ok = ^{addr_word, clk_div, spi_mode, tx_rd_data, miso_in};
    end

endmodule
