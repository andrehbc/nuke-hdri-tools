# dng2exr_ui.py -- DNG/raw -> linear EXR transcoder panel for Nuke.
#
# Install through the MyTools Tool Manager (it exposes run()).
# The panel is only a frontend: transcodes run in an EXTERNAL Python
# process (which needs rawpy/numpy/opencv installed), so Nuke never
# blocks and needs no extra libraries. The worker script is embedded
# here and written to a temp file at launch -- single-file install.
#
# Requirements on the SYSTEM python (not Nuke's):
#     pip install rawpy numpy openexr

import os
import re
import tempfile

import nuke

try:
    from PySide6 import QtWidgets, QtCore
except ImportError:
    from PySide2 import QtWidgets, QtCore

__version__ = "1.0.0"

RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".raf",
            ".rw2", ".pef", ".srw", ".3fr", ".iiq"}
FILE_FILTER = ("Camera raw (*" + " *".join(sorted(RAW_EXTS)) +
               ");;All files (*)")

# ---------------------------------------------------------------------------
# Embedded worker (runs in the external python; identical to dng2exr.py)
# ---------------------------------------------------------------------------
WORKER_SRC = r'''
import os, sys, argparse
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
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
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--baseline", action="store_true",
                    help="apply DNG BaselineExposure tag "
                         "(matches Adobe brightness)")
    ap.add_argument("--colorspace", default="acescg",
                    choices=["acescg", "aces2065", "srgb"],
                    help="output primaries (default: ACEScg)")
    args = ap.parse_args()
    files = list(args.inputs)
    out_dir = args.out or os.path.join(os.path.dirname(files[0]), "exr")
    os.makedirs(out_dir, exist_ok=True)
    for i, f in enumerate(files, 1):
        print("[%d/%d] %s" % (i, len(files), os.path.basename(f)),
              end=" ", flush=True)
        gain = 1.0
        if args.baseline:
            ev = baseline_ev(f)
            gain = 2.0 ** ev
            if ev:
                print("(baseline %+.2f EV) " % ev, end="",
                      flush=True)
        print("-> %s" % convert(f, out_dir, gain,
                                args.colorspace), flush=True)
    print("DONE %d" % len(files), flush=True)

if __name__ == "__main__":
    main()
'''

_PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")
_OUTPUT_RE = re.compile(r"-> (.+\.exr)\s*$")


def _nuke_main_window():
    app = QtWidgets.QApplication.instance()
    for w in app.topLevelWidgets():
        if w.inherits("QMainWindow") and "Nuke" in w.windowTitle():
            return w
    return None


