// The slot decode a DINO card makes, as the drawn cards make it: a '138 on
// M11-M13 (A, B, C), enabled by ~{IO_SEL} on ~G2A, ~G2B tied low, G1 tied
// high (the serial card's U101). Output WINDOW, active low, selects the 2K
// window 0x4000 + 0x800 * WINDOW. PHASE_G's rule: a card with its own
// read/write strobes enables on ~{IO_SEL} and qualifies with ~{IO_RD_Q} /
// ~{IO_WR}; card zero (read-only, older) enables on ~{IO_RD_Q} instead.
//
// sel  the window is addressed (the '138 output low)
// rd   sel and ~{IO_RD_Q} low: the card may drive W
// wr   sel and ~{IO_WR} low: the card may take W
module card_window #(parameter integer WINDOW = 0)
                   (input wire m11, m12, m13, nio_sel, nio_rd_q, nio_wr,
                    output wire sel, rd, wr);
  wire [7:0] y_n;
  f_138 decode (.i1(m11), .i2(m12), .i3(m13), .i4(nio_sel), .i5(1'b0), .i6(1'b1),
                .o15(y_n[0]), .o14(y_n[1]), .o13(y_n[2]), .o12(y_n[3]),
                .o11(y_n[4]), .o10(y_n[5]), .o9(y_n[6]), .o7(y_n[7]));
  assign sel = ~y_n[WINDOW];
  assign rd = sel & ~nio_rd_q;
  assign wr = sel & ~nio_wr;
endmodule
