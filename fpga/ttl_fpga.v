// Part models for the FPGA twin (docs/notes/fpga_twin_gen.py).
//
// Synthesizable, one module per part type. Ports follow the DIP pin
// numbers: iN = the resolved level on pin N (input or bidirectional),
// oN = what the part drives on pin N, eN = whether it drives (tri-state,
// bidirectional, open-collector pins only; a totem-pole output always
// drives). The generator resolves every net from these.
//
// Everything runs on one system clock `clk` (48 MHz on the Versa). The
// TTL's timing is not modelled; its logic is:
//   - gates, decoders, muxes, the ALU: combinational, zero delay
//   - edge-triggered parts ('74 '163 '169 '193 '273): act on a rising
//     edge of their clock pin, seen as low on the previous tick and high
//     on this one, with the data as it stands on this tick
//   - transparent latches ('373), '245 data, memory reads: update once per
//     tick. That one tick is what breaks the bus loops a '245 pair and a
//     transparent latch would otherwise close.
//   - asynchronous clears/presets/loads: level-sensitive, applied each tick
//   - nothing changes state until `live` (the top's power-up window); each
//     stateful part powers up at INIT, which the generator draws from a
//     seed so the machine does not start from all zeros.
// Where the datasheet leaves an output undefined (the '382's Cn+4 and OVR
// in logic modes, never measured on DINO), the model drives 0; the oracle
// refuses to depend on them, and so must every program.

// ---- gates -------------------------------------------------------------------

module f_00 (input wire i1, i2, i4, i5, i9, i10, i12, i13,
             output wire o3, o6, o8, o11);
  assign o3 = ~(i1 & i2);   assign o6 = ~(i4 & i5);
  assign o8 = ~(i9 & i10);  assign o11 = ~(i12 & i13);
endmodule

module f_08 (input wire i1, i2, i4, i5, i9, i10, i12, i13,
             output wire o3, o6, o8, o11);
  assign o3 = i1 & i2;   assign o6 = i4 & i5;
  assign o8 = i9 & i10;  assign o11 = i12 & i13;
endmodule

module f_32 (input wire i1, i2, i4, i5, i9, i10, i12, i13,
             output wire o3, o6, o8, o11);
  assign o3 = i1 | i2;   assign o6 = i4 | i5;
  assign o8 = i9 | i10;  assign o11 = i12 | i13;
endmodule

module f_02 (input wire i2, i3, i5, i6, i8, i9, i11, i12,
             output wire o1, o4, o10, o13);
  assign o1 = ~(i2 | i3);   assign o4 = ~(i5 | i6);
  assign o10 = ~(i8 | i9);  assign o13 = ~(i11 | i12);
endmodule

// '04, and the '14 (a Schmitt input is a logic inverter here)
module f_04 (input wire i1, i3, i5, i9, i11, i13,
             output wire o2, o4, o6, o8, o10, o12);
  assign o2 = ~i1;  assign o4 = ~i3;   assign o6 = ~i5;
  assign o8 = ~i9;  assign o10 = ~i11; assign o12 = ~i13;
endmodule

// '06 open-collector inverter: pulls low when its input is high, else off
module f_06 (input wire i1, i3, i5, i9, i11, i13,
             output wire o2, o4, o6, o8, o10, o12,
             output wire e2, e4, e6, e8, e10, e12);
  assign {o2, o4, o6, o8, o10, o12} = 6'b0;
  assign e2 = i1;  assign e4 = i3;   assign e6 = i5;
  assign e8 = i9;  assign e10 = i11; assign e12 = i13;
endmodule

// ---- '74 dual D flip-flop: async ~R ~S (both low: Q = ~Q = 1) ----------------

module f_74_half #(parameter INIT = 1'b0)
                 (input wire clk, live, nr, d, c, ns, output wire q, nq);
  reg s = INIT, c_q = 1'b1;
  always @(posedge clk) begin
    c_q <= c;
    if (live) begin
      if (!nr) s <= 1'b0;
      else if (!ns) s <= 1'b1;
      else if (c && !c_q) s <= d;
    end
  end
  wire both = ~nr & ~ns;
  assign q = both | s;
  assign nq = both | ~s;