class Dng2ExrPanel(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super(Dng2ExrPanel, self).__init__(parent)
        self.setWindowTitle("DNG > EXR transcoder  v%s" % __version__)
        self.setMinimumSize(620, 520)
        self.setWindowFlags(self.windowFlags()
                            | QtCore.Qt.WindowMinimizeButtonHint)
        self._settings = QtCore.QSettings("MyTools", "dng2exr_ui")
        self._proc = None
        self._worker_path = None
        self._outputs = []
        self._buf = ""
        self._build_ui()

    # ---- UI --------------------------------------------------------------
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)

        # file list + buttons
        lay.addWidget(QtWidgets.QLabel("Raw files to convert:"))
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.file_list, 1)

        row = QtWidgets.QHBoxLayout()
        for label, slot in (("Add Files...", self.add_files),
                            ("Add Folder...", self.add_folder),
                            ("Remove Selected", self.remove_selected),
                            ("Clear", self.file_list.clear)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

        # output folder
        out_row = QtWidgets.QHBoxLayout()
        self.sub_check = QtWidgets.QCheckBox(
            "Write to 'exr' subfolder next to the sources")
        self.sub_check.setChecked(True)
        self.sub_check.toggled.connect(self._toggle_out)
        lay.addWidget(self.sub_check)
        self.out_edit = QtWidgets.QLineEdit(
            self._settings.value("out_dir", ""))
        self.out_edit.setPlaceholderText("Custom output folder")
        self.out_edit.setEnabled(False)
        out_btn = QtWidgets.QPushButton("Browse...")
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(out_btn)
        lay.addLayout(out_row)

        # python interpreter + deps
        py_row = QtWidgets.QHBoxLayout()
        py_row.addWidget(QtWidgets.QLabel("System python:"))
        self.py_edit = QtWidgets.QLineEdit(
            self._settings.value("python_exe", "python3"))
        deps_btn = QtWidgets.QPushButton("Check dependencies")
        deps_btn.clicked.connect(self.check_deps)
        py_row.addWidget(self.py_edit, 1)
        py_row.addWidget(deps_btn)
        lay.addLayout(py_row)

        cs_row = QtWidgets.QHBoxLayout()
        cs_row.addWidget(QtWidgets.QLabel("Output colorspace:"))
        self.cs_combo = QtWidgets.QComboBox()
        self.cs_combo.addItem("ACEScg (AP1) - Nuke ACES working space",
                              "acescg")
        self.cs_combo.addItem("ACES2065-1 (AP0) - archival/interchange",
                              "aces2065")
        self.cs_combo.addItem("Linear sRGB/Rec.709 - non-ACES pipelines",
                              "srgb")
        idx = self.cs_combo.findData(
            self._settings.value("colorspace", "acescg"))
        self.cs_combo.setCurrentIndex(max(idx, 0))
        cs_row.addWidget(self.cs_combo, 1)
        lay.addLayout(cs_row)

        self.baseline_check = QtWidgets.QCheckBox(
            "Apply DNG BaselineExposure (match Adobe brightness)")
        self.baseline_check.setChecked(True)
        self.baseline_check.setToolTip(
            "Reads the BaselineExposure tag from each DNG and applies it "
            "as a uniform gain. Identical across a bracket, so merge "
            "ratios stay intact. Needs 'exifread' in the system python; "
            "silently skipped if missing.")
        lay.addWidget(self.baseline_check)

        # nuke integration
        self.reads_check = QtWidgets.QCheckBox(
            "Create Read nodes for the EXRs when done")
        self.reads_check.setChecked(True)
        self.merge_check = QtWidgets.QCheckBox(
            "...and build an HDRIMerge from them")
        self.merge_check.setChecked(False)
        lay.addWidget(self.reads_check)
        lay.addWidget(self.merge_check)

        # progress + log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        lay.addWidget(self.progress)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        lay.addWidget(self.log, 1)

        # run / cancel
        run_row = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Convert")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        run_row.addStretch(1)
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.cancel_btn)
        lay.addLayout(run_row)

    def _log(self, msg):
        self.log.appendPlainText(msg)

    def _toggle_out(self, checked):
        self.out_edit.setEnabled(not checked)

    def _browse_out(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Output folder", self.out_edit.text() or os.path.expanduser("~"))
        if d:
            self.out_edit.setText(d)
            self.sub_check.setChecked(False)

    # ---- file list ---------------------------------------------------------
    def _existing(self):
        return {self.file_list.item(i).text()
                for i in range(self.file_list.count())}

    def add_files(self):
        start = self._settings.value("last_dir", os.path.expanduser("~"))
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select raw files", start, FILE_FILTER)
        self._add(files)

    def add_folder(self):
        start = self._settings.value("last_dir", os.path.expanduser("~"))
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select folder of raw files", start)
        if d:
            self._add(sorted(
                os.path.join(d, f) for f in os.listdir(d)
                if os.path.splitext(f)[1].lower() in RAW_EXTS))

    def _add(self, files):
        have = self._existing()
        added = 0
        for f in files:
            if f and f not in have and \
                    os.path.splitext(f)[1].lower() in RAW_EXTS:
                self.file_list.addItem(f)
                added += 1
        if files:
            self._settings.setValue("last_dir", os.path.dirname(files[0]))
        if added:
            self._log("Added %d file(s)." % added)

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    # ---- dependency check ---------------------------------------------------
    def check_deps(self):
        import subprocess
        exe = os.path.expanduser(self.py_edit.text().strip() or "python3")
        try:
            r = subprocess.run(
                [exe, "-c",
                 "import rawpy, numpy\n"
                 "try:\n import OpenEXR\n"
                 "except ImportError:\n import cv2\n"
                 "print('deps-ok')"],
                capture_output=True, text=True, timeout=30)
            ok = "deps-ok" in (r.stdout or "")
        except Exception as e:
            ok, r = False, None
            self._log("Could not run '%s': %s" % (exe, e))
        if ok:
            QtWidgets.QMessageBox.information(
                self, "Dependencies", "All good: rawpy, numpy and an EXR writer found.")
        else:
            if r is not None and r.stderr:
                self._log(r.stderr.strip())
            QtWidgets.QMessageBox.warning(
                self, "Dependencies",
                "Missing libraries in '%s'.\n\nInstall with:\n"
                "pip install rawpy numpy openexr exifread"
                % exe)

    # ---- transcode ------------------------------------------------------------
    def start(self):
        files = [self.file_list.item(i).text()
                 for i in range(self.file_list.count())]
        if not files:
            QtWidgets.QMessageBox.information(
                self, "DNG > EXR", "Add some raw files first.")
            return

        exe = os.path.expanduser(self.py_edit.text().strip() or "python3")
        self._settings.setValue("python_exe", self.py_edit.text().strip())

        args = list(files)
        cs = self.cs_combo.currentData()
        self._settings.setValue("colorspace", cs)
        args += ["--colorspace", cs]
        if self.baseline_check.isChecked():
            args.append("--baseline")
        if not self.sub_check.isChecked():
            out = os.path.expanduser(self.out_edit.text().strip())
            if not out:
                QtWidgets.QMessageBox.warning(
                    self, "DNG > EXR", "Pick a custom output folder or "
                    "re-enable the 'exr subfolder' option.")
                return
            self._settings.setValue("out_dir", out)
            args += ["-o", out]

        fd, self._worker_path = tempfile.mkstemp(
            suffix=".py", prefix="dng2exr_worker_")
        with os.fdopen(fd, "w") as fh:
            fh.write(WORKER_SRC)

        self._outputs = []
        self._buf = ""
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._log("Starting: %s (%d files)" % (exe, len(files)))

        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.start(exe, [self._worker_path] + args)

    def _on_output(self):
        data = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buf += data
        lines = self._buf.split("\n")
        self._buf = lines.pop()  # keep trailing partial line for next chunk
        for line in lines:
            self._handle_line(line)

    def _handle_line(self, line):
        line = line.rstrip()
        if not line:
            return
        self._log(line)
        m = _PROGRESS_RE.search(line)
        if m:
            self.progress.setValue(int(m.group(1)))
        m = _OUTPUT_RE.search(line)
        if m:
            self._outputs.append(m.group(1))

    def _on_finished(self, *fargs):
        if self._buf:
            self._handle_line(self._buf)
            self._buf = ""
        code = self._proc.exitCode() if self._proc else -1
        self._cleanup_worker()
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if code != 0:
            self._log("FAILED (exit code %s). See messages above -- "
                      "usually missing libraries; try 'Check "
                      "dependencies'." % code)
            return
        self._log("Finished: %d EXR(s) written." % len(self._outputs))
        if self.reads_check.isChecked() and self._outputs:
            self._create_reads()

    def cancel(self):
        if self._proc and self._proc.state() != QtCore.QProcess.NotRunning:
            self._proc.kill()
            self._log("Cancelled.")
        self._cleanup_worker()
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _cleanup_worker(self):
        if self._worker_path and os.path.exists(self._worker_path):
            try:
                os.remove(self._worker_path)
            except OSError:
                pass
        self._worker_path = None

    # ---- nuke integration -----------------------------------------------------
    def _create_reads(self):
        reads = []
        cs = self.cs_combo.currentData()
        tag_names = {
            "acescg": ["ACES - ACEScg", "ACEScg"],
            "aces2065": ["ACES - ACES2065-1", "ACES2065-1"],
            "srgb": ["Utility - Linear - Rec.709", "linear"],
        }.get(cs, [])
        for i, path in enumerate(sorted(self._outputs)):
            r = nuke.nodes.Read(file=path.replace(os.sep, "/"))
            r.setXYpos(i * 120, 0)
            for name in tag_names:
                try:
                    r["colorspace"].setValue(name)
                    break
                except Exception:
                    continue
            reads.append(r)
        self._log("Created %d Read node(s)." % len(reads))
        if self.merge_check.isChecked() and len(reads) >= 2:
            try:
                import hdri_merge
                g = hdri_merge.create_hdri_merge_node()
                for i, r in enumerate(reads[:9]):
                    g.setInput(i, r)
                g["generate"].execute()
                self._log("HDRIMerge built and generated -- set "
                          "'EV spacing' to your bracket step.")
            except Exception as e:
                self._log("Could not build HDRIMerge: %s" % e)


# ---------------------------------------------------------------------------
# MyTools entry point
# ---------------------------------------------------------------------------
_panel = None


def run():
    global _panel
    if _panel is None:
        _panel = Dng2ExrPanel(_nuke_main_window())
    _panel.show()
    _panel.raise_()
    _panel.activateWindow()
