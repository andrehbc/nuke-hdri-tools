# nuke-hdri-tools

Bracketed raw photos -> true scene-referred HDRI, entirely from Nuke.
Replaces the Photoshop "Merge to HDR" step with an ACES-native,
radiance-correct pipeline.

Two single-file tools, no external plugins:

| Tool | What it does |
|---|---|
| `dng2exr_ui.py` | Panel in Nuke that batch-transcodes DNG/CR2/CR3/NEF/ARW... to linear ACEScg EXRs in an external python process (UI stays live), then optionally creates Reads and a ready-made merge node |
| `hdri_merge.py` | Creates an **HDRIMerge** node: connect 2-9 bracketed frames, click *Generate HDRI*. Weighted radiance merge with live knobs |
| `dng2exr.py` | Same transcoder as a plain CLI for batch/farm use |

New to the tools? Read **TEAM_GUIDE.md** (1 page).

## Why not just Photoshop?

ACR bakes BaselineExposure and a tone curve into its output - fine for
stills, wrong for HDRI sources, since it distorts the exposure ratios
between brackets. These tools keep the conversion strictly linear
(consensus recipe: Poly Haven technical standards, ACES community) and
do the merge in float radiance space. Full background and sources in
`docs/RESEARCH_dng_to_exr.md`.

## Install

Requires Nuke 14-16 (PySide2/6 both handled).

**With a tool-manager menu:** add `hdri_merge.py` and `dng2exr_ui.py`;
both expose `run()`.

**Plain ~/.nuke:** copy both files into a folder on your plugin path
and add menu entries (sample in `extras/menu.py`):

    m = nuke.menu("Nodes").addMenu("HDRI")
    m.addCommand("HDRIMerge", "import hdri_merge; hdri_merge.run()")
    m.addCommand("DNG to EXR", "import dng2exr_ui; dng2exr_ui.run()")

**Transcoder environment** (system python, not Nuke's):

    python3 -m venv ~/venvs/dng2exr
    ~/venvs/dng2exr/bin/pip install rawpy numpy openexr exifread

Point the panel's *System python* field at the venv's python3 once.

## How the merge works

Each frame is divided by its relative exposure (2^EV) onto a common
radiance scale, then blended with per-pixel confidence weights that
reject near-clipped highlights and noise-floor shadows; the darkest
frame keeps its highlights and the brightest keeps its shadows, so
every scene value has a real measurement:

    HDR = sum(w_i * pixel_i * 2^-ev_i) / sum(w_i)

The Generate button's code is embedded in the node, so saved scripts
keep working on machines without the tools installed. Everything inside
the group is ordinary Nuke nodes - Ctrl+Enter to inspect.

## Transcode fidelity choices

- Strict linear: gamma (1,1), no auto-brightness, fixed camera WB
- `adjust_maximum_thr=0` - identical white-level scaling across a
  bracket (LibRaw's per-frame auto-max would corrupt exposure ratios)
- DHT demosaic, camera -> ACES AP0 matrix, AP0->AP1 for ACEScg output
- 16-bit half EXR (lossless vs 12-14 bit sensor data)
- Optional DNG BaselineExposure gain to match Adobe brightness
  (uniform across a bracket, merge-safe)

## Troubleshooting

- **"Missing libraries"** - *Check dependencies* button; make sure
  *System python* points at the venv (full path or ~).
- **EXR write fails** - `pip install openexr` in the venv (OpenCV 5
  dropped its EXR codec; the tool prefers OpenEXR).
- **Merged HDRI too dark/bright** - check *EV spacing* sign and value;
  *output exposure* knob for overall gain.
- **Menu entry does nothing** - the module must be importable by Nuke;
  check your tool manager copied it and restart.