endmodule

module f_74 #(parameter [1:0] INIT = 2'b00)
            (input wire clk, live, i1, i2, i3, i4, i10, i11, i12, i13,
             output wire o5, o6, o8, o9);
  f_74_half #(INIT[0]) a (clk, live, i1, i2, i3, i4, o5, o6);
  f_74_half #(INIT[1]) b (clk, live, i13, i12, i11, i10, o9, o8);
endmodule

// ---- '138: E1, E2 active low, E3 active high --------------------------------

module f_138 (input wire i1, i2, i3, i4, i5, i6,
              output wire o7, o9, o10, o11, o12, o13, o14, o15);
  wire en = ~i4 & ~i5 & i6;
  wire [2:0] a = {i3, i2, i1};
  assign o15 = ~(en & (a == 3'd0)); assign o14 = ~(en & (a == 3'd1));
  assign o13 = ~(en & (a == 3'd2)); assign o12 = ~(en & (a == 3'd3));
  assign o11 = ~(en & (a == 3'd4)); assign o10 = ~(en & (a == 3'd5));
  assign o9  = ~(en & (a == 3'd6)); assign o7  = ~(en & (a == 3'd7));
endmodule

// ---- '157 quad 2:1 mux, E active low (E high: outputs low) ------------------

module f_157 (input wire i1, i2, i3, i5, i6, i10, i11, i13, i14, i15,
              output wire o4, o7, o9, o12);
  assign o4  = ~i15 & (i1 ? i3 : i2);
  assign o7  = ~i15 & (i1 ? i6 : i5);
  assign o9  = ~i15 & (i1 ? i10 : i11);
  assign o12 = ~i15 & (i1 ? i13 : i14);
endmodule

// ---- '163 synchronous counter, synchronous ~MR -------------------------------

