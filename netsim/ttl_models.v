// Part models for the netlist simulation (docs/notes/netsim_gen.py).
//
// One module per part type, ports p1..pN = DIP pin numbers, so the
// generated netlist connects them exactly as the copper does. Function
// tables are the datasheets'; pinned by docs/notes/test_netsim.py.
//
// Unknowns are kept honest rather than resolved:
//   - x on a select/enable/control gives x wherever the outcome depends on it.
//   - A memory output, after its address moves, switches each differing bit
//     once at a seeded random moment inside its access time (mem_read).
//   - Outputs pass any pulse 4 ns or wider (pd): runts are not filtered.
//   - An SRAM write pulse shorter than tWP, or one during which the address
//     moves, leaves the cell(s) x.
//   - Stateful parts power up at a definite random state from SEED, as real
//     silicon does: not 0 (a stand-in better than the hardware hides
//     defects) and not x (a free-running divider would never resolve).
//   - The '382's Cn+4/OVR in logic modes are x (data-dependent, never
//     measured on DINO); CLEAR gives H/H per the truth table.
`timescale 1ns/10ps

// Power-up: rails ramp over milliseconds, so nothing changes state while
// they do. For the first POWERUP_NS no flop, counter or latch moves; each
// holds its random power-up state while the gates settle to definite
// levels. Without it, gate outputs leaving x at t = 0 look like clock
// edges (U20's tap clocked U27 before U27's own ~Q existed). The runner
// sets 1000; the unit tests leave it 0.
`ifndef POWERUP_NS
`define POWERUP_NS 0
`endif
// `LIVE_DECL gives a stateful model its own `live` flag; level-sensitive
// blocks list `live` so a held async input (a preset from the reset RC)
// takes effect the moment the window ends, as it would on a live chip.
`define LIVE live
`define LIVE_DECL reg live = 1'b0; initial #(`POWERUP_NS) live = 1'b1;

// Propagation: pulses under REJ ns are swallowed (simulator slivers, which
// silicon also eats); anything wider comes out whole after TPD. A runt
// shorter than the part's own delay still gets through, as the 14 ns one
// at U30.7 did on 2026-09-29. An inertial `assign #TPD` would eat it.
module pd #(parameter W = 1, parameter real TPD = 10, parameter real REJ = 4)
           (input wire [W-1:0] a, output reg [W-1:0] y);
  wire [W-1:0] f;
  assign #(REJ) f = a;
  initial y = {W{1'bx}};
  always @(f) y <= #(TPD - REJ) f;
endmodule

// ---- gates -----------------------------------------------------------------

module ttl_00 #(parameter real TPD = 10) (inout wire p1, p2, p3, p4, p5, p6, p7,
                                           p8, p9, p10, p11, p12, p13, p14);
  pd #(1, TPD) d1 (~(p1 & p2), p3);
  pd #(1, TPD) d2 (~(p4 & p5), p6);
  pd #(1, TPD) d3 (~(p9 & p10), p8);
  pd #(1, TPD) d4 (~(p12 & p13), p11);
endmodule

module ttl_08 #(parameter real TPD = 10) (inout wire p1, p2, p3, p4, p5, p6, p7,
                                           p8, p9, p10, p11, p12, p13, p14);
  pd #(1, TPD) d5 (p1 & p2, p3);
  pd #(1, TPD) d6 (p4 & p5, p6);
  pd #(1, TPD) d7 (p9 & p10, p8);
  pd #(1, TPD) d8 (p12 & p13, p11);
endmodule

module ttl_32 #(parameter real TPD = 14) (inout wire p1, p2, p3, p4, p5, p6, p7,
                                           p8, p9, p10, p11, p12, p13, p14);
  pd #(1, TPD) d9 (p1 | p2, p3);
  pd #(1, TPD) d10 (p4 | p5, p6);
  pd #(1, TPD) d11 (p9 | p10, p8);
  pd #(1, TPD) d12 (p12 | p13, p11);
