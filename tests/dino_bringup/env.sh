# source me:  source env.sh
# /dev/cu.* (call-out), NOT /dev/tty.* (dial-in). Opening a tty.* device
# BLOCKS waiting for carrier detect, so `cat` hangs in open() before reading
# a byte and ctrl-c gets echoed instead of delivered. screen survives it by
# setting CLOCAL itself; nothing else does. Learned on the bench 2026-07-30.
export DINO_RIG_PORT="${DINO_RIG_PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
build()   { make PORT="$DINO_RIG_PORT"; }
flash()   { make PORT="$DINO_RIG_PORT" flash; }
monitor() { screen "$DINO_RIG_PORT" 115200; }   # exit: ctrl-a k

# ---- capturing a bench run ----------------------------------------------
# `monitor | tee file` DOES NOT WORK and fails silently: screen needs a tty,
# so the pipe leaves you a 0-byte file and no output. Use one of these.

# Interactive AND logged. `script` hands screen a pty, so screen is happy.
# Keeps terminal escape codes — fine to read, noisy to diff or paste.
#   monitorlog block1.log
monitorlog() { script -q "${1:-bench.log}" screen "$DINO_RIG_PORT" 115200; }

# Clean ASCII capture of one scripted run, no screen involved. This is the
# one to use for sharing a failure: no escape codes, nothing to strip.
#   capture block1.log run block1
# Guided tests still work — block1.seq prompts ARM and waits on the RESET
# LINE, not on the keyboard. For tests that want a y/n answer (io.leds,
# io.switches), use monitorlog instead; capture cannot type back.
capture() {
    local out="$1"; shift
    [ -n "$out" ] || { echo "usage: capture <file> <shell command...>"; return 2; }
    [ -e "$DINO_RIG_PORT" ] || { echo "no rig at $DINO_RIG_PORT"; return 1; }
    # clocal: ignore modem control lines, belt-and-braces alongside cu.*
    stty -f "$DINO_RIG_PORT" 115200 raw -echo clocal || return 1
    # opening the port resets the Mega, so wait out the boot before typing
    ( sleep 2; printf '%s\r' "$*" > "$DINO_RIG_PORT" ) &
    local typer=$!
    echo "capturing '$*' -> $out   (ctrl-c when the run finishes)"
    # trap so ctrl-c always tears down the helper, never orphans it
    trap 'kill $typer 2>/dev/null; trap - INT; stty sane' INT
    cat "$DINO_RIG_PORT" | tee "$out"
    trap - INT
    kill $typer 2>/dev/null
}
