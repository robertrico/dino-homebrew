// proto_card -- the template for a hand-written DINO card.
//
// A card on the card contract (docs/notes/fpga_twin_gen.py docstring): its
// port list IS fpga/gen/dino_card_ports.vh, the 37 non-rail pins of the
// 50-pin edge by pin number. Copy this file to fpga/cards/<name>.v, rename
// the module, fill in "the card": what it answers on a read (rdata) and
// what it takes on a write (win_wr, in_W*). Then add its entry, with its
// oracle model, to docs/notes/fpga_cards.py and seat it with one line in
// fpga_slots_gen.SLOTS.
//
// This card answers 0xFF at every address of its window: a card that
// decodes but holds nothing. It never drives W outside its window or on a
// write, and drives no other pin (test_fpga_slots.py).
module proto_card #(parameter integer WINDOW = 3) (
`include "dino_card_ports.vh"
);
`include "dino_card_in.vh"

  // ---- the slot decode (fpga/cards/card_window.v) -------------------------
  wire win_sel, win_rd, win_wr;
  card_window #(.WINDOW(WINDOW)) window (
    .m11(in_M11), .m12(in_M12), .m13(in_M13),
    .nio_sel(in_nIO_SEL), .nio_rd_q(in_nIO_RD_Q), .nio_wr(in_nIO_WR),
    .sel(win_sel), .rd(win_rd), .wr(win_wr));
  wire [10:0] offset = {in_M10, in_M9, in_M8, in_M7, in_M6, in_M5, in_M4,
                        in_M3, in_M2, in_M1, in_M0};

  // ---- the card: its registers ----------------------------------------------
  wire [7:0] rdata = 8'hFF;

  // ---- the edge: W only inside the window, on a read; nothing else ---------
  assign {e15_W7_do, e14_W6_do, e13_W5_do, e12_W4_do, e11_W3_do, e10_W2_do, e9_W1_do, e8_W0_do} = rdata;
  assign {e15_W7_de, e14_W6_de, e13_W5_de, e12_W4_de, e11_W3_de, e10_W2_de, e9_W1_de, e8_W0_de} = {8{win_rd}};
  assign e1_CLK_B_do = 1'b0;  assign e1_CLK_B_de = 1'b0;
  assign e3_nIO_SEL_do = 1'b0;  assign e3_nIO_SEL_de = 1'b0;
  assign e4_nIO_RD_Q_do = 1'b0;  assign e4_nIO_RD_Q_de = 1'b0;
  assign e5_nIO_WR_do = 1'b0;  assign e5_nIO_WR_de = 1'b0;
  assign e6_RESET_B_do = 1'b0;  assign e6_RESET_B_de = 1'b0;
  assign e18_nIRQ_do = 1'b0;  assign e18_nIRQ_de = 1'b0;
  assign e19_nNMI_do = 1'b0;  assign e19_nNMI_de = 1'b0;
  assign e20_nDMARQ_do = 1'b0;  assign e20_nDMARQ_de = 1'b0;
  assign e21_nDMAAK_do = 1'b0;  assign e21_nDMAAK_de = 1'b0;
  assign e22_RDY_do = 1'b0;  assign e22_RDY_de = 1'b0;
  assign e23_spare_do = 1'b0;  assign e23_spare_de = 1'b0;
  assign e24_spare_do = 1'b0;  assign e24_spare_de = 1'b0;
  assign e28_M0_do = 1'b0;  assign e28_M0_de = 1'b0;
  assign e29_M1_do = 1'b0;  assign e29_M1_de = 1'b0;
  assign e30_M2_do = 1'b0;  assign e30_M2_de = 1'b0;
  assign e31_M3_do = 1'b0;  assign e31_M3_de = 1'b0;
  assign e32_M4_do = 1'b0;  assign e32_M4_de = 1'b0;
  assign e33_M5_do = 1'b0;  assign e33_M5_de = 1'b0;
  assign e34_M6_do = 1'b0;  assign e34_M6_de = 1'b0;
  assign e35_M7_do = 1'b0;  assign e35_M7_de = 1'b0;
  assign e36_M8_do = 1'b0;  assign e36_M8_de = 1'b0;
  assign e37_M9_do = 1'b0;  assign e37_M9_de = 1'b0;
  assign e38_M10_do = 1'b0;  assign e38_M10_de = 1'b0;
  assign e39_M11_do = 1'b0;  assign e39_M11_de = 1'b0;
  assign e40_M12_do = 1'b0;  assign e40_M12_de = 1'b0;
  assign e41_M13_do = 1'b0;  assign e41_M13_de = 1'b0;
  assign e42_M14_do = 1'b0;  assign e42_M14_de = 1'b0;
  assign e43_M15_do = 1'b0;  assign e43_M15_de = 1'b0;
  assign e47_spare_do = 1'b0;  assign e47_spare_de = 1'b0;
  assign contention = 1'b0;
endmodule
