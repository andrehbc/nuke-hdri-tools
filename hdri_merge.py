# hdri_merge.py -- HDRIMerge node for Nuke (v2, node-first workflow)
#
# Usage:
#   1. Create the node (from your tools menu, or run
#      hdri_merge.create_hdri_merge_node() in the Script Editor).
#   2. Connect your bracketed frames to the input arrows (up to 9).
#   3. Click "Generate HDRI" on the node.
#
# The Generate button's code is EMBEDDED in the node, so the node keeps
# working in saved scripts even on machines that don't have this file.
#
# Merge math: each frame is divided by its relative exposure (2^EV) to a
# common radiance scale, then blended with confidence weights that reject
# near-clipped highlights and noisy shadows:
#     HDR = sum(w_i * pixel_i * 2^-ev_i) / sum(w_i)

import nuke

__version__ = "2.0.0"

MAX_INPUTS = 9

# ---------------------------------------------------------------------------
# Code embedded into the "Generate HDRI" button (fully self-contained).
# ---------------------------------------------------------------------------
GENERATE_CMD = r"""
import nuke, traceback

def _hdri_generate():
    node = nuke.thisNode()

    cnx = [i for i in range(node.maximumInputs()) if node.input(i)]
    if len(cnx) < 2:
        nuke.message('Connect at least 2 bracketed frames to the input '
                     'arrows, then click Generate again.')
        return

    # Order frames: by filename if every source is a Read (recommended),
    # otherwise by input arrow number.
    order = list(cnx)
    if node['sort_by_filename'].value() and all(
            node.input(i).Class() == 'Read' for i in cnx):
        order.sort(key=lambda i: node.input(i)['file'].value())

    N = len(order)

    with node:
        # wipe previous tree, keep the Input/Output stubs
        for nd in nuke.allNodes():
            if nd.Class() not in ('Input', 'Output'):
                nuke.delete(nd)
        inputs_by_num = {int(nd['number'].value()): nd
                         for nd in nuke.allNodes('Input')}

        tops = []
        for rank, idx in enumerate(order):
            src = inputs_by_num[idx]
            x = rank * 220

            w = nuke.nodes.Expression(name='Weight%d' % (rank + 1),
                                      inputs=[src])
            w['temp_name0'].setValue('zmax')
            w['temp_expr0'].setValue('max(r, max(g, b))')
            w['temp_name1'].setValue('whi')
            w['temp_expr1'].setValue(
                'clamp((parent.hi_end - zmax) / '
                'max(parent.hi_end - parent.hi_start, 0.0001), 0, 1)')
            w['temp_name2'].setValue('wlo')
            w['temp_expr2'].setValue(
                'clamp((zmax - parent.lo_start) / '
                'max(parent.lo_end - parent.lo_start, 0.0001), 0, 1)')
            hi, lo = 'whi', 'wlo'
            if rank == 0:
                hi = ('((parent.keep_extreme_highlights && '
                      'parent.ev_spacing >= 0) ? 1 : whi)')
                lo = ('((parent.keep_extreme_shadows && '
                      'parent.ev_spacing < 0) ? 1 : wlo)')
            if rank == N - 1:
                hi = ('((parent.keep_extreme_highlights && '
                      'parent.ev_spacing < 0) ? 1 : whi)')
                lo = ('((parent.keep_extreme_shadows && '
                      'parent.ev_spacing >= 0) ? 1 : wlo)')
            w['expr3'].setValue('(%s) * (%s)' % (hi, lo))
            w['label'].setValue('confidence -> alpha')
            w.setXYpos(x, 150)

            m = nuke.nodes.Multiply(name='Normalize%d' % (rank + 1),
                                    inputs=[w])
            m['channels'].setValue('rgb')
            m['value'].setExpression(
                'pow(2, -(%d - parent.ref_index) * parent.ev_spacing)'
                % rank)
            m['label'].setValue('to reference exposure')
            m.setXYpos(x, 230)

            p = nuke.nodes.Premult(name='ApplyWeight%d' % (rank + 1),
                                   inputs=[m])
            p.setXYpos(x, 310)
            tops.append(p)

        acc = tops[0]
        for k, b in enumerate(tops[1:], 1):
            mg = nuke.nodes.Merge2(name='Sum%d' % k, inputs=[acc, b])
            mg['operation'].setValue('plus')
            mg['output'].setValue('rgba')
            mg.setXYpos(k * 220, 390)
            acc = mg

        norm = nuke.nodes.Expression(name='DivideByWeights', inputs=[acc])
        norm['expr0'].setValue('a > 1e-6 ? r / a : r')
        norm['expr1'].setValue('a > 1e-6 ? g / a : g')
        norm['expr2'].setValue('a > 1e-6 ? b / a : b')
        norm['expr3'].setValue('1')
        norm['label'].setValue('HDR = sum(w*rad) / sum(w)')
        norm.setXYpos((N - 1) * 220, 470)

        gain = nuke.nodes.Multiply(name='OutputExposure', inputs=[norm])
        gain['channels'].setValue('rgb')
        gain['value'].setExpression('pow(2, parent.exposure_offset)')
        gain.setXYpos((N - 1) * 220, 550)

        nuke.allNodes('Output')[0].setInput(0, gain)

    # keep the reference-frame knob inside the valid range
    if node['ref_index'].value() > N - 1:
        node['ref_index'].setValue((N - 1) / 2.0)
    node['label'].setValue(
        '%d frames | [value ev_spacing] EV steps' % N)

try:
    _hdri_generate()
except Exception:
    nuke.message('HDRIMerge error:\n\n' + traceback.format_exc())
"""


