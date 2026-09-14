# pcb_tools — the placer scripts from the 2026-09-12 layout session

Promoted verbatim from a session scratchpad on 2026-09-14 so the DMA/INT
re-shuffle has them. **Throwaway quality: no tests, absolute paths,
constants hard-coded for the 77-DIP / 14-column / 6-row board.** Read
`.git/sdd/PCB_LAYOUT.md` RESULTS R2 and `.git/sdd/TO_PCB.md` (volume
checkout) before running any of them. They only READ `.kicad_pcb`;
placements are applied through Konnect `set_component_placements`.

    anneal.py  <out.json> [seed]   simulated annealing over DIP cell
                                   assignment; cost = HPWL with CLK x6,
                                   ~CLK x4, CLK_B x6, Y1->U20 x6, RC x5.
                                   `ROWH`, `cells`, `chips==77` assert and
                                   the fixed-part table need editing for
                                   a board with U80-U99 added.
    hpwl.py    <pcb> [n]           per-net HPWL of the SAVED board, worst n
    report.py  <placements.json>   CLK/RST/PC6 spans + courtyard overlaps
                                   for a placements file before applying
    place_sheetrows.py             the FIRST placer (sheet rows). Superseded
                                   by anneal.py; kept for the cap-pairing
                                   and front-panel geometry it encodes.

Pipeline: anneal -> report -> Konnect set_component_placements ->
score_placement -> docs/notes/test_pcb_envelope.py -> pcbnew DSN export
-> Freerouting -> KiCad SES import -> hairpin sweep -> pours -> DRC.
