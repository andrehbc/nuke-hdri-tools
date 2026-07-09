# DNG -> EXR for HDRI: what "keeping all the data" actually requires

Research notes, July 2026. Focus: converting bracketed DNGs to linear EXR
for radiance-correct HDRI merging in Nuke.

## 1. Where data can actually be lost

**Bit depth -- mostly a red herring.** Sensor data is natively 10-16 bit
integer. LibRaw's 16-bit linear output holds a 12-bit sensor's data with
16x headroom: nothing is lost going 12-bit sensor -> 16-bit int -> half
EXR. Adobe's float pipeline is not "more data" from a single raw; float
only matters for intermediate math. A half-float EXR resolves ~11 bits
of mantissa at every exposure level, which exceeds sensor noise floors.

**White-level auto-adjustment -- the real correctness issue for HDRI.**
LibRaw ships "adjust_maximum" logic (default `adjust_maximum_thr=0.75`)
that rescales each file by the *measured* data maximum of that frame to
avoid magenta/"pink clouds" highlights. Consequence for brackets: frames
can receive slightly DIFFERENT scale factors (LibRaw forum reports ~25%
exposure jumps between similar files). That silently corrupts the
exposure ratios the merge depends on. Fix: `adjust_maximum_thr=0` so
every frame is scaled by the same static camera white level.
Trade-off: potential magenta cast in clipped highlights of a single
frame -- but our merge rejects near-clipped pixels by design, and the
darkest bracket should be unclipped anyway (Poly Haven's #1 rule).

**Highlight clipping.** ACR does highlight "recovery" (reconstructs 1-2
stops from partially-clipped channels). Good for single photos,
unnecessary and actually undesirable for HDRI: recovered highlights are
guesses, while the shorter bracket has the real measurement. Keep
`HighlightMode.Clip` + clip rejection in the merge.

**Gamut clipping at the color matrix.** Converting camera RGB to sRGB
primaries clips saturated colors (neon, LEDs, deep sky). Wider output
primaries (ProPhoto/XYZ/ACES) preserve them, at the cost of needing
matching colorspace tags on the Nuke Reads. This is the one place our
current sRGB-primaries output genuinely discards information -- usually
small, but real for colorful light sources. Worth exposing as an option.

**Tone curves -- the thing to avoid, and Adobe's default sin.** ACR
"without adjustments" still applies BaselineExposure, a default tone
curve and highlight rolloff. That's display-referred rendering baked
into pixels: it *breaks* the linear exposure relationships between
brackets. Every HDRI authority (Poly Haven technical standards, ACES
community) demands a fully linear conversion: no curve, no sharpening,
no auto-brightness, fixed WB. Our settings (gamma=(1,1),
no_auto_bright, camera WB) are exactly the consensus recipe. The
Photoshop EXR only *looks* like it has more information because it is
brighter and tone-mapped.

**BaselineExposure.** A per-model rendering *hint* (EV shift) so
different cameras render similarly -- not sensor data. Applying it is a
uniform gain, identical across a bracket, so it is merge-safe; it is
cosmetic, not fidelity. (Already optional in our tool.)

## 2. Demosaic quality

Ranking from VFX comparison testing (jedypod/debayer):
RCD > DCB > AMaZE > DHT > AAHD > AHD > VNG.
rawpy/LibRaw defaults to AHD; DHT, AAHD and DCB are available in
mainline LibRaw at no cost -- a free quality bump (finer detail, fewer
zipper/maze artifacts). RCD/AMaZE require RawTherapee as the engine.
For 360 HDRIs viewed as environment light, demosaic differences are
minor; they matter if the HDRI doubles as a backplate.

## 3. Tool landscape

| Tool | Pipeline | Verdict for us |
|---|---|---|
| rawpy/LibRaw (current) | 16-bit int, scriptable, no deps beyond pip | Correct choice; needs adjust_maximum_thr=0, optionally better demosaic + wide-gamut option |
| oiiotool (OpenImageIO) | LibRaw underneath, same 16-bit ceiling | No fidelity gain over rawpy; extra dependency |
| rawtoaces (ASWF) | Float, ACES2065-1, best colorimetric pedigree, DNG metadata path | Gold standard for ACES shops; heavier install, ACES-only output |
| RawTherapee CLI | True float output, RCD/AMaZE demosaic, CA removal; needs neutral pp3 | Poly Haven's recommendation; best quality ceiling; external binary to manage |
| darktable-cli | Float EXR, scene-referred, xmp-driven | Capable but config-heavy |
| Photoshop/ACR | Float but tone-curved by default | Not neutral; avoid for HDRI sources |

## 4. Recommendations (priority order)

1. **`adjust_maximum_thr=0`** -- consistency fix; directly protects
   merge ratios. Do this regardless of anything else.
2. **Demosaic option, default DHT** (or AAHD) -- free quality gain.
3. **Primaries option** -- keep linear sRGB/Rec.709 default (matches
   your Nuke working space); add ACES/ProPhoto choice for saturated
   light sources or future ACES work, with a note on setting the Read
   colorspace.
4. Keep: gamma=(1,1), no_auto_bright, camera WB, HighlightMode.Clip,
   half EXR, optional BaselineExposure. These already match community
   best practice.
5. Later, if backplate-grade demosaic is ever needed: RawTherapee
   engine mode (like jedypod/debayer's multi-engine design).

## Sources

- Poly Haven, "How to Create High Quality HDR Environments" + HDRI
  technical standards (linear, no tone curve, unclipped, RawTherapee):
  https://blog.polyhaven.com/how-to-create-high-quality-hdri/ ,
  https://docs.polyhaven.com/en/technical-standards/hdris
- LibRaw docs/forums on adjust_maximum & pink clouds, processing order:
  https://www.libraw.org/node/2605 , https://www.libraw.org/node/2514 ,
  https://www.libraw.org/node/2824
- rawpy Params documentation:
  https://letmaik.github.io/rawpy/api/rawpy.Params.html
- jedypod/debayer (engines, demosaic ranking, raw->scene-linear exposure):
  https://github.com/jedypod/debayer
- rawtoaces (ASWF): https://github.com/AcademySoftwareFoundation/rawtoaces
- Adobe DNG Specification 1.7.1 (BaselineExposure semantics):
  https://helpx.adobe.com/content/dam/help/en/camera-raw/digital-negative/jcr_content/root/content/flex/items/position/position-par/download_section_733958301/download-1/DNG_Spec_1_7_1_0.pdf
- ACEScentral, "Converting DNG still images to ACES primaries":
  https://community.acescentral.com/t/converting-dng-still-images-to-aces-primaries/4243