def create_hdri_merge_node():
    """Create an empty HDRIMerge node; user connects inputs and clicks
    Generate HDRI."""
    group = nuke.nodes.Group(name="HDRIMerge1")
    group["label"].setValue("connect brackets, click Generate")
    group["tile_color"].setValue(0xAD7F30FF)

    # ---- knobs -----------------------------------------------------------
    tab = nuke.Tab_Knob("hdri", "HDRI Merge")
    gen = nuke.PyScript_Knob("generate", " Generate HDRI ", GENERATE_CMD)
    gen.setTooltip("Scans the connected inputs and (re)builds the merge "
                   "tree inside this node. Re-click any time you "
                   "add/remove inputs.")
    sortk = nuke.Boolean_Knob("sort_by_filename", "sort inputs by filename")
    sortk.setValue(True)
    sortk.setFlag(nuke.STARTLINE)
    sortk.setTooltip("If all inputs are Read nodes, order frames by "
                     "filename instead of by input arrow number.")

    div0 = nuke.Text_Knob("ediv", "Exposure", "")
    ev = nuke.Double_Knob("ev_spacing", "EV spacing")
    ev.setRange(-4, 4)
    ev.setValue(2.0)
    ev.setTooltip("Stops between consecutive frames (in filename order). "
                  "Positive = frames get brighter A->Z, negative = darker.")
    ref = nuke.Double_Knob("ref_index", "reference frame")
    ref.setRange(0, MAX_INPUTS - 1)
    ref.setValue(1.0)
    ref.setTooltip("Frame (0 = first) whose exposure the merged result "
                   "matches. Auto-clamped to the frame count on Generate.")
    gain = nuke.Double_Knob("exposure_offset", "output exposure (stops)")
    gain.setRange(-6, 6)
    gain.setValue(0.0)

    div1 = nuke.Text_Knob("wdiv", "Weighting", "")
    hi_s = nuke.Double_Knob("hi_start", "highlight ramp start")
    hi_s.setRange(0, 1); hi_s.setValue(0.70)
    hi_e = nuke.Double_Knob("hi_end", "highlight ramp end")
    hi_e.setRange(0, 1); hi_e.setValue(0.95)
    lo_s = nuke.Double_Knob("lo_start", "shadow ramp start")
    lo_s.setRange(0, 0.1); lo_s.setValue(0.002)
    lo_e = nuke.Double_Knob("lo_end", "shadow ramp end")
    lo_e.setRange(0, 0.1); lo_e.setValue(0.02)
    keep_hi = nuke.Boolean_Knob("keep_extreme_highlights",
                                "darkest frame keeps highlights")
    keep_hi.setValue(True)
    keep_hi.setFlag(nuke.STARTLINE)
    keep_lo = nuke.Boolean_Knob("keep_extreme_shadows",
                                "brightest frame keeps shadows")
    keep_lo.setValue(True)
    keep_lo.setFlag(nuke.STARTLINE)

    info = nuke.Text_Knob(
        "info", "",
        "HDRIMerge v%s\n1. connect bracketed frames (2-%d)\n"
        "2. set EV spacing\n3. click Generate HDRI" % (__version__,
                                                       MAX_INPUTS))

    for k in (tab, gen, sortk, div0, ev, ref, gain,
              div1, hi_s, hi_e, lo_s, lo_e, keep_hi, keep_lo, info):
        group.addKnob(k)

    # ---- input/output stubs (real tree is built by the button) -----------
    group.begin()
    try:
        first = None
        for i in range(MAX_INPUTS):
            inp = nuke.nodes.Input(name="Input%d" % (i + 1))
            inp.setXYpos(i * 120, 0)
            if i == 0:
                first = inp
        nuke.nodes.Output(inputs=[first]).setXYpos(0, 500)
    finally:
        group.end()

    return group


# Backwards-compatible aliases (v1 entry point names)
def merge_from_selection():
    create_hdri_merge_node()


create = create_hdri_merge_node


# ---------------------------------------------------------------------------
# Entry point for the MyTools tool manager: its menu command does
#   import hdri_merge; importlib.reload(...); hdri_merge.run()
# ---------------------------------------------------------------------------
def run():
    create_hdri_merge_node()
