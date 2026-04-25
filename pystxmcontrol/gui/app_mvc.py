#!/usr/bin/env python3
"""
Application entry point using MVC architecture.
This demonstrates how to use the refactored MVC components.
"""

import sys
import faulthandler
faulthandler.enable()   # print Python traceback to stderr on SIGSEGV/SIGFPE

from PySide6.QtWidgets import QApplication
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Create and show the main window
    window = MainWindowMVC()
    window.show()
    
    # Start the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()