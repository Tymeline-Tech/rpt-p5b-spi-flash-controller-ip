// SPI Master Engine — Modes 0/3 with clock divider and shift registers
// FSM sequences CMD / ADDR / DATA_TX / DATA_RX; this module also generates
// SCLK, drives MOSI (MSB first), samples MISO, and manages CS_N.
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

    // Byte-complete pulse — from shift-register / clock engine
    logic        byte_done;

    logic        phase_cmd_done;
    logic        phase_addr_done;
    logic        phase_rx_done;
    logic        phase_tx_done;
    logic        enter_addr;
    logic        enter_tx;
    logic        enter_rx;

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
    // Clock divider, Mode 0/3 edge selects, MOSI/MISO shifters, CS_N
    // -------------------------------------------------------------------------
    logic [7:0]  clk_div_r;
    logic [1:0]  mode_r;
    logic [23:0] addr_r;

    logic        cpol;
    logic        cpha;

    // Mode 0 → 2'b00, Mode 3 → 2'b11 (CPOL=mode[1], CPHA=mode[0])
    assign cpol = mode_r[1];
    assign cpha = mode_r[0];

    logic        in_xfer;
    logic        bit_active;
    logic [7:0]  div_cnt;
    logic        sclk_internal;
    logic [2:0]  bit_cnt;
    logic [7:0]  mosi_shift;
    // Holds the first 7 sampled bits; the 8th arrives as miso_in on the last sample
    logic [6:0]  miso_partial;

    logic [7:0]  rx_data_r;
    logic        rx_valid_r;
    logic [7:0]  rx_wr_data_r;
    logic [7:0]  miso_byte;

    assign miso_byte = {miso_partial, miso_in};

    logic        at_half;
    logic        pos_edge_i;
    logic        neg_edge_i;
    logic        sample_ev;
    logic        shift_ev;
    logic        rx_block; // last RX sample pending but FIFO full (no comb loop)
    logic        more_bytes_needed;
    logic [7:0]  load_data;
    logic [7:0]  addr_byte_data;

    assign in_xfer = (state == CMD_PHASE) || (state == ADDR_PHASE) ||
                     (state == DATA_TX)   || (state == DATA_RX);

    // Assert CS_N through CMD/ADDR/DATA; release in IDLE and DONE
    assign cs_n_out = ~in_xfer;

    // SCLK idle level follows CPOL; while active, mirror or invert internal toggle
    assign sclk_out = in_xfer ? (cpol ? ~sclk_internal : sclk_internal) : cpol;

    // MOSI is MSB-first
    assign mosi_out = mosi_shift[7];

    assign rx_data    = rx_data_r;
    assign rx_valid   = rx_valid_r;
    assign rx_wr_data = rx_wr_data_r;

    // Half-period boundary (before optional RX FIFO stall inhibit)
    assign at_half    = bit_active & (div_cnt >= clk_div_r);
    assign pos_edge_i = at_half & ~sclk_internal;
    assign neg_edge_i = at_half &  sclk_internal;

    // Mode 0 (CPHA=0): sample on rising internal, shift on falling
    // Mode 3 (CPHA=1): shift on rising internal (leading on wire), sample on falling
    assign sample_ev = cpha ? neg_edge_i : pos_edge_i;
    assign shift_ev  = cpha ? pos_edge_i : neg_edge_i;

    // Hold clocks when the last MISO bit is ready but RX FIFO cannot accept it
    assign rx_block = (state == DATA_RX) & (bit_cnt == 3'd7) & sample_ev & rx_wr_full;

    // Avoid starting another byte once the phase completion condition is met
    always_comb begin
        more_bytes_needed = 1'b1;
        unique case (state)
            CMD_PHASE:  more_bytes_needed = (byte_cnt < {6'b0, CMD_BYTES});
            ADDR_PHASE: more_bytes_needed = (byte_cnt < {5'b0, addr_bytes_total});
            DATA_TX:    more_bytes_needed = ~tx_rd_empty;
            DATA_RX: begin
                if (cmd_r == CMD_READ || cmd_r == CMD_FAST_READ) begin
                    more_bytes_needed = ~tx_rd_empty;
                end else begin
                    more_bytes_needed = (byte_cnt < rx_bytes_total);
                end
            end
            default: more_bytes_needed = 1'b0;
        endcase
    end

    // Address bytes MSB first; 4th byte is Fast-Read dummy (0x00)
    always_comb begin
        unique case (byte_cnt[1:0])
            2'd0:    addr_byte_data = addr_r[23:16];
            2'd1:    addr_byte_data = addr_r[15:8];
            2'd2:    addr_byte_data = addr_r[7:0];
            default: addr_byte_data = 8'h00;
        endcase
    end

    always_comb begin
        unique case (state)
            CMD_PHASE:  load_data = cmd_r;
            ADDR_PHASE: load_data = addr_byte_data;
            DATA_TX:    load_data = tx_rd_data;
            DATA_RX:    load_data = 8'h00;
            default:    load_data = 8'h00;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_div_r     <= 8'h00;
            mode_r        <= 2'b00;
            addr_r        <= 24'h0;
            div_cnt       <= 8'h00;
            sclk_internal <= 1'b0;
            bit_active    <= 1'b0;
            bit_cnt       <= 3'd0;
            mosi_shift    <= 8'h00;
            miso_partial  <= 7'h00;
            byte_done     <= 1'b0;
            tx_rd_en      <= 1'b0;
            rx_wr_en      <= 1'b0;
            rx_wr_data_r  <= 8'h00;
            rx_data_r     <= 8'h00;
            rx_valid_r    <= 1'b0;
        end else begin
            byte_done  <= 1'b0;
            tx_rd_en   <= 1'b0;
            rx_wr_en   <= 1'b0;
            rx_valid_r <= 1'b0;

            // Latch divider / mode / address with the transaction
            if ((state == IDLE) && start) begin
                clk_div_r <= clk_div;
                mode_r    <= spi_mode;
                addr_r    <= addr_word;
            end

            if (!in_xfer) begin
                div_cnt       <= 8'h00;
                sclk_internal <= 1'b0;
                bit_active    <= 1'b0;
                bit_cnt       <= 3'd0;
            end else if (!bit_active) begin
                div_cnt       <= 8'h00;
                sclk_internal <= 1'b0;
                if (more_bytes_needed) begin
                    // Load MOSI shift register (MSB first) before the first edge
                    mosi_shift <= load_data;
                    bit_cnt    <= 3'd0;
                    bit_active <= 1'b1;

                    // Pop TX FIFO when sourcing a DATA_TX byte
                    if (state == DATA_TX && !tx_rd_empty) begin
                        tx_rd_en <= 1'b1;
                    end
                    // Multi-byte reads: one TX dummy per RX beat (length control)
                    if (state == DATA_RX &&
                        (cmd_r == CMD_READ || cmd_r == CMD_FAST_READ) &&
                        !tx_rd_empty) begin
                        tx_rd_en <= 1'b1;
                    end
                end
            end else begin
                // Counter-based clock divider → sclk_internal toggles
                // Freeze while RX FIFO blocks the final sample of a byte
                if (!rx_block) begin
                    if (div_cnt >= clk_div_r) begin
                        div_cnt       <= 8'h00;
                        sclk_internal <= ~sclk_internal;
                    end else begin
                        div_cnt <= div_cnt + 8'd1;
                    end
                end

                // Shift / sample on the appropriate internal edges
                if (at_half && !rx_block) begin
                    if (sample_ev) begin
                        if (bit_cnt == 3'd7) begin
                            byte_done  <= 1'b1;
                            bit_active <= 1'b0;
                            miso_partial <= 7'h00;
                            if (state == DATA_RX) begin
                                rx_wr_data_r <= miso_byte;
                                rx_wr_en     <= 1'b1;
                                rx_data_r    <= miso_byte;
                                rx_valid_r   <= 1'b1;
                            end
                        end else begin
                            miso_partial <= miso_byte[6:0];
                            bit_cnt <= bit_cnt + 3'd1;
                        end
                    end

                    // CPHA=1: keep preloaded MSB through the first leading edge
                    if (shift_ev) begin
                        if (!cpha || (bit_cnt != 3'd0)) begin
                            mosi_shift <= {mosi_shift[6:0], 1'b0};
                        end
                    end
                end
            end
        end
    end

endmodule