endmodule

module ttl_02 #(parameter real TPD = 10) (inout wire p1, p2, p3, p4, p5, p6, p7,
                                           p8, p9, p10, p11, p12, p13, p14);
  pd #(1, TPD) d13 (~(p2 | p3), p1);
  pd #(1, TPD) d14 (~(p5 | p6), p4);
  pd #(1, TPD) d15 (~(p8 | p9), p10);
  pd #(1, TPD) d16 (~(p11 | p12), p13);
endmodule

module ttl_04 #(parameter real TPD = 10) (inout wire p1, p2, p3, p4, p5, p6, p7,
                                           p8, p9, p10, p11, p12, p13, p14);
  pd #(1, TPD) d17 (~p1, p2);
  pd #(1, TPD) d18 (~p3, p4);
  pd #(1, TPD) d19 (~p5, p6);
  pd #(1, TPD) d20 (~p9, p8);
  pd #(1, TPD) d21 (~p11, p10);
  pd #(1, TPD) d22 (~p13, p12);
endmodule

// ---- '74 dual D flip-flop ----------------------------------------------------

module ttl_74_half #(parameter real TPD = 20, parameter integer SEED = 1)
                   (input wire nr, d, c, ns, output wire q, nq);
  // sd is set inside the initial (a declaration initialiser runs in no fixed
  // order against it), scrambled, and the first draw thrown away: $random's
  // first draw from a small seed has its low bits all 0. Either way every
  // part powered up identical.
  `LIVE_DECL
  integer sd;
  reg s;
  initial begin sd = SEED * 32'h9E3779B9; s = $random(sd); s = $random(sd); end
  always @(posedge c)
    if (`LIVE && nr === 1'b1 && ns === 1'b1) s <= (c === 1'b1) ? d : ((s === d) ? s : 1'bx);
  always @(nr or ns or live)
    if (!`LIVE) ;
    else if (nr === 1'b0) s = 1'b0;
    else if (ns === 1'b0) s = 1'b1;
    else if (nr !== 1'b1 || ns !== 1'b1) s = 1'bx;
  wire both = (nr === 1'b0 && ns === 1'b0);
  pd #(1, TPD) d23 (both ? 1'b1 : s, q);
  pd #(1, TPD) d24 (both ? 1'b1 : ~s, nq);
endmodule

module ttl_74 #(parameter real TPD = 20, parameter integer SEED = 1)
              (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14);
  ttl_74_half #(.TPD(TPD), .SEED(SEED)) a (.nr(p1), .d(p2), .c(p3), .ns(p4), .q(p5), .nq(p6));
  ttl_74_half #(.TPD(TPD), .SEED(SEED + 7919)) b (.nr(p13), .d(p12), .c(p11), .ns(p10), .q(p9), .nq(p8));
endmodule

// ---- '138 3-to-8 decoder: E1, E2 active low, E3 active high ---------------

module ttl_138 #(parameter real TPD = 20) (inout wire p1, p2, p3, p4, p5, p6, p7, p8,
                                            p9, p10, p11, p12, p13, p14, p15, p16);
  wire en = ~p4 & ~p5 & p6;
  wire [2:0] a = {p3, p2, p1};
  pd #(1, TPD) d25 (~(en & (a == 3'd0)), p15);
  pd #(1, TPD) d26 (~(en & (a == 3'd1)), p14);
  pd #(1, TPD) d27 (~(en & (a == 3'd2)), p13);
  pd #(1, TPD) d28 (~(en & (a == 3'd3)), p12);
  pd #(1, TPD) d29 (~(en & (a == 3'd4)), p11);
  pd #(1, TPD) d30 (~(en & (a == 3'd5)), p10);
  pd #(1, TPD) d31 (~(en & (a == 3'd6)), p9);
  pd #(1, TPD) d32 (~(en & (a == 3'd7)), p7);
endmodule

// ---- '157 quad 2:1 mux, E active low (E high: outputs low) ----------------

module ttl_157 #(parameter real TPD = 12) (inout wire p1, p2, p3, p4, p5, p6, p7, p8,
                                            p9, p10, p11, p12, p13, p14, p15, p16);
  pd #(1, TPD) d33 (~p15 & (p1 ? p3 : p2), p4);
  pd #(1, TPD) d34 (~p15 & (p1 ? p6 : p5), p7);
  pd #(1, TPD) d35 (~p15 & (p1 ? p10 : p11), p9);
  pd #(1, TPD) d36 (~p15 & (p1 ? p13 : p14), p12);
endmodule

// ---- '163 synchronous 4-bit counter, synchronous clear --------------------

module ttl_163 #(parameter integer SEED = 1, parameter real TPD = 15) (inout wire p1, p2, p3, p4, p5, p6, p7, p8,
                                            p9, p10, p11, p12, p13, p14, p15, p16);
  `LIVE_DECL
  integer sd;
  reg [3:0] q;
  initial begin sd = SEED * 32'h9E3779B9; q = $random(sd); q = $random(sd); end
  always @(posedge p2) if (`LIVE) begin
    if (p2 !== 1'b1) q <= 4'bx;
    else if (p1 === 1'b0) q <= 4'd0;
    else if (p1 !== 1'b1) q <= 4'bx;
    else if (p9 === 1'b0) q <= {p6, p5, p4, p3};
    else if (p9 !== 1'b1) q <= 4'bx;
    else if ((p7 & p10) === 1'b1) q <= q + 4'd1;
    else if ((p7 & p10) !== 1'b0) q <= 4'bx;
  end
  pd #(4, TPD) d37 (q, {p11, p12, p13, p14});
  pd #(1, TPD) d38 ((q == 4'hF) & p10, p15);
endmodule

// ---- '169 synchronous up/down counter ---------------------------------------

module ttl_169 #(parameter integer SEED = 1, parameter real TPD = 15) (inout wire p1, p2, p3, p4, p5, p6, p7, p8,
                                            p9, p10, p11, p12, p13, p14, p15, p16);
  `LIVE_DECL
  integer sd;
  reg [3:0] q;
  initial begin sd = SEED * 32'h9E3779B9; q = $random(sd); q = $random(sd); end
  always @(posedge p2) if (`LIVE) begin
    if (p2 !== 1'b1) q <= 4'bx;
    else if (p9 === 1'b0) q <= {p6, p5, p4, p3};
    else if (p9 !== 1'b1) q <= 4'bx;
    else if ((p7 | p10) === 1'b0) q <= (p1 === 1'b1) ? q + 4'd1 :
                                       (p1 === 1'b0) ? q - 4'd1 : 4'bx;
    else if ((p7 | p10) !== 1'b1) q <= 4'bx;
  end
  pd #(4, TPD) d39 (q, {p11, p12, p13, p14});
  pd #(1, TPD) d40 (~(~p10 & (p1 ? (q == 4'hF) : (q == 4'h0))), p15);
endmodule

// ---- '193 up/down counter: async CLR (high), async ~LOAD, dual clock -------

module ttl_193 #(parameter integer SEED = 1, parameter real TPD = 20) (inout wire p1, p2, p3, p4, p5, p6, p7, p8,
                                            p9, p10, p11, p12, p13, p14, p15, p16);
  `LIVE_DECL
  integer sd;
  reg [3:0] q;
  initial begin sd = SEED * 32'h9E3779B9; q = $random(sd); q = $random(sd); end
  wire [3:0] d = {p9, p10, p1, p15};
  always @(p14 or p11 or d or live)
    if (!`LIVE) ;
    else if (p14 === 1'b1) q = 4'd0;
    else if (p14 !== 1'b0) q = 4'bx;
    else if (p11 === 1'b0) q = d;
    else if (p11 !== 1'b1) q = 4'bx;
  always @(posedge p5)
    if (`LIVE && p14 === 1'b0 && p11 === 1'b1)
      q = (p4 === 1'b1 && p5 === 1'b1) ? q + 4'd1 : 4'bx;
  always @(posedge p4)
    if (`LIVE && p14 === 1'b0 && p11 === 1'b1)
      q = (p5 === 1'b1 && p4 === 1'b1) ? q - 4'd1 : 4'bx;
  pd #(4, TPD) d41 (q, {p7, p6, p2, p3});
  pd #(1, TPD) d42 (~((q == 4'hF) & ~p5), p12);
  pd #(1, TPD) d43 (~((q == 4'h0) & ~p4), p13);
endmodule

// ---- '244 octal buffer, two active-low enables ------------------------------

module ttl_244 #(parameter real TPD = 12) (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10,
                                            p11, p12, p13, p14, p15, p16, p17, p18, p19, p20);
  function automatic tri3(input en_n, input v);
    tri3 = (en_n === 1'b0) ? v : (en_n === 1'b1) ? 1'bz : 1'bx;
  endfunction
  pd #(1, TPD) d44 (tri3(p1, p2), p18);
  pd #(1, TPD) d45 (tri3(p1, p4), p16);
  pd #(1, TPD) d46 (tri3(p1, p6), p14);
  pd #(1, TPD) d47 (tri3(p1, p8), p12);
  pd #(1, TPD) d48 (tri3(p19, p11), p9);
  pd #(1, TPD) d49 (tri3(p19, p13), p7);
  pd #(1, TPD) d50 (tri3(p19, p15), p5);
  pd #(1, TPD) d51 (tri3(p19, p17), p3);
endmodule

// ---- '245 octal transceiver: DIR high = A to B, CE active low --------------

module ttl_245 #(parameter real TPD = 10) (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10,
                                            p11, p12, p13, p14, p15, p16, p17, p18, p19, p20);
  wire [7:0] a = {p9, p8, p7, p6, p5, p4, p3, p2};
  wire [7:0] b = {p11, p12, p13, p14, p15, p16, p17, p18};
  wire a2b = (p19 === 1'b0 && p1 === 1'b1);
  wire b2a = (p19 === 1'b0 && p1 === 1'b0);
  wire off = (p19 === 1'b1);
  pd #(8, TPD) d52 (a2b ? a : off || b2a ? 8'bz : 8'bx, {p11, p12, p13, p14, p15, p16, p17, p18});
  pd #(8, TPD) d53 (b2a ? b : off || a2b ? 8'bz : 8'bx, {p9, p8, p7, p6, p5, p4, p3, p2});
endmodule

// ---- '273 octal D flip-flop, async clear -------------------------------------

module ttl_273 #(parameter integer SEED = 1, parameter real TPD = 18) (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10,
                                            p11, p12, p13, p14, p15, p16, p17, p18, p19, p20);
  `LIVE_DECL
  integer sd;
  reg [7:0] q;
  initial begin sd = SEED * 32'h9E3779B9; q = $random(sd); q = $random(sd); end
  wire [7:0] d = {p18, p17, p14, p13, p8, p7, p4, p3};
  always @(posedge p11)
    if (`LIVE && p1 === 1'b1) q <= (p11 === 1'b1) ? d : 8'bx;
  always @(p1 or live)
    if (!`LIVE) ;
    else if (p1 === 1'b0) q = 8'd0;
    else if (p1 !== 1'b1) q = 8'bx;
  pd #(8, TPD) d54 (q, {p19, p16, p15, p12, p9, p6, p5, p2});
endmodule

// ---- '373 octal transparent latch, OE active low ----------------------------

module ttl_373 #(parameter integer SEED = 1, parameter real TPD = 18) (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10,
                                            p11, p12, p13, p14, p15, p16, p17, p18, p19, p20);
  `LIVE_DECL
  integer sd;
  reg [7:0] q;
  initial begin sd = SEED * 32'h9E3779B9; q = $random(sd); q = $random(sd); end
  wire [7:0] d = {p18, p17, p14, p13, p8, p7, p4, p3};
  integer i;
  always @(p11 or d or live)
    if (!`LIVE) ;
    else if (p11 === 1'b1) q = d;
    else if (p11 !== 1'b0)
      for (i = 0; i < 8; i = i + 1) if (q[i] !== d[i]) q[i] = 1'bx;
  pd #(8, TPD) d55 ((p1 === 1'b0) ? q : (p1 === 1'b1) ? 8'bz : 8'bx, {p19, p16, p15, p12, p9, p6, p5, p2});
endmodule

// ---- 74F382 4-bit ALU ---------------------------------------------------------

module ttl_382 #(parameter real TPD = 9) (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10,
                                           p11, p12, p13, p14, p15, p16, p17, p18, p19, p20);
  wire [2:0] s = {p7, p6, p5};
  wire [3:0] a = {p17, p19, p1, p3};
  wire [3:0] b = {p16, p18, p2, p4};
  wire cn = p15;
  reg [3:0] f;
  reg c4, ovr;
  reg [4:0] sum;
  reg [3:0] lo;
  // cn is an argument: @* does not see signals a task reads on its own.
  task arith(input [3:0] x, input [3:0] y, input c);
    begin
      sum = x + y + c;
      lo  = x[2:0] + y[2:0] + c;
      f   = sum[3:0];
      c4  = sum[4];
      ovr = lo[3] ^ sum[4];
    end
  endtask
  always @* begin
    case (s)
      3'd0: begin f = 4'h0; c4 = 1'b1; ovr = 1'b1; end
      3'd1: arith(b, ~a, cn);
      3'd2: arith(a, ~b, cn);
      3'd3: arith(a, b, cn);
      3'd4: begin f = a ^ b; c4 = 1'bx; ovr = 1'bx; end
      3'd5: begin f = a | b; c4 = 1'bx; ovr = 1'bx; end
      3'd6: begin f = a & b; c4 = 1'bx; ovr = 1'bx; end
      3'd7: begin f = 4'hF; c4 = 1'bx; ovr = 1'bx; end
      default: begin f = 4'bx; c4 = 1'bx; ovr = 1'bx; end
    endcase
  end
  pd #(4, TPD) d56 (f, {p12, p11, p9, p8});
  pd #(1, TPD) d57 (c4, p14);
  pd #(1, TPD) d58 (ovr, p13);
endmodule

// ---- memories -----------------------------------------------------------------
// 28-pin JEDEC byte-wide pinout: A14 p1, A13 p26, A12 p2, A11 p23, A10 p21,
// A9 p24, A8 p25, A7-A0 p3-p10; data p11-13, p15-19; ~CE p20 ~OE p22 ~WE p27.

module mem_read #(parameter real TACC = 150, parameter ABITS = 15, parameter integer SEED = 1)
                 (input wire [ABITS-1:0] addr, input wire [31:0] wseq, output wire [7:0] d);
  // What the array puts out. After the address (or the cell) changes, each
  // bit that differs moves ONCE, at a seeded random moment between TACC/3
  // and TACC; until then it holds the old datum.
  reg [7:0] mem [0:(1 << ABITS) - 1];
  genvar i;
  generate for (i = 0; i < 8; i = i + 1) begin : b
    integer sd, my = 0, fire = 0;
    initial begin sd = (SEED * 8 + i) * 32'h9E3779B9; my = $random(sd); my = 0; end
    reg v = 1'bx;
    realtime dl;
    always @(addr or wseq) begin
      my = my + 1;
      dl = TACC / 3.0 + (TACC * 2.0 / 3.0) * (($random(sd) & 32'hFFFF) / 65535.0);
      fire <= #(dl) my;
    end
    always @(fire) if (fire == my) v = mem[addr][i];
    assign d[i] = v;
  end endgenerate
endmodule

module eeprom_28 #(parameter real TACC = 150, parameter real TOE = 70, parameter ABITS = 15,
                   parameter FILE = "", parameter integer SEED = 1)
                  (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14,
                   p15, p16, p17, p18, p19, p20, p21, p22, p23, p24, p25, p26, p27, p28);
  wire [14:0] af = {p1, p26, p2, p23, p21, p24, p25, p3, p4, p5, p6, p7, p8, p9, p10};
  wire [7:0] d;
  mem_read #(.TACC(TACC), .ABITS(ABITS), .SEED(SEED)) r (.addr(af[ABITS-1:0]), .wseq(32'd0), .d(d));
  initial if (FILE != "") $readmemh(FILE, r.mem);
  wire en = ~p20 & ~p22;
  wire en_d;
  assign #(TOE, 40) en_d = en;
  assign {p19, p18, p17, p16, p15, p13, p12, p11} =
      (en_d === 1'b1) ? d : (en_d === 1'b0) ? 8'bz : 8'bx;
endmodule

module sram_28 #(parameter real TAA = 100, parameter real TOE = 50, parameter real TWP = 70,
                 parameter FILE = "", parameter integer SEED = 1)
                (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14,
                 p15, p16, p17, p18, p19, p20, p21, p22, p23, p24, p25, p26, p27, p28);
  wire [14:0] addr = {p1, p26, p2, p23, p21, p24, p25, p3, p4, p5, p6, p7, p8, p9, p10};
  wire [7:0] dq = {p19, p18, p17, p16, p15, p13, p12, p11};
  reg [31:0] wseq = 0;
  wire [7:0] d;
  mem_read #(.TACC(TAA), .ABITS(15), .SEED(SEED)) r (.addr(addr), .wseq(wseq), .d(d));
  initial if (FILE != "") $readmemh(FILE, r.mem);

  // A write is the overlap of ~CE low and ~WE low; it commits at its end.
  reg writing = 0, moved = 0;
  realtime wstart;
  reg [14:0] waddr;
  // wsure/wnone are evaluated IN the block: as wires they could still hold
  // the previous value when this block runs (a write began on ~WE's rise).
  reg wsure, wnone;
  always @(p20 or p27) begin
    wsure = (p20 === 1'b0 && p27 === 1'b0);
    wnone = (p20 === 1'b1 || p27 === 1'b1);
    if (wsure && !writing) begin
      writing = 1; moved = 0; wstart = $realtime; waddr = addr;
    end else if (!wsure && writing) begin
      writing = 0;
      if ($realtime - wstart < TWP || moved) r.mem[waddr] = 8'bx;
      else r.mem[waddr] = dq;
      wseq = wseq + 1;
    end
    if (!wsure && !wnone) begin            // ~CE or ~WE is x: maybe a write
      r.mem[addr] = 8'bx;
      wseq = wseq + 1;
    end
  end
  always @(addr) if (writing) begin
    moved = 1;
    r.mem[addr] = 8'bx;                    // the new address is written too
  end

  wire en = ~p20 & ~p22 & p27;
  wire en_d;
  assign #(TOE, 20) en_d = en;
  assign {p19, p18, p17, p16, p15, p13, p12, p11} =
      (en_d === 1'b1) ? d : (en_d === 1'b0) ? 8'bz : 8'bx;
endmodule

// ---- the oscillator can ---------------------------------------------------------

module osc_14 #(parameter real HALF = 122.0703125, parameter real START = 2000)
              (inout wire p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14);
  // Low until START ns after power-up (a can's start-up time), then runs.
  // Starting at t = 0 clocked U27's toggle before its own ~Q had settled.
  reg o = 1'b0;
  initial begin
    #(START);
    forever #(HALF) o = ~o;
  end
  assign p8 = o;
endmodule
