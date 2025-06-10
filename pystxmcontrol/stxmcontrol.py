#!/usr/bin/env python
from pystxmcontrol.gui.mainwindow import *
import qdarkstyle

if __name__ == '__main__':
    @atexit.register
    def disconnectClient():
        global widget
        widget.disconnect()

    app = QtWidgets.QApplication([])
    #app.setStyleSheet(qdarkstyle.load_stylesheet())
    widget = sampleScanWindow()
    widget.show()
    sys.exit(app.exec())