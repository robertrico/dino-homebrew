# DINO — top-level Makefile. Source in, ROM image out, chip burned.
#
#     make assemble-hello        asm/hello.asm -> roms/PROG_hello.bin
#     make listing-hello         annotated listing, writes nothing
#     make list-asm              what can be assembled, straight off disk
#     make assemble-all          every asm/*.asm
#
#     make burn-prog-hello       re-assemble IF stale, then burn U24
#     make burn-real-u9          microcode, CW0-7
#     make list-prog             what can be burned, straight off disk
#     make id-rom                name whatever chip is in the socket
#
# The burn targets carry the SAME NAMES as tests/dino_bringup/Makefile on
# purpose. Two vocabularies for one action is how `make burn-prog-window` died
# at the bench with the chip already in the programmer -- a name that works in
# one tree and not the other is the same failure with extra steps.
#
# Rico burns. These targets are reachable from the root as of 2026-08-27
# (Rico's call: the machine is complete, every image is generated from a
# pinned source, and there is little left to clobber). Nothing here runs
# minipro without being asked by name.

PY   ?= python3
ASM   = docs/notes/asm.py
SRCS  = asm
ROMS  = roms
RIG   = tests/dino_bringup

# The image depends on more than its source. Opcodes, byte lengths and operand
# shapes are all read out of microcode_gen at assembly time -- so a microcode
# edit changes the bytes with the .asm untouched, and a rule keyed on the .asm
# alone would report "up to date" while holding a stale image. progrom_gen
# supplies build_image_from_bytes and the oracle.
ASMDEPS = $(ASM) docs/notes/microcode_gen.py docs/notes/progrom_gen.py

ASM_SRCS = $(wildcard $(SRCS)/*.asm)
ASM_TAGS = $(patsubst $(SRCS)/%.asm,%,$(ASM_SRCS))

# ---- assemble ----------------------------------------------------------
# ONE PATTERN RULE, NOT A HAND-WRITTEN LIST -- same reason burn-prog-% is one.
# A tag list is a step someone has to remember, and the one time it is not
# remembered is at the bench with the chip already in the programmer.
#
# --run comes BEFORE -o on purpose: the oracle prints the expected OB, and a
# coverage image with no expected value is a program with no answer key.
$(ROMS)/PROG_%.bin: $(SRCS)/%.asm $(ASMDEPS)
	$(PY) $(ASM) $< --run -o $@

# The guard is the point: a typo names itself and lists what IS available,
# instead of dying with make's "No rule to make target".
assemble-%:
	@test -f $(SRCS)/$*.asm || { \
	  echo "no such source: $(SRCS)/$*.asm"; \
	  echo "available:"; \
	  for t in $(ASM_TAGS); do echo "    $$t"; done; \
	  exit 1; }
	@$(MAKE) --no-print-directory $(ROMS)/PROG_$*.bin

listing-%:
	@test -f $(SRCS)/$*.asm || { \
	  echo "no such source: $(SRCS)/$*.asm"; \
	  echo "available:"; \
	  for t in $(ASM_TAGS); do echo "    $$t"; done; \
	  exit 1; }
	@$(PY) $(ASM) $(SRCS)/$*.asm --list

# What can be assembled right now, straight off disk. No list to fall stale.
list-asm:
	@for t in $(ASM_TAGS); do echo "$$t"; done

assemble-all: $(patsubst %,$(ROMS)/PROG_%.bin,$(ASM_TAGS))

# ---- burn --------------------------------------------------------------
# This is the ONE thing the root can do that $(RIG) cannot: an image with an
# .asm source is REBUILT before it is burned. $(RIG) burns whatever bytes are
# on disk, which is correct there and stale here -- the assembler reads its
# opcodes out of microcode_gen, so `make -C $(RIG) burn-prog-hello` after a
# microcode edit burns the OLD encoding without a word.
#
# Images with no .asm source (PROG_alu, PROG_suite, everything progrom_gen
# emits) pass straight through untouched. Regenerate those with gen-progrom.
burn-prog-%:
	@if test -f $(SRCS)/$*.asm; then \
	  $(MAKE) --no-print-directory $(ROMS)/PROG_$*.bin; \
	fi
	@test -f $(ROMS)/PROG_$*.bin || { \
	  echo "no such image: $(ROMS)/PROG_$*.bin"; \
	  echo "available:"; \
	  ls $(ROMS)/PROG_*.bin | sed 's|.*/PROG_||; s|\.bin$$||; s|^|    |'; \
	  exit 1; }
	$(MAKE) -C $(RIG) burn-prog-$*

# Microcode. No source-rebuild hook: microcode_gen writes U9/U15/U23 whole,
# and the CRCs are pinned as literals in test_microcode_gen.py so a reburn is
# always deliberate. Run gen-microcode and let the host test rule on it first.
burn-real-u9 burn-real-u15 burn-real-u23 burn-prog burn-prog-diag:
	$(MAKE) -C $(RIG) $@

list-prog read-prog id-rom verify-prog verify-prog-diag \
verify-real-u9 verify-real-u15 verify-real-u23:
	@$(MAKE) --no-print-directory -C $(RIG) $@

# ---- generate ----------------------------------------------------------
# The images that are NOT assembled: microcode, and the built-in program ROMs.
gen-microcode:
	$(PY) docs/notes/microcode_gen.py

gen-progrom:
	$(PY) docs/notes/progrom_gen.py

expected:
	@$(PY) docs/notes/progrom_gen.py --expected

test:
	$(PY) -m pytest docs/notes -q

.PHONY: list-asm assemble-all gen-microcode gen-progrom expected test \
        burn-real-u9 burn-real-u15 burn-real-u23 burn-prog burn-prog-diag \
        list-prog read-prog id-rom verify-prog verify-prog-diag \
        verify-real-u9 verify-real-u15 verify-real-u23
.PRECIOUS: $(ROMS)/PROG_%.bin
