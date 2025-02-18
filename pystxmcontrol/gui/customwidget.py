import sys
from PySide6 import QtCore, QtWidgets

class customWidget(QtWidgets.QWidget):

    def __init__(self, parent= None):
        QtWidgets.QWidget.__init__(self, parent)

        #Container Widget
        self.widget = QtWidgets.QWidget()
        #Layout of Container Widget
        layout = QtWidgets.QVBoxLayout(self)
        self.widget.setLayout(layout)

        #Scroll Area Properties
        scroll = QtWidgets.QScrollArea()
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.widget)

        #Scroll Area Layer add
        vLayout = QtWidgets.QVBoxLayout(self)
        vLayout.addWidget(scroll)
        self.setLayout(vLayout)

    def addWidget(self, widget):
        self.widget.layout().addWidget(widget)

    def removeWidget(self, widget):
        self.widget.layout().removeWidget(widget)


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)

    dialog = customWidget()
    dialog.show()

    app.exec_()
