#!/usr/bin/env python3
"""dng2exr.py -- batch-convert camera raw files (DNG, CR2, CR3, NEF, ARW...)
to linear scene-referred EXRs ready for Nuke's HDRIMerge tool.

The conversion is deliberately "dumb": camera white balance, NO auto
brightness, NO tone curve, linear output (gamma 1.0), sRGB/Rec.709
primaries. That keeps each bracket's pixel values proportional to sensor
exposure, which is exactly what the merge math needs.

Requirements (regular system Python, not Nuke's):
    pip install rawpy numpy openexr

Usage:
    python dng2exr.py /path/to/bracket_folder            # all raws in folder
    python dng2exr.py img1.dng img2.dng img3.dng         # explicit files
    python dng2exr.py folder -o /path/to/output_folder
"""

import os
import sys
import argparse

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"  # must precede cv2 import

import numpy as np
import rawpy

def write_exr(out, img):
    """img: float32 RGB, written as 16-bit half. Prefers the official
    OpenEXR lib; falls back to OpenCV 4.x (5.x wheels dropped EXR)."""
    try:
        import OpenEXR
        header = {"compression": OpenEXR.ZIP_COMPRESSION,
                  "type": OpenEXR.scanlineimage}
        with OpenEXR.File(header, {"RGB": img.astype(np.float16)}) as f:
            f.write(out)
        return
    except ImportError:
        pass
    import cv2
    ok = cv2.imwrite(out, img[:, :, ::-1],
                     [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF])
    if not ok:
        raise RuntimeError("cv2 could not write %s" % out)


RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".raf",
            ".rw2", ".pef", ".srw", ".3fr", ".iiq"}


# ACES AP0 (ACES2065-1) -> AP1 (ACEScg) matrix, both D60
AP0_TO_AP1 = [
    [ 1.4514393161, -0.2365107469, -0.2149285693],
    [-0.0765537734,  1.1762296998, -0.0996759264],
    [ 0.0083161484, -0.0060324498,  0.9977163014],
]

def _libraw_colorspace(name):
    if name in ("acescg", "aces2065"):
        return rawpy.ColorSpace.ACES     # AP0 primaries from LibRaw
    return rawpy.ColorSpace.sRGB

def baseline_ev(path):
    """DNG BaselineExposure tag (EV). 0.0 if absent or exifread missing."""
    try:
        import exifread
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False)
        for key in ("Image BaselineExposure", "EXIF BaselineExposure"):
            if key in tags:
                v = tags[key].values[0]
                if hasattr(v, "num"):
                    return float(v.num) / float(v.den or 1)
                return float(v)
    except Exception:
        pass
    return 0.0

def convert(path, out_dir, gain=1.0, colorspace="acescg"):
    out = os.path.join(
        out_dir, os.path.splitext(os.path.basename(path))[0] + ".exr")
    with rawpy.imread(path) as raw:
        opts = dict(
            gamma=(1.0, 1.0),
            no_auto_bright=True,
            use_camera_wb=True,
            output_bps=16,
            output_color=_libraw_colorspace(colorspace),
            highlight_mode=rawpy.HighlightMode.Clip,
            # static white level: identical scaling for every frame of a
            # bracket, protecting the exposure ratios the merge needs
            adjust_maximum_thr=0.0,
        )
        try:
            # DHT: cleaner than the default AHD, free in mainline LibRaw
            opts["demosaic_algorithm"] = rawpy.DemosaicAlgorithm.DHT
        except AttributeError:
            pass
        rgb16 = raw.postprocess(**opts)
    img = rgb16.astype(np.float32) * (gain / 65535.0)
    if colorspace == "acescg":
        m = np.array(AP0_TO_AP1, dtype=np.float32)
        img = img.reshape(-1, 3).dot(m.T).reshape(img.shape)
    write_exr(out, img)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+",
                    help="raw files, or a single folder of raws")
    ap.add_argument("-o", "--out", default=None,
                    help="output folder (default: '<input>/exr')")
    ap.add_argument("--baseline", action="store_true",
                    help="apply DNG BaselineExposure tag "
                         "(matches Adobe brightness)")
    ap.add_argument("--colorspace", default="acescg",
                    choices=["acescg", "aces2065", "srgb"],
                    help="output primaries (default: ACEScg)")
    args = ap.parse_args()

    files = []
    for item in args.inputs:
        if os.path.isdir(item):
            files += sorted(
                os.path.join(item, f) for f in os.listdir(item)
                if os.path.splitext(f)[1].lower() in RAW_EXTS)
        elif os.path.splitext(item)[1].lower() in RAW_EXTS:
            files.append(item)
        else:
            print("Skipping (not a raw file): %s" % item)

    if not files:
        sys.exit("No raw files found.")

    out_dir = args.out or os.path.join(os.path.dirname(files[0]), "exr")
    os.makedirs(out_dir, exist_ok=True)

    for i, f in enumerate(files, 1):
        print("[%d/%d] %s" % (i, len(files), os.path.basename(f)), end=" ", flush=True)
        gain = 1.0
        if args.baseline:
            ev = baseline_ev(f)
            gain = 2.0 ** ev
            if ev:
                print("(baseline %+.2f EV) " % ev, end="",
                      flush=True)
        print("-> %s" % convert(f, out_dir, gain,
                                args.colorspace), flush=True)
    print("Done. %d EXRs in %s" % (len(files), out_dir))


if __name__ == "__main__":
    main()
