#!/bin/bash
pyside6-uic -o mainwindow_UI.py mainwindow.ui && sed -i '' 's/Qt\.AlignmentFlag\.Qt\.AlignmentFlag\./Qt.AlignmentFlag./g' mainwindow_UI.py