module f_163 #(parameter [3:0] INIT = 4'd0)
             (input wire clk, live, i1, i2, i3, i4, i5, i6, i7, i9, i10,
              output wire o11, o12, o13, o14, o15);
  reg [3:0] q = INIT;
  reg c_q = 1'b1;
  always @(posedge clk) begin
    c_q <= i2;
    if (live && i2 && !c_q) begin
      if (!i1) q <= 4'd0;
      else if (!i9) q <= {i6, i5, i4, i3};
      else if (i7 & i10) q <= q + 4'd1;
    end
  end
  assign {o11, o12, o13, o14} = q;
  assign o15 = (q == 4'hF) & i10;
endmodule

// ---- '169 synchronous up/down counter ----------------------------------------

module f_169 #(parameter [3:0] INIT = 4'd0)
             (input wire clk, live, i1, i2, i3, i4, i5, i6, i7, i9, i10,
              output wire o11, o12, o13, o14, o15);
  reg [3:0] q = INIT;
  reg c_q = 1'b1;
  always @(posedge clk) begin
    c_q <= i2;
    if (live && i2 && !c_q) begin
      if (!i9) q <= {i6, i5, i4, i3};
      else if (!(i7 | i10)) q <= i1 ? q + 4'd1 : q - 4'd1;
    end
  end
  assign {o11, o12, o13, o14} = q;
  assign o15 = ~(~i10 & (i1 ? (q == 4'hF) : (q == 4'h0)));
endmodule

// ---- '193 up/down counter: async CLR (high), async ~LOAD, two clocks ---------

module f_193 #(parameter [3:0] INIT = 4'd0)
             (input wire clk, live, i1, i4, i5, i9, i10, i11, i14, i15,
              output wire o2, o3, o6, o7, o12, o13);
  reg [3:0] q = INIT;
  reg up_q = 1'b1, dn_q = 1'b1;
  wire [3:0] d = {i9, i10, i1, i15};
  always @(posedge clk) begin
    up_q <= i5;
    dn_q <= i4;
    if (live) begin
      if (i14) q <= 4'd0;
      else if (!i11) q <= d;
      else if (i5 && !up_q && i4) q <= q + 4'd1;
      else if (i4 && !dn_q && i5) q <= q - 4'd1;
    end
  end
  assign {o7, o6, o2, o3} = q;
  assign o12 = ~((q == 4'hF) & ~i5);
  assign o13 = ~((q == 4'h0) & ~i4);
endmodule

// ---- '244 octal buffer, two active-low enables -------------------------------

module f_244 (input wire i1, i2, i4, i6, i8, i11, i13, i15, i17, i19,
              output wire o3, o5, o7, o9, o12, o14, o16, o18,
              output wire e3, e5, e7, e9, e12, e14, e16, e18);
  assign {o18, o16, o14, o12} = {i2, i4, i6, i8};
  assign {o9, o7, o5, o3} = {i11, i13, i15, i17};
  assign {e18, e16, e14, e12} = {4{~i1}};
  assign {e9, e7, e5, e3} = {4{~i19}};
endmodule

// ---- '245 octal transceiver: DIR high = A to B, CE active low ----------------
// The data a side passes over is registered (one tick); the enables are not.

module f_245 (input wire clk, i1, i19,
              input wire i2, i3, i4, i5, i6, i7, i8, i9,
              input wire i11, i12, i13, i14, i15, i16, i17, i18,
              output wire o2, o3, o4, o5, o6, o7, o8, o9,
              output wire o11, o12, o13, o14, o15, o16, o17, o18,
              output wire e2, e3, e4, e5, e6, e7, e8, e9,
              output wire e11, e12, e13, e14, e15, e16, e17, e18);
  reg [7:0] to_b = 8'hFF, to_a = 8'hFF;
  always @(posedge clk) begin
    to_b <= {i9, i8, i7, i6, i5, i4, i3, i2};
    to_a <= {i11, i12, i13, i14, i15, i16, i17, i18};
  end
  wire a2b = ~i19 & i1, b2a = ~i19 & ~i1;
  assign {o11, o12, o13, o14, o15, o16, o17, o18} = to_b;
  assign {o9, o8, o7, o6, o5, o4, o3, o2} = to_a;
  assign {e11, e12, e13, e14, e15, e16, e17, e18} = {8{a2b}};
  assign {e9, e8, e7, e6, e5, e4, e3, e2} = {8{b2a}};
endmodule

// ---- '273 octal D flip-flop, async ~MR -----------------------------------------

module f_273 #(parameter [7:0] INIT = 8'd0)
             (input wire clk, live, i1, i3, i4, i7, i8, i11, i13, i14, i17, i18,
              output wire o2, o5, o6, o9, o12, o15, o16, o19);
  reg [7:0] q = INIT;
  reg c_q = 1'b1;
  always @(posedge clk) begin
    c_q <= i11;
    if (live) begin
      if (!i1) q <= 8'd0;
      else if (i11 && !c_q) q <= {i18, i17, i14, i13, i8, i7, i4, i3};
    end
  end
  assign {o19, o16, o15, o12, o9, o6, o5, o2} = q;
endmodule

// ---- '373 octal transparent latch, ~OE ---------------------------------------

module f_373 #(parameter [7:0] INIT = 8'd0)
             (input wire clk, live, i1, i3, i4, i7, i8, i11, i13, i14, i17, i18,
              output wire o2, o5, o6, o9, o12, o15, o16, o19,
              output wire e2, e5, e6, e9, e12, e15, e16, e19);
  reg [7:0] q = INIT;
  always @(posedge clk)
    if (live && i11) q <= {i18, i17, i14, i13, i8, i7, i4, i3};
  assign {o19, o16, o15, o12, o9, o6, o5, o2} = q;
  assign {e19, e16, e15, e12, e9, e6, e5, e2} = {8{~i1}};
endmodule

// ---- 74F382 4-bit ALU ------------------------------------------------------------

module f_382 (input wire i1, i2, i3, i4, i5, i6, i7, i15, i16, i17, i18, i19,
              output wire o8, o9, o11, o12, o13, o14);
  wire [2:0] s = {i7, i6, i5};
  wire [3:0] a = {i17, i19, i1, i3};
  wire [3:0] b = {i16, i18, i2, i4};
  wire [3:0] x = (s == 3'd1) ? b : a;
  wire [3:0] y = (s == 3'd1) ? ~a : (s == 3'd2) ? ~b : b;
  wire [4:0] sum = x + y + i15;
  wire [3:0] lo = x[2:0] + y[2:0] + i15;
  reg [3:0] f;
  reg c4, ovr;
  always @* begin
    case (s)
      3'd0: begin f = 4'h0; c4 = 1'b1; ovr = 1'b1; end
      3'd1, 3'd2, 3'd3: begin f = sum[3:0]; c4 = sum[4]; ovr = lo[3] ^ sum[4]; end
      3'd4: begin f = a ^ b; c4 = 1'b0; ovr = 1'b0; end
      3'd5: begin f = a | b; c4 = 1'b0; ovr = 1'b0; end
      3'd6: begin f = a & b; c4 = 1'b0; ovr = 1'b0; end
      default: begin f = 4'hF; c4 = 1'b0; ovr = 1'b0; end
    endcase
  end
  assign {o12, o11, o9, o8} = f;
  assign o14 = c4;
  assign o13 = ovr;
endmodule

// ---- memories ------------------------------------------------------------------
// 28-pin JEDEC byte-wide pinout: A14 p1, A13 p26, A12 p2, A11 p23, A10 p21,
// A9 p24, A8 p25, A7-A0 p3-p10; data p11-13, p15-19; ~CE p20 ~OE p22 ~WE p27.
// The array is read once per tick (block RAM); the output enable is not
// registered. FILE is the image burned into the part.

module f_eeprom #(parameter ABITS = 15, parameter FILE = "", parameter TAG = "")
                (input wire clk, i1, i2, i3, i4, i5, i6, i7, i8, i9, i10,
                 input wire i20, i21, i22, i23, i24, i25, i26, i27,
                 output wire o11, o12, o13, o15, o16, o17, o18, o19,
                 output wire e11, e12, e13, e15, e16, e17, e18, e19);
  wire [14:0] af = {i1, i26, i2, i23, i21, i24, i25, i3, i4, i5, i6, i7, i8, i9, i10};
  reg [7:0] mem [0:(1 << ABITS) - 1];
`ifdef SIM
  reg [1023:0] path;
  initial if ($value$plusargs({TAG, "=%s"}, path)) $readmemh(path, mem);
          else if (FILE != "") $readmemh(FILE, mem);
`else
  initial if (FILE != "") $readmemh(FILE, mem);
`endif
  reg [7:0] d = 8'hFF;
  always @(posedge clk) d <= mem[af[ABITS-1:0]];
  assign {o19, o18, o17, o16, o15, o13, o12, o11} = d;
  assign {e19, e18, e17, e16, e15, e13, e12, e11} = {8{~i20 & ~i22}};
endmodule

// SRAM: a write is ~CE low and ~WE low; the cell follows the data bus for
// as long as both are, so it holds the last byte on the bus when either
// rises. Uninitialised cells read 0 (the twin cannot hold x).
module f_sram #(parameter TAG = "")
              (input wire clk, i1, i2, i3, i4, i5, i6, i7, i8, i9, i10,
               input wire i20, i21, i22, i23, i24, i25, i26, i27,
               input wire i11, i12, i13, i15, i16, i17, i18, i19,
               output wire o11, o12, o13, o15, o16, o17, o18, o19,
               output wire e11, e12, e13, e15, e16, e17, e18, e19);
  wire [14:0] a = {i1, i26, i2, i23, i21, i24, i25, i3, i4, i5, i6, i7, i8, i9, i10};
  wire [7:0] dq = {i19, i18, i17, i16, i15, i13, i12, i11};
  reg [7:0] mem [0:32767];
`ifdef SIM
  reg [1023:0] path;
  initial if ($value$plusargs({TAG, "=%s"}, path)) $readmemh(path, mem);
`endif
  reg [7:0] d = 8'hFF;
  always @(posedge clk) begin
    if (~i20 & ~i27) mem[a] <= dq;
    d <= mem[a];
  end
  assign {o19, o18, o17, o16, o15, o13, o12, o11} = d;
  assign {e19, e18, e17, e16, e15, e13, e12, e11} = {8{~i20 & ~i22 & i27}};
endmodule

// ---- oscillator cans -------------------------------------------------------------

// The mainboard's 4.096 MHz can (Y1): toggles every HALF ticks once live.
// Its rate sets the machine's speed; it is chosen so a half CLK period is
// many ticks longer than the deepest registered path settles (fpga_twin_gen.py).
module f_osc14 #(parameter integer HALF = 16)
               (input wire clk, live, i1, output wire o8);
  reg o = 1'b0;
  reg [15:0] n = 16'd0;
  always @(posedge clk)
    if (live && i1) begin
      if (n == HALF - 1) begin n <= 16'd0; o <= ~o; end
      else n <= n + 16'd1;
    end
  assign o8 = o;
endmodule

// The serial card's 3.6864 MHz can: its real rate, from the system clock by
// a phase accumulator, so the UART's baud rate is right on the wire.
module f_osc8 #(parameter integer F_HZ = 3686400, parameter integer CLK_HZ = 48000000)
              (input wire clk, live, i1, output wire o5);
  reg o = 1'b0;
  reg [31:0] acc = 32'd0;
  always @(posedge clk)
    if (live && i1) begin
      if (acc + 2 * F_HZ >= CLK_HZ) begin acc <= acc + 2 * F_HZ - CLK_HZ; o <= ~o; end
      else acc <= acc + 2 * F_HZ;
    end
  assign o5 = o;
endmodule

// ---- PC16550D UART -----------------------------------------------------------------
// What DINO's software uses (asm/ser*.asm, monitor, imon): RBR/THR, IER, IIR,
// FCR (FIFO enable/clear, RX trigger level), LCR (DLAB; 8N1 framing),
// MCR (loopback; DTR RTS OUT1 OUT2), LSR (DR OE FE THRE TEMT), MSR, SCR,
// DLL/DLM. Interrupts: line status, RX data (trigger level), RX timeout,
// THR empty. ~ADS is tied low on the card, so the address is transparent.
// The baud clock is XIN / divisor; the receiver uses it too (the card ties
// ~BAUDOUT to RCLK). Not modelled: parity, word lengths other than 8, break,
// modem-status deltas.

module f_16550 (input wire clk, live,
                input wire i1, i2, i3, i4, i5, i6, i7, i8,
                input wire i9, i10, i12, i13, i14, i16, i18, i19, i21, i22, i25,
                input wire i26, i27, i28, i35, i36, i37, i38, i39,
                output wire o1, o2, o3, o4, o5, o6, o7, o8,
                output wire e1, e2, e3, e4, e5, e6, e7, e8,
                output wire o11, o15, o17, o23, o24, o29, o30, o31, o32, o33, o34);
  wire mr = i35;
  wire sel = i12 & i13 & ~i14;
  wire rd = sel & (~i21 | i22);
  wire wr = sel & (~i18 | i19);
  wire [2:0] adr = {i26, i27, i28};
  wire [7:0] din = {i8, i7, i6, i5, i4, i3, i2, i1};

  reg [7:0] lcr = 0, scr = 0, dll = 0, dlm = 0;
  reg [3:0] ier = 0;
  reg [4:0] mcr = 0;
  reg fifo_en = 0;
  reg [1:0] trig = 0;
  reg oe = 0, fe = 0, thre_int = 0;
  wire dlab = lcr[7];

  // FIFOs, 16 deep (depth 1 behaviour is the FIFO with FCR0 = 0)
  reg [7:0] rxf [0:15];
  reg [7:0] txf [0:15];
  reg [3:0] rx_rd = 0, rx_wr = 0, tx_rd = 0, tx_wr = 0;
  reg [4:0] rx_n = 0, tx_n = 0;

  // baud: one tick per divisor XIN rising edges (16x the bit rate)
  reg x_q = 0;
  reg [15:0] bdiv = 0;
  reg b16 = 0;
  wire [15:0] divisor = {dlm, dll};

  // transmitter
  reg [3:0] t_ph = 0;     // 16 ticks per bit
  reg [3:0] t_bit = 0;    // 0 idle, 1 start, 2..9 data, 10 stop
  reg [7:0] t_sh = 0;
  reg t_line = 1;

  // receiver
  wire r_in_raw = mcr[4] ? t_line : i10;
  reg r_in = 1;
  reg [3:0] r_ph = 0;
  reg [3:0] r_bit = 0;    // 0 idle, 1 start, 2..9 data, 10 stop
  reg [7:0] r_sh = 0;
  reg [9:0] r_idle = 0;   // b16 ticks since the FIFO last moved
  wire timeout = fifo_en && rx_n != 0 && r_idle >= 10'd640;

  // bus cycle tracking: act at the END of a read or write
  reg rd_q = 0, wr_q = 0;
  reg [2:0] adr_q = 0;
  reg [7:0] wd_q = 0;

  wire [4:0] lvl = trig == 2'd0 ? 5'd1 : trig == 2'd1 ? 5'd4 : trig == 2'd2 ? 5'd8 : 5'd14;
  wire rda = fifo_en ? rx_n >= lvl : rx_n != 0;
  wire thre = tx_n == 0;
  wire temt = thre && t_bit == 0;
  reg [3:0] iid;
  always @* begin
    if (ier[2] && (oe || fe)) iid = 4'h6;
    else if (ier[0] && rda) iid = 4'h4;
    else if (ier[0] && timeout) iid = 4'hC;
    else if (ier[1] && thre_int) iid = 4'h2;
    else iid = 4'h1;
  end
  wire [7:0] iir = {{2{fifo_en}}, 2'b00, iid};
  wire [7:0] lsr = {1'b0, temt, thre, 1'b0, fe, 1'b0, oe, rx_n != 0};
  wire [7:0] msr = mcr[4] ? {mcr[3], mcr[2], mcr[0], mcr[1], 4'b0} : 8'h00;

  reg [7:0] dout;
  always @* case (adr)
    3'd0: dout = dlab ? dll : rxf[rx_rd];
    3'd1: dout = dlab ? dlm : {4'b0, ier};
    3'd2: dout = iir;
    3'd3: dout = lcr;
    3'd4: dout = {3'b0, mcr};
    3'd5: dout = lsr;
    3'd6: dout = msr;
    default: dout = scr;
  endcase

  always @(posedge clk) begin
    rd_q <= rd;
    wr_q <= wr;
    if (rd) adr_q <= adr;
    if (wr) begin adr_q <= adr; wd_q <= din; end
    x_q <= i16;
    r_in <= r_in_raw;
    b16 <= 1'b0;
    if (!live) ;
    else if (mr) begin
      lcr <= 0; ier <= 0; mcr <= 0; fifo_en <= 0; trig <= 0;
      oe <= 0; fe <= 0; thre_int <= 0;
      rx_rd <= 0; rx_wr <= 0; rx_n <= 0; tx_rd <= 0; tx_wr <= 0; tx_n <= 0;
      t_bit <= 0; t_line <= 1; r_bit <= 0; bdiv <= 0; r_idle <= 0;
    end else begin
      // baud
      if (i16 && !x_q && divisor != 0) begin
        if (bdiv + 16'd1 >= divisor) begin bdiv <= 0; b16 <= 1'b1; end
        else bdiv <= bdiv + 16'd1;
      end
      // end of a write
      if (wr_q && !wr) case (adr_q)
        3'd0: if (dlab) dll <= wd_q;
              else if (tx_n != 16) begin
                txf[tx_wr] <= wd_q; tx_wr <= tx_wr + 1; tx_n <= tx_n + 1; thre_int <= 0;
              end
        3'd1: if (dlab) dlm <= wd_q;
              else begin ier <= wd_q[3:0]; if (wd_q[1] && !ier[1] && tx_n == 0) thre_int <= 1; end
        3'd2: begin
                if (wd_q[0] != fifo_en || wd_q[1]) begin rx_rd <= 0; rx_wr <= 0; rx_n <= 0; end
                if (wd_q[0] != fifo_en || wd_q[2]) begin tx_rd <= 0; tx_wr <= 0; tx_n <= 0; end
                fifo_en <= wd_q[0];
                trig <= wd_q[7:6];
              end
        3'd3: lcr <= wd_q;
        3'd4: mcr <= wd_q[4:0];
        3'd7: scr <= wd_q;
        default: ;
      endcase
      // end of a read: the side effects
      if (rd_q && !rd) case (adr_q)
        3'd0: if (!dlab && rx_n != 0) begin rx_rd <= rx_rd + 1; rx_n <= rx_n - 1; r_idle <= 0; end
        3'd2: if (iid == 4'h2) thre_int <= 0;
        3'd5: begin oe <= 0; fe <= 0; end
        default: ;
      endcase
      // transmitter
      if (b16) begin
        if (t_bit == 0) begin
          if (tx_n != 0 && !(wr_q && !wr && adr_q == 3'd0 && !dlab)) begin
            t_sh <= txf[tx_rd]; tx_rd <= tx_rd + 1; tx_n <= tx_n - 1;
            if (tx_n == 1) thre_int <= 1;
            t_bit <= 1; t_ph <= 0; t_line <= 0;
          end
        end else if (t_ph == 15) begin
          t_ph <= 0;
          if (t_bit == 10) begin t_bit <= 0; t_line <= 1; end
          else begin
            t_bit <= t_bit + 1;
            if (t_bit <= 8) begin t_line <= t_sh[0]; t_sh <= t_sh >> 1; end
            else t_line <= 1;
          end
        end else t_ph <= t_ph + 1;
      end
      // receiver
      if (b16) begin
        if (r_idle != 10'h3FF) r_idle <= r_idle + 1;
        if (r_bit == 0) begin
          if (!r_in) begin r_bit <= 1; r_ph <= 0; end
        end else if (r_bit == 1) begin
          if (r_ph == 7) begin r_ph <= 0; r_bit <= r_in ? 0 : 2; end
          else r_ph <= r_ph + 1;
        end else if (r_ph == 15) begin
          r_ph <= 0;
          if (r_bit <= 9) begin r_sh <= {r_in, r_sh[7:1]}; r_bit <= r_bit + 1; end
          else begin
            r_bit <= 0;
            fe <= ~r_in;
            r_idle <= 0;
            if (rx_n == (fifo_en ? 16 : 1)) oe <= 1;
            else begin rxf[rx_wr] <= r_sh; rx_wr <= rx_wr + 1; rx_n <= rx_n + 1; end
          end
        end else r_ph <= r_ph + 1;
      end
    end
  end

  assign {o8, o7, o6, o5, o4, o3, o2, o1} = dout;
  assign {e8, e7, e6, e5, e4, e3, e2, e1} = {8{rd}};
  assign o11 = mcr[4] ? 1'b1 : t_line;   // SOUT idles high in loopback
  assign o15 = ~b16;                     // ~BAUDOUT
  assign o17 = ~i16;                     // XOUT
  assign o23 = ~rd;                      // DDIS: low while the CPU reads
  assign o24 = ~thre;                    // ~TXRDY
  assign o29 = ~(rx_n != 0);             // ~RXRDY
  assign o30 = iid != 4'h1;              // INTR
  assign o31 = mcr[4] | ~mcr[3];         // ~OUT2
  assign o32 = mcr[4] | ~mcr[1];         // ~RTS
  assign o33 = mcr[4] | ~mcr[0];         // ~DTR
  assign o34 = mcr[4] | ~mcr[2];         // ~OUT1
endmodule
