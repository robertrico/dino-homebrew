#!/usr/bin/env python3
"""Studio renders of the DINO case: the whole box (no print seams), lid on,
the brand embossed, OB LEDs dressed as 5 mm reds showing a byte.

    ~/.venvs/dino-cad/bin/python docs/notes/case_render.py [--byte 0xB4]
                                    [--samples 256] [--out case/gen/render]
    make case-render

Step 1 (here, build123d): meshes to <out>/mesh/*.stl in case mm.
Step 2 (Blender, Cycles): case_render_blender.py lights and shoots them,
with the Rev 1.0 board (KiCad glTF, case/gen/board.glb, exported once) on
its standoffs. Views: hero, front (1.5x resolution), rear, open (lid off).
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import case_gen as cg                                 # noqa: E402

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
REPO = os.path.dirname(os.path.dirname(HERE))

# brand colours (docs/brand/build.py)
COLOURS = {"case": "#D8CCAA", "orange": "#E35F1A", "grey": "#4A3F37", "black": "#16130F"}


def export_meshes(L, mesh_dir):
    from build123d import export_stl
    os.makedirs(mesh_dir, exist_ok=True)
    parts = {"tray": cg.build_tray(L), "lid": cg.lid_installed(L, cg.build_lid(L))}
    for name, solid in cg.build_logo(L).items():
        parts[f"logo_{name}"] = solid
    for name, solid in parts.items():
        export_stl(solid, os.path.join(mesh_dir, name + ".stl"),
                   tolerance=0.02, angular_tolerance=0.1)
    return sorted(parts)


def scene_json(L, byte):
    leds = [c for c in L["cutouts"] if c["kind"] == "led"]
    x0, y0, x1, y1 = L["bbox"]
    return {
        "colours": COLOURS,
        "bbox": [x0, y0, 0.0, x1, y1, L["z"]["interior_top"] + cg.LID_T],
        "panel_x": L["front"]["panel_x"], "wall": cg.WALL, "led_d": cg.LED_D,
        "leds": [{"ref": c["ref"], "y": c["y"], "z": (c["z0"] + c["z1"]) / 2,
                  "on": bool(byte >> int(c["ref"][2:]) & 1)} for c in leds],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--byte", default="0xB4", help="what OB shows (default 0xB4, isa's pass)")
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--out", default=os.path.join(REPO, "case", "gen", "render"))
    ap.add_argument("--views", default="hero,front,rear,open")
    ap.add_argument("--no-board", action="store_true", help="leave the PCB out")
    ap.add_argument("--scale", type=int, default=100, help="resolution %% (drafts: 33)")
    ap.add_argument("--reuse", action="store_true", help="keep the meshes from the last run")
    a = ap.parse_args(argv)
    L = cg.layout("plain", "atx")
    mesh_dir = os.path.join(a.out, "mesh")
    names = (sorted(f[:-4] for f in os.listdir(mesh_dir) if f.endswith(".stl"))
             if a.reuse else export_meshes(L, mesh_dir))
    scene = scene_json(L, int(a.byte, 0))
    scene.update(meshes={n: os.path.join(mesh_dir, n + ".stl") for n in names},
                 out=a.out, samples=a.samples, scale=a.scale, views=a.views.split(","))
    board = os.path.join(REPO, "case", "gen", "board.glb")
    if not a.no_board:
        if not os.path.exists(board):           # KiCad's glTF keeps its colours
            subprocess.run([KICAD_CLI, "pcb", "export", "glb", "--subst-models", "--force",
                            "--include-tracks", "--include-pads", "--include-zones",
                            "--include-silkscreen", "--include-soldermask", "-o", board,
                            os.path.join(REPO, "dino_v0_0_2", "dino_v0_0_2.kicad_pcb")], check=True)
        # glb: KiCad x, -y, metres, z 0 at the board's underside -> on the standoffs
        scene["board"] = {"path": board, "at": [0.0, cg.BOARD_H / 1000, L["z"]["board_bot"] / 1000]}
    sj = os.path.join(a.out, "scene.json")
    json.dump(scene, open(sj, "w"), indent=1)
    subprocess.run([BLENDER, "-b", "--factory-startup", "-P",
                    os.path.join(HERE, "case_render_blender.py"), "--", sj], check=True)


if __name__ == "__main__":
    main()
