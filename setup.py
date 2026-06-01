from setuptools import setup
from setuptools.command.install import install
from setuptools.command.develop import develop
import os
import subprocess

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _install_desktop_file():
    icon_path = os.path.join(_REPO_ROOT, 'icons', 'pystxmcontrol_icon.png')
    desktop_dir = os.path.expanduser('~/.local/share/applications')
    os.makedirs(desktop_dir, exist_ok=True)
    desktop_path = os.path.join(desktop_dir, 'pystxmcontrol.desktop')
    with open(desktop_path, 'w') as f:
        f.write(
            '[Desktop Entry]\n'
            'Name=pystxmControl\n'
            'Exec=python -m pystxmcontrol.gui.main\n'
            f'Icon={icon_path}\n'
            'Type=Application\n'
            'Categories=Science;\n'
        )
    # subprocess.run(['update-desktop-database', desktop_dir], check=False)
    print(f'Installed desktop file: {desktop_path}')


class _PostInstall(install):
    def run(self):
        super().run()
        _install_desktop_file()


class _PostDevelop(develop):
    def run(self):
        super().run()
        _install_desktop_file()


def readme():
    with open('README.rst') as f:
        return f.read()

setup(  name = 'pystxmcontrol',
        version = '1.0',
        description = 'Basic GUI for ALS STXM Control',
        author = 'David Shapiro',
        author_email = 'dashapiro@lbl.gov',
        packages = ['pystxmcontrol','pystxmcontrol.gui','pystxmcontrol.controller',\
            'pystxmcontrol.drivers','pystxmcontrol.utils','pystxmcontrol.controller.scans'],
        entry_points = {
            'console_scripts': [
                'stxmcontrol = pystxmcontrol.gui.main:main',
                'stxmserver   = pystxmcontrol.controller.server:main',
                'stxmbrowser  = pystxmcontrol.gui.browser_analysis_app:main',
            ],
        },
        cmdclass={'install': _PostInstall, 'develop': _PostDevelop},
        data_files = [('pystxmcontrol_cfg',['config/daq.json','config/main.json',\
                                 'config/motor.json','config/scan.json','config/log.txt',\
                                 'config/xeryon_default.txt'])],
        install_requires = ['numpy<2.0','pyusb','python-usbtmc','pylibftdi','pyvisa-py',\
                             'scipy','scikit-image','pyqtdarktheme', 'pyepics', 'pyserial',\
                             'pyzmq','PySide6==6.8.2.1','matplotlib','h5py','pyqtgraph',\
                                'python-dotenv','opencv-python-headless','scikit-learn', 'PIPython'],
        zip_safe = False)
