// Verilator harness for the FPGA twin (fpga/gen/dino_system.v).
//
// Drives dino_system the way fpga/versa_top.v does: one tick per 48 MHz
// system clock, `live` after the power-up window, the reset RC node held
// low, then released. Card zero's switches come from +SW=<hex> (1 = closed,
// default open, so SW1 reads 0xFF). +SIN=<text> is typed into the serial
// card at 9600 8N1; what it sends back on SOUT is printed as it arrives.
//
// Prints `OB <hex> tick=<n>` on every change of OB, then one of
//   HALT OB=<hex> ticks=<n> contention=<ticks>
//   TIMEOUT OB=<hex> ticks=<n> contention=<ticks>
// HALT = CW15 high for +HALT_TICKS ticks in a row (default 2 ms: 2000 machine
// CLKs, and long enough for the UART to send its last two characters).
#include "Vdino_system.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <string>

// CLK_HZ and MCLK (one machine clock, 8 * HALF ticks) as fpga_twin_gen.py
static const long CLK_HZ = 48000000, MCLK = 48, BAUD = 9600, BIT = CLK_HZ / BAUD;

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    auto *top = new Vdino_system;
    long max_ticks = 2000000000L, halt_ticks = 2000L * MCLK, live_at = 1000,
         reset_until = 1000 + 50L * MCLK;
    int sw = 0, gap_bits = 12, gap2_bits = 10;
    long sin2_at = -1;
    std::string sin, sin2;
    const char *a;
    if ((a = Verilated::commandArgsPlusMatch("MAX_TICKS="))[0]) max_ticks = atol(a + 11);
    if ((a = Verilated::commandArgsPlusMatch("HALT_TICKS="))[0]) halt_ticks = atol(a + 12);
    if ((a = Verilated::commandArgsPlusMatch("SW="))[0]) sw = (int)strtol(a + 4, nullptr, 16);
    if ((a = Verilated::commandArgsPlusMatch("SIN="))[0]) sin = a + 5;
    if ((a = Verilated::commandArgsPlusMatch("GAP_BITS="))[0]) gap_bits = atoi(a + 10);
    // +SIN2=<text> +SIN2_AT=<tick> +GAP2_BITS=<n>: a second burst at a set time
    if ((a = Verilated::commandArgsPlusMatch("SIN2="))[0]) sin2 = a + 6;
    if ((a = Verilated::commandArgsPlusMatch("SIN2_AT="))[0]) sin2_at = atol(a + 9);
    if ((a = Verilated::commandArgsPlusMatch("GAP2_BITS="))[0]) gap2_bits = atoi(a + 11);
    for (size_t i = 0; (i = sin2.find("\\r", i)) != std::string::npos;) sin2.replace(i, 2, "\r");
    for (size_t i = 0; (i = sin.find("\\r", i)) != std::string::npos;) sin.replace(i, 2, "\r");
    for (size_t i = 0; (i = sin.find("\\n", i)) != std::string::npos;) sin.replace(i, 2, "\n");

    top->clk = 0; top->live = 0; top->rc_low = 1; top->sw_closed = sw; top->sin = 1;
    top->eval();
    int ob = -1;
    long halted = 0, cont = 0, t;
    // serial out (SOUT -> host) and in (host -> SIN), both 8N1
    long rx_start = -1;
    int rx_byte = 0;
    size_t tx_i = 0;
    long tx_t0 = -1;
    int last_sout = 1;
    for (t = 0; t < max_ticks; t++) {
        top->live = t >= live_at;
        top->rc_low = t < reset_until;
        // host -> SIN: start after reset plus 0.5 s of machine time, one
        // character every 12 bit times
        if (!sin.empty() && tx_i < sin.size()) {
            if (tx_t0 < 0 && t > reset_until + CLK_HZ / 2) tx_t0 = t;
            if (tx_t0 >= 0) {
                long k = (t - tx_t0) / BIT;
                int c = (unsigned char)sin[tx_i];
                if (c == '~') {                 // '~' = two seconds of idle line
                    top->sin = 1;
                    if (t - tx_t0 >= 2 * CLK_HZ) { tx_i++; tx_t0 = t; gap_bits = 12; }
                } else {
                    top->sin = k == 0 ? 0 : (k <= 8 ? (c >> (k - 1)) & 1 : 1);
                    if (k >= gap_bits) { tx_i++; tx_t0 = t; }
                }
            }
        }
        if (sin2_at >= 0 && t >= sin2_at && tx_i >= sin.size()) {
            if (sin.size() == tx_i && t == sin2_at) { sin += sin2; tx_t0 = t; gap_bits = gap2_bits; }
        }
        top->clk = 1; top->eval();
        top->clk = 0; top->eval();
        if (top->contention) cont++;
        if (top->ob != ob) { ob = top->ob; printf("OB %02x tick=%ld\n", ob, t); fflush(stdout); }
        int so = top->sout;
        if (rx_start < 0) { if (last_sout && !so) rx_start = t; }
        else {
            long k = (t - rx_start - BIT / 2) / BIT, r = (t - rx_start - BIT / 2) % BIT;
            if (r == 0 && k >= 1 && k <= 8) rx_byte |= so << (k - 1);
            if (r == 0 && k == 9) {
                printf("SOUT %02x %c\n", rx_byte, rx_byte >= 32 && rx_byte < 127 ? rx_byte : '.');
                fflush(stdout);
                rx_byte = 0; rx_start = -1;
            }
        }
        last_sout = so;
        if (t > reset_until && top->halt) { if (++halted >= halt_ticks) break; }
        else halted = 0;
    }
    printf("%s OB=%02x ticks=%ld contention=%ld\n", t < max_ticks ? "HALT" : "TIMEOUT",
           ob & 0xFF, t, cont);
    delete top;
    return 0;
}
