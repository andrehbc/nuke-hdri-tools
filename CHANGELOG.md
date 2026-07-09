# Changelog

## v2.7
- ACES-native transcodes: output colorspace option (ACEScg default,
  ACES2065-1, linear Rec.709), AP0->AP1 conversion, OCIO-tagged Reads
- adjust_maximum_thr=0: static white level so every frame of a bracket
  gets identical scaling (protects merge exposure ratios)
- DHT demosaic (cleaner than LibRaw's default AHD)

## v2.6
- Optional DNG BaselineExposure gain (matches Adobe brightness)

## v2.5
- Fixed transcoder output parsing (progress bar, Read/HDRIMerge
  auto-build after conversion)

## v2.4
- EXR writing via official OpenEXR lib (OpenCV 5 dropped its EXR codec)

## v2.3
- Expand ~ in python interpreter and output folder paths

## v2.2
- dng2exr_ui: transcoder panel inside Nuke (external-process transcodes,
  progress/log, dependency check, auto Reads + HDRIMerge build)

## v2.0
- Node-first workflow: create HDRIMerge, connect inputs, click Generate
- Self-contained Generate button (works in saved scripts anywhere)
- MyTools-compatible run() entry point

## v1.0
- Initial HDRI merge tool + command-line DNG converter
