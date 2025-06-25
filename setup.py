from setuptools import setup

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
        data_files = [('pystxmcontrol_cfg',['config/daqConfig.json','config/main.json',\
                                 'config/motorConfig.json','config/scans.json','config/meta.json','config/stxmLog.txt',\
                                 'config/xeryon_default.txt'])],
        install_requires = ['numpy<2.0','pyusb','python-usbtmc','pylibftdi','pyvisa-py',\
                             'scipy','scikit-image','pyqtdarktheme', 'pyepics', 'pyserial',\
                             'pyzmq','PySide6==6.8.2.1','matplotlib','h5py','pyqtgraph','griffe==0.47',\
                             'prefect==2.14.3','pydantic==1.10.4','python-dotenv','opencv-python-headless','scikit-learn',\
                            'PIPython'],
        zip_safe = False)
