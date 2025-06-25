#!/usr/bin/env python
from pystxmcontrol.gui.mainwindow import *
import qdarktheme

if __name__ == '__main__':
    @atexit.register
    def disconnectClient():
        global widget
        widget.disconnect()

    app = QtWidgets.QApplication([])
    app.setStyleSheet(qdarktheme.load_stylesheet("light"))
    widget = sampleScanWindow()
    widget.show()
    sys.exit(app.exec())