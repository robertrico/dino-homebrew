// Testbench for the generated Rev 1.0 netlist (netsim/gen/dino_rev1.v).
//
// Seats ROM images (plusargs U9/U15/U23/U24 = hex paths), holds the reset
// RC node low as SW2 would, releases it, and runs until the machine has
// sat in HALT for HALT_CLKS clocks or MAX_CLKS clocks have passed. Every
// change of OB is logged with its clock count. Instruction fetches are
// logged as `F <clk> <addr> <opcode>` when +trace is given.
//
// State check: no unknown bit in IR, T, PC, SP, A/B/C or the flags at any
// CLK rise after RESET. Uninitialised RAM is x, so a program that reads it
// will trip this; the coverage images do not.
`timescale 1ns/10ps
module tb;
  dino_rev1 dut ();

  reg [1023:0] path;
  integer max_us, max_clks, halt_clks, clks = 0, halted = 0, fetches = 0;
  reg trace;

  wire [7:0]  ob  = {dut.n_OB7, dut.n_OB6, dut.n_OB5, dut.n_OB4,
                     dut.n_OB3, dut.n_OB2, dut.n_OB1, dut.n_OB0};
  wire [7:0]  irb = {dut.n_IRB7, dut.n_IRB6, dut.n_IRB5, dut.n_IRB4,
                     dut.n_IRB3, dut.n_IRB2, dut.n_IRB1, dut.n_IRB0};
  wire [7:0]  mdr = {dut.n_MDR7, dut.n_MDR6, dut.n_MDR5, dut.n_MDR4,
                     dut.n_MDR3, dut.n_MDR2, dut.n_MDR1, dut.n_MDR0};
  wire [15:0] m   = {dut.n_M15, dut.n_M14, dut.n_M13, dut.n_M12,
                     dut.n_M11, dut.n_M10, dut.n_M9, dut.n_M8,
                     dut.n_M7, dut.n_M6, dut.n_M5, dut.n_M4,
                     dut.n_M3, dut.n_M2, dut.n_M1, dut.n_M0};
  wire [3:0]  t   = {dut.n_T3, dut.n_T2, dut.n_T1, dut.n_T0};

  initial begin
    $timeformat(-9, 0, "", 0);
    if ($value$plusargs("U9=%s", path))  $readmemh(path, dut.U9.r.mem);
    if ($value$plusargs("U15=%s", path)) $readmemh(path, dut.U15.r.mem);
    if ($value$plusargs("U23=%s", path)) $readmemh(path, dut.U23.r.mem);
    if ($value$plusargs("U24=%s", path)) $readmemh(path, dut.U24.r.mem);
    if ($value$plusargs("U26=%s", path)) $readmemh(path, dut.U26.r.mem);   // as L loads
    if (!$value$plusargs("MAX_CLKS=%d", max_clks)) max_clks = 2000000;
    if (!$value$plusargs("HALT_CLKS=%d", halt_clks)) halt_clks = 200;
    if (!$value$plusargs("MAX_US=%d", max_us)) max_us = 0;
    trace = $test$plusargs("trace");
    // SW2 held: the RC node low, then released to charge through R1.
    force dut.n_Net_C1_Pad1 = 1'b0;
    #20000;
    release dut.n_Net_C1_Pad1;
    $display("RESET released at %0t ns", $time);
  end

  initial #1 $display("POWERUP U20=%h U6=%h U49=%h SP=%h%h%h%h",
                      dut.U20.q, dut.U6.q, dut.U49.q, dut.U66.q, dut.U65.q, dut.U64.q, dut.U63.q);

  // a dead clock never reaches MAX_CLKS: stop on simulated time as well
  initial begin
    #1;
    if (max_us == 0) max_us = max_clks * 2 + 100;   // 1.024 MHz with margin
    #(max_us * 1000.0);
    $display("STUCK no progress by %0d us: clks=%0d CLK=%b osc=%b tap0=%b sel=%b RESET=%b",
             max_us, clks, dut.n_CLK, dut.n_CLK_OSC, dut.n_CLK_TAP0, dut.n_CLK_SEL, dut.n_RESET);
    $finish;
  end

  // State check: at every CLK rise after RESET, the machine's state must
  // hold no unknown bit. The first offender is named; all are counted.
  // C and V (U49 Q0, Q2) are left out: after a logic op they come from the
  // '382's Cn+4/OVR, which the datasheet does not table and DINO has never
  // measured, so the twin holds them x exactly as the oracle refuses to
  // guess them. Anything that DEPENDS on them turns PC or IR x and fails
  // here anyway.
  integer statex = 0;
  wire [61:0] state = {irb, t, dut.U1.q, dut.U2.q, dut.U3.q, dut.U4.q,
                       dut.U63.q, dut.U64.q, dut.U65.q, dut.U66.q,
                       dut.U31.q, dut.U32.q, dut.U33.q, dut.U49.q[3], dut.U49.q[1]};
  always @(posedge dut.n_CLK)
    if (dut.n_RESET === 1'b0 && ^state === 1'bx) begin
      statex = statex + 1;
      if (statex == 1)
        $display("STATEX clk=%0d IR=%h T=%h PC=%h%h%h%h SP=%h%h%h%h A/B/C=%h %h %h NZ=%b",
                 clks, irb, t, dut.U4.q, dut.U3.q, dut.U2.q, dut.U1.q,
                 dut.U66.q, dut.U65.q, dut.U64.q, dut.U63.q,
                 dut.U31.q, dut.U32.q, dut.U33.q, {dut.U49.q[3], dut.U49.q[1]});
    end

  // WE: every RAM ~WE pulse narrower than tWP (70 ns) is a violation.
  realtime we_fall;
  integer writes = 0, we_short = 0;
  always @(dut.n_Memory_nRAM_WRITE_EN)
    if (dut.n_Memory_nRAM_WRITE_EN === 1'b0) we_fall = $realtime;
    else if (dut.n_Memory_nRAM_WRITE_EN === 1'b1 && we_fall > 0) begin
      writes = writes + 1;
      if ($realtime - we_fall < 70) begin
        we_short = we_short + 1;
        $display("WE VIOLATION ~WE low %0.1f ns at clk=%0d T=%h m=%h", $realtime - we_fall, clks, t, m);
      end
    end

  always @(ob) $display("OB %02h clk=%0d t=%0t", ob, clks, $time);

  always @(posedge dut.n_CLK) begin
    clks = clks + 1;
    if (dut.n_CW15 === 1'b1) halted = halted + 1; else halted = 0;
    if (halted >= halt_clks) begin
      $display("HALT OB=%02h clk=%0d t=%0t fetches=%0d writes=%0d we_short=%0d statex=%0d",
               ob, clks, $time, fetches, writes, we_short, statex);
      $finish;
    end
    if (clks >= max_clks) begin
      $display("TIMEOUT OB=%02h clk=%0d m=%04h irb=%02h t=%0d we_short=%0d statex=%0d",
               ob, clks, m, irb, t, we_short, statex);
      $finish;
    end
  end

  // a fetch: T-count 0 at the CLK fall that opens the FETCH row's window
  always @(negedge dut.n_CLK) begin
    if (t === 4'd0 && dut.n_RESET === 1'b0) begin
      fetches = fetches + 1;
      if (trace) $display("F %0d %04h %02h", clks, m, mdr);
    end
  end
endmodule
