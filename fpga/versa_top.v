// The FPGA twin on the Lattice ECP5-5G Versa (LFE5UM5G-45F).
//
// dino_system (fpga/gen/, generated from the three KiCad projects) on a
// 48 MHz clk_sys from the board's 100 MHz oscillator. What the board
// stands in for:
//   - power-up: nothing changes state for the first 1000 ticks (the rails
//     ramp), then the reset RC node is held low a further 50 machine
//     clocks, as C1 holds it at power-on; the Versa reset button (T1)
//     holds it low too, as SW2 does
//   - the 8 user LEDs show OB (lit = 1), read like a byte: bit 7 on D25,
//     then D24 D22 D21 D26 D27 D28, bit 0 on D29 (led[0] is D25, so the
//     bits go in reversed); they are active low on the board
//   - the 8 user DIP switches are card zero's SW1, read like a byte: bit 7
//     on dip[0] (H2), bit 0 on dip[7] (K20). ON reads 0 on the Versa and a
//     closed SW1 switch pulls its bit to 0 on DINO, so ON = closed
//   - the serial card's FTDI header goes to the USB-serial adapter on the
//     pins b8008_monitor uses (TX B19, RX B12)
// Machine speed: Y1 toggles every 6 ticks (fpga_twin_gen.py HALF), so Y1
// is 4.0 MHz and CLK is 48 MHz / 48 = 1.0 MHz, the breadboard's 1.024 MHz
// within 2.4%. A machine clock is MCLK = 48 ticks. The UART's can runs at its real
// 3.6864 MHz, so the line is 9600 8N1 as on the bench.
module versa_top (input wire clk, input wire rst_n,
                  input wire [7:0] dip,
                  input wire uart_rx, output wire uart_tx,
                  output wire [7:0] led);
  wire clk_sys, locked;
  pll_48mhz pll (.clkin(clk), .clkout0(clk_sys), .locked(locked));

  reg [15:0] ticks = 16'd0;
  always @(posedge clk_sys)
    if (!locked) ticks <= 16'd0;
    else if (ticks != 16'hFFFF) ticks <= ticks + 16'd1;
  wire live = ticks >= 16'd1000;
  localparam MCLK = 16'd48;
  wire por = ticks < 16'd1000 + 16'd50 * MCLK;

  // the asynchronous inputs, brought into clk_sys
  reg [1:0] rx_s = 2'b11, rst_s = 2'b11;
  reg [7:0] dip_s0 = 8'hFF, dip_s1 = 8'hFF;
  always @(posedge clk_sys) begin
    rx_s <= {rx_s[0], uart_rx};
    rst_s <= {rst_s[0], rst_n};
    dip_s0 <= dip;
    dip_s1 <= dip_s0;
  end

  wire [7:0] ob;
  wire halt, contention;
  dino_system dino (.clk(clk_sys), .live(live),
                    .rc_low(por | ~rst_s[1]),
                    .sw_closed(~{dip_s1[0], dip_s1[1], dip_s1[2], dip_s1[3],
                                 dip_s1[4], dip_s1[5], dip_s1[6], dip_s1[7]}),
                    .sin(rx_s[1]), .sout(uart_tx),
                    .ob(ob), .halt(halt), .contention(contention));
  assign led = ~{ob[0], ob[1], ob[2], ob[3], ob[4], ob[5], ob[6], ob[7]};
endmodule
