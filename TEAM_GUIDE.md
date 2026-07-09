# HDRI Tools - Artist Quick Guide

Make a true HDRI from bracketed DNGs without leaving Nuke.
Two tools: **dng2exr_ui** (transcode panel) and **hdri_merge** (merge node).

## One-time setup (5 min)

1. Copy `hdri_merge.py` and `dng2exr_ui.py` from this repo into your
   `~/.nuke` folder.
2. Add these lines to `~/.nuke/menu.py` (create the file if it doesn't
   exist), then restart Nuke - you'll get an **HDRI** menu in the Nodes
   toolbar:

       m = nuke.menu("Nodes").addMenu("HDRI")
       m.addCommand("HDRIMerge", "import hdri_merge; hdri_merge.run()")
       m.addCommand("DNG to EXR", "import dng2exr_ui; dng2exr_ui.run()")

3. Terminal (transcoder needs a python env with raw libs):

       python3 -m venv ~/venvs/dng2exr
       ~/venvs/dng2exr/bin/pip install rawpy numpy openexr exifread

4. First launch of **DNG to EXR**: set *System python* to
   `~/venvs/dng2exr/bin/python3`, hit *Check dependencies*. Saved
   after that.

## Everyday workflow

1. **HDRI > DNG to EXR** - Add Files or Add Folder (your bracketed
   DNGs), leave *ACEScg* selected, tick both "Create Read nodes" and
   "build an HDRIMerge", hit **Convert**.
2. When it finishes you have Reads + a generated **HDRIMerge** node.
3. On the node, set **EV spacing** = your bracket step (e.g. 2 if you
   shot 2 stops apart; negative if files go bright to dark).
4. Write out: EXR, 16-bit half. Reads are already tagged ACES - ACEScg.

Already have EXRs? Skip the panel: **HDRI > HDRIMerge** creates an
empty node - connect up to 9 frames, click **Generate HDRI**.

## Checks & gotchas

- Verify it's really HDR: sample the sun/lights - values should be way
  above 1.0. If not, your darkest bracket was clipped when shooting.
- Wrong EV spacing shows up instantly as wrong brightness - just fix
  the knob, no need to regenerate.
- Shoot tips: tripod, manual everything, bracket with SHUTTER only,
  fixed WB, keep bracketing down until the brightest light stops
  clipping.
- Leave the two "keep" checkboxes on the node ON (they guarantee the
  sun and deep shadows always have a valid source frame).
- The tools never render inside Nuke's python - transcodes run in the
  venv, so Nuke stays responsive.

Questions -> Andre.
