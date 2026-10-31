// deadbeef_card -- card 2: four bytes and nothing else. Built from
// fpga/cards/proto_card.v.
//
// In its window (WINDOW = 2: 0x5000-0x57FF) it reads DE AD BE EF at offsets
// 0x000, 0x555, 0x2AA, 0x7FF, and 0xFF everywhere else. The four offsets
// between them toggle every one of M0-M10, so a stuck or swapped low
// address line reads a wrong byte. asm/deadbeef.asm reads them.
module deadbeef_card #(parameter integer WINDOW = 2) (
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
  reg [7:0] rdata;
  always @* begin
    case (offset)
      11'h000: rdata = 8'hDE;
      11'h555: rdata = 8'hAD;
      11'h2AA: rdata = 8'hBE;
      11'h7FF: rdata = 8'hEF;
      default: rdata = 8'hFF;
    endcase
  end

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
