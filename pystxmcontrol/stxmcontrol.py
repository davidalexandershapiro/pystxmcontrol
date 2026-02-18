#!/usr/bin/env python
from pystxmcontrol.gui.mainwindow import *
import qdarktheme

if __name__ == '__main__':

    app = QtWidgets.QApplication([])
    app.setStyleSheet(qdarktheme.load_stylesheet("light"))
    widget = sampleScanWindow()
    widget.show()

    @atexit.register
    def disconnectClient():
        global widget
        widget.disconnect()

    sys.exit(app.exec())