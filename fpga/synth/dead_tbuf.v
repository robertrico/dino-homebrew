// dead_tbuf.v -- yosys techmap rule: DELETE tri-state buffers that are
// provably never enabled.
//
// Why this file exists (the Task-13 rework's item-3 blocker, root-caused
// 2026-08-09; full write-up in .superpowers/sdd/2026-08-08-dino-fpga-port/
// task-13-report.md, "Bus resolution + gates"):
//
// Every constant-direction '245 in this design has ONE dead side. `dir` is
// tied to a literal in the generated sheet, so the model's own drive equation
// for the other side -- ttl_74ls245.vhd's `a0_o <= b0_i when (ce_n='0' and
// dir='0') else 'Z'` with dir tied '1' -- reduces to a constant 'Z'. That is
// CORRECT hardware (a transceiver pin pointing the wrong way is an input,
// full stop) and it is what a real board does.
//
// The exact census, measured (not counted off the schematic) by walking the
// flattened RTLIL for $_TBUF_ cells whose E port is connected to 1'0 and
// bucketing them by the hierarchical instance on their Y net -- 68 cells:
//
//   mar_i.u54                 8      \
//   mar_i.u59                 8      |
//   memory_i.u19              8      |  EIGHT constant-`dir` '245s,
//   registers_a_b_i.u44       8      |  8 data pins each = 64
//   program_counter_i.u11     8      |
//   program_counter_i.u12     8      |  (u13/u14 are dir => '0', so it is
//   program_counter_i.u13     8      |   their B side that is dead; the
//   program_counter_i.u14     8      /   other six are dir => '1')
//   microcode_i.u17           4      <- NOT a '245: see below
//
// microcode U17 is a '74LS244 whose SECOND half is permanently disabled --
// `s2g_n => '1'` with all four of s2y1..s2y4 mapped `open` (fpga/gen/
// microcode.vhd). Four dead drivers on unconnected outputs. They are not
// part of the multiply-driven-net problem (they drive nothing at all), and
// removing them is equally exact; they are listed so the 68 reconciles.
//
// But fpga_gen.py ties BOTH `<pin>_i` and `<pin>_o` of a bidirectional model
// pin onto the same net (that association pair IS the shared-bus wiring --
// see the item-1 note in ttl_74ls245.vhd), so after `flatten` the dead side
// still exists as a `$_TBUF_` with E constant 0 sitting on a net that already
// has a real driver. `opt_expr` folds E to 1'0 but does NOT remove the cell
// (measured: 352 $_TBUF_ before and after). `tribuf -logic` then resolves the
// tri-state drivers of that net into a mux and connects the mux to the net --
// ALONGSIDE the real driver, because a non-tri-state driver ('193 counter Q,
// registered ROM data) is invisible to it. Result: 16 multiply-driven M-bus
// nets + 8 multiply-driven MDR-bus nets, and nextpnr-ecp5 refuses to place.
//
// Deleting a tri-state buffer whose enable is a hard constant 0 is exact, not
// an approximation: it can never contribute a value to its net, in any state,
// under any input. Leaving Y unassigned in the replacement is how a techmap
// rule says "this cell drives nothing".
//
// Cells with a non-constant enable (the five genuinely dynamic-direction
// '245s -- U21, U25, U41/U42/U43 -- and every '373/'244/ROM/RAM output
// enable) hit _TECHMAP_FAIL_ and are left untouched for `tribuf -logic` to
// resolve normally.
module \$_TBUF_ (A, E, Y);
  input A, E;
  output Y;

  parameter _TECHMAP_CONSTMSK_E_ = 0;
  parameter _TECHMAP_CONSTVAL_E_ = 0;

  generate
    if (_TECHMAP_CONSTMSK_E_ == 1'b1 && _TECHMAP_CONSTVAL_E_ == 1'b0) begin
      // Provably dead driver: Y is intentionally left undriven, which
      // removes this cell's contribution to the net entirely.
    end else begin
      wire _TECHMAP_FAIL_ = 1'b1;
    end
  endgenerate
endmodule
