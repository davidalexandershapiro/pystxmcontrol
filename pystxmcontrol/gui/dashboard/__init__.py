"""The acquisition dashboard: the single-window STXM/ptychography interface.

Run it with the ``stxmcontrol`` console script, or ``python -m
pystxmcontrol.gui.dashboard.main``.  It drives the same ``MainController`` and
models as the classic window in ``pystxmcontrol.gui.mainwindow_mvc``, so both
can talk to the same server.

The window itself is ``mainwindow.MainWindowDashboard``.  Around it:

* ``theme`` / ``widgets``   — the palette, stylesheet and styled builders every
                              panel is assembled from
* ``scan_definition``       — the editable scan geometry, and the region
                              dictionaries the server scans (Qt-free)
* ``scan_stats``            — estimated time, point count, stage velocity
* ``motor_info``            — what motor.json says exists and what to show
* ``staff_auth``            — the staff-mode password
* ``scan_files``            — instrument identity and the last recorded scan
* ``image_area``            — the main viewer, its ROIs and its scientific axis
* ``detector_panel``        — the Live-detector card
* ``favorites_bar``         — saved energy-region shortcuts
* ``heartbeat``             — server reachability for the header LED
* ``browser_app`` / ``analysis_app`` / ``agent_app`` — the other three top-level
                              views, each also runnable standalone
* ``motor_panel`` / ``beamline_panel`` — floating utility windows

The modules with no Qt import — ``scan_definition``, ``scan_stats``,
``motor_info``, ``staff_auth`` — are where the arithmetic and the rules live,
and they are unit-tested directly in ``tests/``.

Shared image assets stay in the parent package (``pystxmcontrol/gui/icons``),
because the classic window uses them too.
"""
