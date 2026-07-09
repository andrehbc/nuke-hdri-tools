# menu.py -- sample menu entries for nuke-hdri-tools.
# Copy these lines into your ~/.nuke/menu.py (create it if missing).

import nuke

m = nuke.menu("Nodes").addMenu("HDRI")
m.addCommand("HDRIMerge", "import hdri_merge; hdri_merge.run()")
m.addCommand("DNG to EXR", "import dng2exr_ui; dng2exr_ui.run()")
