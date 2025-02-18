#! /usr/bin/python
# -*- coding: utf-8 -*-
import time
import socket
from . import cin_register_map as crm




def connect2daq(ip, port):
    # Connect to QT DAQ
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(("dummy data"), (ip, port))

    return sock


def ByteToHex(byteStr):
    """
    Convert a byte string to it's hex string representation e.g. for output.
    """

    # Uses list comprehension which is a fractionally faster implementation than
    # the alternative, more readable, implementation below
    #
    #    hex = []
    #    for aChar in byteStr:
    #        hex.append( "%02X " % ord( aChar ) )
    #
    #    return ''.join( hex ).strip()

    return ''.join(["%02X" % x for x in byteStr]).strip()


def HexToByte(hexStr):
    """
    Convert a string hex byte values into a byte string. The Hex Byte values may
    or may not be space separated.
    """
    # The list comprehension implementation is fractionally slower in this case
    # s
    #    hexStr = ''.join( hexStr.split(" ") )
    #    return ''.join( ["%c" % chr( int ( hexStr[i:i+2],16 ) ) \
    #                                   for i in range(0, len( hexStr ), 2) ] )

    ints = []

    hexStr = ''.join(hexStr.split(" "))

    for i in range(0, len(hexStr), 2):
        ints.append(int(hexStr[i:i + 2], 16))

    return bytes(ints)


def current_calc(reg_val, current):
    if (int(reg_val[4:8], 16) >= int("8000", 16)):
        #	  current = 0.000000238*((int("10000",16) - int(reg_val[4:8],16)))/0.003
        current = 0.000000476 * ((int("10000", 16) - int(reg_val[4:8], 16))) / 0.003
    else:
        #	  current = 0.000000238*(int(reg_val[4:8],16))/0.003
        current = 0.000000476 * (int(reg_val[4:8], 16)) / 0.003
    return current


class CIN(object):
    def __init__(self, **kwargs):

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)

        base = '/global/software/code/cosmic/cosmic/camera/CINControl/'
        
        self.IP_FRAME = "10.0.5.207"
        self.IP_CONFIG = "192.168.1.207"
        self.PORT_COMMAND = 49200
        self.PORT_STREAM_IN = 49202
        self.PORT_STREAM_OUT = 49203
        #self.FILE_WAVEFORM_SETTINGS = base + "CINController/config/waveform_settings_20131218.txt"
        self.FILE_WAVEFORM_SETTINGS = base + "CINController/config/20180511_125MHz_fCCD_Timing_FS_2OS_xper.txt"
        self.FILE_BIAS_SETTINGS = base + "CINController/config/bias_setting_lbl_gold4_8000.txt"
        self.FILE_FCRIC_CONFIG = base + "CINController/config/ARRA_fcrics_config_x1_11112011_8000.txt"
        #self.FILE_FIRMWARE = base + "firmware/CIN_1kFSCCD/top_frame_fpga_r2001.bit"
        #self.FILE_FIRMWARE = base + "firmware/CIN_1kFSCCD/CIN_1kFSCCD_ISE14_7_top_302D.bit"
        self.FILE_FIRMWARE = base + "firmware/CIN_1kFSCCD/CIN_1kFSCCD_ISE14_7_top_302E.bit"
        self.IP_E36102A = "192.168.1.3"
        self.PORT_E36102A = 5025

    def set_register(self, reg_addr, value, verify=0):
        """
        :param reg_addr:
        :param value:
        :param verify:
        :return:
        """
        cin_sock = self.sock
        cin_sock.sendto(HexToByte(reg_addr + value), (self.IP_CONFIG, self.PORT_COMMAND))
        time.sleep(0.001)

        if not verify:
            return 1
        else:
            reg_val = self.get_register(reg_addr)
            if (reg_addr + value).upper() == reg_val.upper():
                return 1
            else:
                print("Register %s: Writing %s but reading %s." % (reg_addr, value, reg_val[4:]))
                return 0

    def get_register(self, reg_addr):

        cin_sock = self.sock

        cin_sock.sendto(HexToByte(crm.REG_READ_ADDRESS + reg_addr),
                        (self.IP_CONFIG, self.PORT_COMMAND))
        time.sleep(0.1)
        cin_sock.sendto(HexToByte(crm.REG_COMMAND + crm.CMD_READ_REG),
                        (self.IP_CONFIG, self.PORT_COMMAND))

        # time.sleep(0.1)
        cin_sock.settimeout(1.0)
        try:
            data, addr = cin_sock.recvfrom(1024)

        except socket.timeout:
            time.sleep(0.1)
            cin_sock.sendto(HexToByte(crm.REG_COMMAND + crm.CMD_READ_REG),
                            (self.IP_CONFIG, self.PORT_COMMAND))
            cin_sock.settimeout(1.0)
            try:
                data, addr = cin_sock.recvfrom(1024)
            except socket.timeout:
                print("No connection to CIN")
                return ""
                
        return ByteToHex(data)
    
    def resetCounter(self):
        self.set_register(crm.REG_FRM_COMMAND, "0106", 0)
        
    def getFrmDone(self):
        temp = bin((int(self.get_register(crm.REG_FPGA_STATUS)[4:8], 16)))[2:].zfill(16)
        return int(temp[-16])

    def CINPowerUp(self):
        print(" ")
        print("Powering On CIN Board ........  ")
        # if self.set_register(crm.REG_PS_ENABLE, "000F", 1) != 1:
        #     return
        self.set_register(crm.REG_PS_ENABLE, "000F", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 1)

        # if self.set_register(crm.REG_PS_ENABLE, "001F", 1) != 1:
        #     return
        self.set_register(crm.REG_PS_ENABLE, "001F", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 0)
        time.sleep(2)

    def CINPowerDown(self):
        print(" ")
        print("Powering Off CIN Board ........  ")
        # if self.set_register(crm.REG_PS_ENABLE, "0000", 1) != 1:
        #     return
        self.set_register(crm.REG_PS_ENABLE, "0000", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 0)
        time.sleep(1)

    def CIN_FP_PowerUp(self):
        print(" ")
        print("Powering On Front Panel Boards ........  ")
        # if self.set_register(crm.REG_PS_ENABLE, "003F", 1) != 1:
        #     print("Write register could not be verified. Aborting.")
        #     return
        self.set_register(crm.REG_PS_ENABLE, "003F", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 1)

        time.sleep(4)

    def CIN_FP_PowerDown(self):
        print(" ")
        print("Powering Off Front Panel Boards ........  ")
        # if self.set_register(crm.REG_PS_ENABLE, "001F", 1) != 1:
        #     print("Write register could not be verified. Aborting.")
        #     return
        self.set_register(crm.REG_PS_ENABLE, "001F", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 1)

        time.sleep(1)

    def setCameraOn(self):
        print(" ")
        print("Turning off Bias and Clocks in camera head ........  ")

        self.set_register(crm.REG_BIASCONFIGREGISTER0_REG, "0001", 1)
        self.set_register(crm.REG_CLOCKCONFIGREGISTER0_REG, "0001", 1) # could also be "0009" or "0003"
        time.sleep(1)
        
    def setCameraOff(self):
        print(" ")
        print("Turning off Bias and Clocks in camera head ........  ")

        self.set_register(crm.REG_BIASCONFIGREGISTER0_REG, "0000", 1)
        self.set_register(crm.REG_CLOCKCONFIGREGISTER0_REG, "0000", 1)
        time.sleep(1)

    def clearFocusBit(self):
        # Get Value from Clock&Bias Control
        reg_val = self.get_register("8205")
        # print reg_val[4:]

        temp = str(hex((int(reg_val[7:], base=16) & 0xD)).lstrip("0x"))
        # print temp

        str_val = reg_val[4:5] + reg_val[5:6] + reg_val[6:7] + temp
        self.set_register("8205", str_val, 1)

    def setFocusBit(self):
        # Get Value from Clock&Bias Control
        reg_val = self.get_register("8205")
        # print reg_val[4:]

        # temp = str(hex((int(reg_val[7:],base=16)|0x2)).lstrip("0x"))
        # print temp

        str_val = reg_val[4:5] + reg_val[5:6] + reg_val[6:7] + "A"  # temp
        self.set_register("8205", str_val, 1)

    def loadFrmFirmware(self, filename):
        print("Loading Frame (FRM) FPGA Configuration Data ...........  ")
        print("File: " + filename)
        self.set_register(crm.REG_COMMAND, crm.CMD_PROGRAM_FRAME, 0)
        time.sleep(1)
        with open(filename, 'rb') as f:
            read_data = f.read(128)
            while read_data != b"":
                self.sock.sendto(read_data, (self.IP_CONFIG, self.PORT_STREAM_IN))
                time.sleep(0.000125)  # For UDP flow control (was 0.002)
                read_data = f.read(128)
            f.close()
        time.sleep(1)
        self.set_register(crm.REG_FRM_RESET, "0001", 0)
        self.set_register(crm.REG_FRM_RESET, "0000", 0)
        time.sleep(1)
        # need to verify sucess!

    def loadCameraConfigFile(self, filename):
        print(" ")
        print("Loading Configuration File to CCD Camera ...........  ")
        print("File: " + filename)
        with open(filename, 'r') as f:
            file_line = f.readline()
            while file_line != "":
                if (file_line[:1] != "#"):
                    read_addr = file_line[:4]
                    read_data = file_line[5:9]
                    # print read_addr + read_data
                    self.set_register(read_addr, read_data, 0)
                # time.sleep(0.1)
                file_line = f.readline()
            f.close()

    def flashFpCfgLeds(self):
        # Test Front Panel LEDs
        print(" ")
        print("Flashing CFG FP LEDs  ............ ")
        self.set_register(crm.REG_SANDBOX_REG00, "AAAA", 1)
        time.sleep(1)
        self.set_register(crm.REG_SANDBOX_REG00, "5555", 1)
        time.sleep(1)
        self.set_register(crm.REG_SANDBOX_REG00, "FFFF", 1)
        time.sleep(1)
        self.set_register(crm.REG_SANDBOX_REG00, "0001", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0002", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0004", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0008", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0010", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0020", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0040", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0080", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0100", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0200", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0400", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0800", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "1000", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "2000", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "4000", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "8000", 1)
        time.sleep(0.4)
        self.set_register(crm.REG_SANDBOX_REG00, "0000", 1)

    # ---------------------------------------------< Frame FPGA functions >

    def flashFpFrmLeds(self):
        # Test Front Panel LEDs
        print(" ")
        print("Flashing FRM FP LEDs  ............ ")
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0004", 1)
        print("RED  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0008", 1)
        print("GRN  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "000C", 1)
        print("YEL  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0010", 1)
        print("RED  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0020", 1)
        print("GRN  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0030", 1)
        print("YEL  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0040", 1)
        print("RED  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0080", 1)
        print("GRN  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "00C0", 1)
        print("YEL  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0100", 1)
        print("RED  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0200", 1)
        print("GRN  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0300", 1)
        print("YEL  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0400", 1)
        print("RED  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0800", 1)
        print("GRN  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0C00", 1)
        print("YEL  ............ ")
        time.sleep(0.5)
        self.set_register(crm.REG_FRM_SANDBOX_REG00, "0000", 1)
        print("All OFF  ............ ")
        time.sleep(0.5)

    ########################################################################################################################
    ########################################################################################################################

    def setFOtestpattern(self, status=True):
        """
        status = True for ON or False for OFF
        """
        if status:
            # Write to FO Module Register to send Test Pattern
            self.set_register("821D", "9E00", 0)
            self.set_register("821E", "0000", 0)
            self.set_register("821F", "0001", 0)
            self.set_register("8001", "0105", 0)

            self.set_register("8211", "0000", 0)
            self.set_register("8212", "0000", 0)
            self.set_register("8213", "0000", 0)
        else:
            # Write to FO Register to turn off Test Pattern
            self.set_register("821D", "9E00", 0)
            self.set_register("821E", "0000", 0)
            self.set_register("821F", "0000", 0)
            self.set_register("8001", "0105", 0)

            # Mask All FCRIC Channels
            self.set_register("8211", "FFFF", 0)
            self.set_register("8212", "FFFF", 0)
            self.set_register("8213", "FFFF", 0)

    def allPowerUp(self, testOnly=True):
        """
        Power on the CIN, send FPGA firmware, set clocks, power on fiber optic module
        :return:
        """

        self.CINPowerDown()
        self.CINPowerUp()
        self.getCfgFPGAStatus()

        # Baseline CIN FW and Clock Configuration
        self.loadFrmFirmware(self.FILE_FIRMWARE)
        self.setFClk125M()
        self.setTriggerExt()
        self.setFPPowerOn()
        self.set_FOPS_On()
        self.getPowerStatus()

        print("Loading WAVEFORM config file...")
        self.loadCameraConfigFile(self.FILE_WAVEFORM_SETTINGS)
        
        print("Arbitrary pausing here...")

        if not testOnly:
            time.sleep(10)
            self.loadCameraConfigFile(self.FILE_BIAS_SETTINGS)
            print("Taking deep breath ...")
            time.sleep(1)
            self.loadCameraConfigFile(self.FILE_FCRIC_CONFIG)
            time.sleep(0.3)
            self.setCameraOn()
            
    def setFPPowerOn(self):
        print(" ")
        print("Powering On Front Panel Boards ........  ")
        # if self.set_register(crm.REG_PS_ENABLE, "003F", 1) != 1:
        #     print("Write register could not be verified. Aborting.")
        #     return
        self.set_register(crm.REG_PS_ENABLE, "003F", 1)
        self.set_register(crm.REG_COMMAND, crm.CMD_PS_ENABLE, 1)

    def set_FOPS_On(self, volts=4.5, amps=4.9, volts_protect=5.25 ):

        # Create a socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((self.IP_E36102A, self.PORT_E36102A))

        # Clear Communications
        s.sendall(b'*CLS\r\n')
        # Wait at least 50ms before sending next command
        time.sleep(0.1)
        s.sendall(b'SYST:REM\r\n')

        # Turn off FO Power Supply Output
        # s.sendall('OUTP 0 \r\n')

        # Set Output Voltage to 4.5V and Current Limit to 4.5A
        s.sendall(b'SOUR:VOLT:PROT %1.3f \r\n' % volts_protect)
        s.sendall(b'SOUR:VOLT %1.3f \r\n' % volts)
        s.sendall(b'SOUR:CURR %1.3f \r\n' % amps)
        # Turn on FO Power Supply Output
        s.sendall(b'OUTP 1 \r\n')

        self.get_FOPS_Status()

        s.close()

    def set_FOPS_Off(self):

        # Create a socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((self.IP_E36102A, self.PORT_E36102A))

        # Clear Communications
        s.sendall(b'*CLS\r\n')
        # Wait at least 50ms before sending next command
        time.sleep(0.1)

        # Turn off FO Power Supply Output
        s.sendall(b'OUTP 0 \r\n')

        time.sleep(0.2)
        s.close()

    def get_FOPS_Status(self):

        # Create a socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((self.IP_E36102A, self.PORT_E36102A))

        # Clear Communications
        s.sendall(b'*CLS\r\n')
        # Wait at least 50ms before sending next command
        time.sleep(0.1)

        # print("FastCCD FO Power Supply Monitor")
        s.sendall(b'MEAS:VOLT?')
        v = s.recv(16)
        s.sendall(b'MEAS:CURR?')
        i = s.recv(16)

        voltage = float(v)
        if (voltage < 0.01):
            voltage = 0.000
        print("%.4f V" % voltage)  # str(voltage)[0:5] + " V"

        current = float(i)
        if (current < 0.01): current = 0.000
        print("%.4f A" % current)

        s.close()

    def getPowerStatus(self):

        # def getPowerStatus():
        print(" ")
        print("****  CIN Power Monitor  ****\n")
        reg_val = bin((int(self.get_register(crm.REG_PS_ENABLE)[4:8], 16)))[2:].zfill(16)
        stats_vec = reg_val[:]
        if (int(stats_vec[-1]) == 1):

            # ADC == LT4151
            reg_val = self.get_register(crm.REG_VMON_ADC1_CH1)
            voltage = 0.025 * int(reg_val[4:8], 16)
            reg_val = self.get_register(crm.REG_IMON_ADC1_CH0)
            current = 0.00002 * int(reg_val[4:8], 16) / 0.003
            power = voltage * current
            print("V12P_BUS Power  : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A \n")

            # ADC == LT2418
            reg_val = self.get_register(crm.REG_VMON_ADC0_CH5)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH5)
            current = current_calc(reg_val, current)
            print("V3P3_MGMT Power : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH7)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH7)
            current = current_calc(reg_val, current)
            print("V2P5_MGMT Power : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            #	reg_val = self.get_register( crm.REG_VMON_ADC0_CH6 )
            #	voltage = 0.00007629*(int(reg_val[4:8],16))
            #	reg_val = self.get_register( crm.REG_IMON_ADC0_CH6 )
            #	current = current_calc(reg_val,current)
            #	print("  V1P8_MGMT Power : {0:.4s}").format(str(voltage)) + "V  @  {0:.5s}".format(str(current)) + "A"

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH2)
            voltage = 0.00007629 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH2)
            current = current_calc(reg_val, current)
            print("V1P2_MGMT Power : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH3)
            voltage = 0.00007629 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH3)
            current = current_calc(reg_val, current)
            print("V1P0_ENET Power : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A\n")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH4)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH4)
            current = current_calc(reg_val, current)
            print("V3P3_S3E Power  : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH8)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH8)
            current = current_calc(reg_val, current)
            print("V3P3_GEN Power  : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CH9)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CH9)
            current = current_calc(reg_val, current)
            print("V2P5_GEN Power  : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A\n")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CHE)
            voltage = 0.00007629 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CHE)
            current = current_calc(reg_val, current)
            print("V0P9_V6 Power   : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CHB)
            voltage = 0.00007629 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CHB)
            current = current_calc(reg_val, current)
            print("V1P0_V6 Power   : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")

            #	reg_val = self.get_register( crm.REG_VMON_ADC0_CHC )
            #	voltage = 0.00007629*(int(reg_val[4:8],16))
            #	reg_val = self.get_register( crm.REG_IMON_ADC0_CHC )
            #	current = current_calc(reg_val,current)
            #	print("  V1P2_V6 Power   : {0:.4s}").format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A"

            reg_val = self.get_register(crm.REG_VMON_ADC0_CHD)
            voltage = 0.00015258 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CHD)
            current = current_calc(reg_val, current)
            print("V2P5_V6 Power   : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A\n")

            reg_val = self.get_register(crm.REG_VMON_ADC0_CHF)
            voltage = 0.00030516 * (int(reg_val[4:8], 16))
            reg_val = self.get_register(crm.REG_IMON_ADC0_CHF)
            current = current_calc(reg_val, current)
            print("V_FP Power      : {0:.4s}".format(str(voltage)) + "V @ {0:.5s}".format(str(current)) + "A")
        else:
            print("  12V Power Supply is OFF")

    def setFClk125M(self):
        # def setFCLK125M():
        print("**** Set CIN FCLK to 125MHz")
        # Freeze DCO
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B089", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F010", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)
        print("  Write to Reg 137 - Freeze DCO")

        print("  Set Si570 Oscillator Freq to 125MHz")
        # WR Reg 7
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B007", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F002", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # WR Reg 8
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B008", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F042", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # WR Reg 9
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B009", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F0BC", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # WR Reg 10
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B00A", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F019", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # WR Reg 11
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B00B", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F06D", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # WR Reg 12
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B00C", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "f08f", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)

        # UnFreeze DCO
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B089", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F000", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)
        self.set_register(crm.REG_FCLK_I2C_ADDRESS, "B087", 0)
        self.set_register(crm.REG_FCLK_I2C_DATA_WR, "F040", 0)
        self.set_register(crm.REG_FRM_COMMAND, crm.CMD_FCLK_COMMIT, 0)
        print("  Write to Reg 137 - UnFreeze DCO & Start Oscillator")
        print("  ")

        # Set Clock&Bias Time Contant
        self.set_register(crm.REG_CCDFCLKSELECT_REG, "0000", 0)

    def getCfgFPGAStatus(self):
        # ---------------------------------------------< Configuration FPGA functions >
        # def getCfgFpgaStat():
        # get Status Registers
        print("****  CFG FPGA Status Registers  **** \n")
        reg_val = self.get_register(crm.REG_BOARD_ID)
        print(" CIN Board ID     :  " + reg_val[4:])
        reg_val = self.get_register(crm.REG_HW_SERIAL_NUM)
        print(" HW Serial Number :  " + reg_val[4:])
        reg_val = self.get_register(crm.REG_FPGA_VERSION)
        print(" CFG FPGA Version :  " + reg_val[4:] + "\n")
        reg_val = self.get_register(crm.REG_FPGA_STATUS)
        print(" CFG FPGA Status  :  " + reg_val[4:])
        # FPGA Status
        # 15 == FRM DONE
        # 14 == NOT FRM BUSY
        # 13 == NOT FRM INIT B
        # 12 >> 4 == 0
        # 3 >>0 == FP Config Control 3 == PS Interlock
        reg_val = bin((int(self.get_register(crm.REG_FPGA_STATUS)[4:8], 16)))[2:].zfill(16)
        stats_vec = reg_val[:]
        if (int(stats_vec[-16]) == 1):
            print("  ** Frame FPGA Configuration Done")
        else:
            print("  ** Frame FPGA NOT Configured")
        if (int(stats_vec[-4]) == 1):
            print("  ** FP Power Supply Unlocked")
        else:
            print("  ** FP Power Supply Locked Off")
        reg_val = self.get_register(crm.REG_DCM_STATUS)
        print("\n CFG DCM Status   : " + reg_val[4:])
        # DCM Status
        # 15 == 0
        # 14 >> 8 == CONF SW
        # 7 == ATCA 48V Alarm
        # 6 == tx2 src ready
        # 5 == tx1 src ready
        # 4 == DCM STATUS2
        # 3 == DCM STATUS1
        # 2 == DCM STATUS0
        # 1 == DCM PSDONE
        # 0 == DCM LOCKED
        reg_val = bin((int(self.get_register(crm.REG_DCM_STATUS)[4:8], 16)))[2:].zfill(16)
        stats_vec = reg_val[:]
        if (int(stats_vec[-8]) == 1):
            print("  ** ATCA 48V Alarm")
        else:
            print("  ** ATCA 48V OK")
        if (int(stats_vec[-1]) == 1):
            print("  ** CFG Clock DCM Locked")
        else:
            print("  ** CFG Clock DCM NOT Locked")
        if (int(stats_vec[-12]) == 0):
            print("  ** FP Power Supply Interlock Overide Enable")

    def allPowerDown(self):
        print("Shutting down CCD Bias and Clocks")
        self.setCameraOff()

        # print("\n  Shutting down Camera Power Supply")
        # import setMainPS1_Off

        print("Shutting down Camera Interface Node Blade & FO Interface Boards")
        self.set_FOPS_Off()
        self.CINPowerDown()

    def setExpTime(self, expTime, other=False):
        """
        Exposure time in ms.
        :return:
        """

        # Convert ms to Hex - 1 count = 10us
        exp_time_d = int(float(expTime) * 32)
        # print exp_time_d
        if (exp_time_d == 0):
            # If exp=0, set register value to "0001"
            exp_time_h = "0001"
        else:
            exp_time_h = str(hex(exp_time_d)).lstrip("0x").zfill(8)
        # exp_time_h = str(hex(exp_time_d)).lstrip("0x").zfill(8)
        # print exp_time_h
        # print exp_time_h[4:]
        # print exp_time_h[0:4]
        if not other:
            # Write Number of Exposure Time MSB
            self.set_register(crm.REG_EXPOSURETIMEMSB_REG, exp_time_h[0:4], 1)
            # Write Number of Exposure Time LSB
            self.set_register(crm.REG_EXPOSURETIMELSB_REG, exp_time_h[4:], 1)
        else:
            # Write Number of Exposure Time MSB
            self.set_register(crm.REG_ALTEXPOSURETIMEMSB_REG, exp_time_h[0:4], 1)
            # Write Number of Exposure Time LSB
            self.set_register(crm.REG_ALTEXPOSURETIMELSB_REG, exp_time_h[4:], 1)
            
    def getExpTime(self, other=False):
        
        if not other:
            # Write Number of Exposure Time MSB
            msb = self.get_register(crm.REG_EXPOSURETIMEMSB_REG)
            # Write Number of Exposure Time LSB
            lsb = self.get_register(crm.REG_EXPOSURETIMELSB_REG)
        else:
            # Write Number of Exposure Time MSB
            msb = self.get_register(crm.REG_ALTEXPOSURETIMEMSB_REG)
            # Write Number of Exposure Time LSB
            lsb = self.get_register(crm.REG_ALTEXPOSURETIMELSB_REG)
        
        return float(int(msb[4:]+lsb[4:],16)) / 32
        
    def setAltExpTime(self, expTime):
        """
        Exposure time in ms.
        :return:
        """
        self.setExpTime(expTime,True)
    
    def getAltExpTime(self):
        """
        Exposure time in ms.
        :return:
        """
        return self.getExpTime(True)


    def setExpMode(self, mode):
        """
        Set single or double exposure mode.  Double = 1 and Single = 0
        :param mode:
        :return:
        """

        addr = str(8050)
        data = int(mode, 16)
        bitpos = int(15)
        width = int(1)

        # Select Bit Mask
        count = 0
        maskbit = 0x0000
        while (count < width):
            maskbit = maskbit << 1
            maskbit = maskbit | 0x0001
            count = count + 1

        # Create bit clearing mask
        temp = maskbit << int(bitpos)
        clrval = ~temp & 0xFFFF
        # Create bitwise insert value
        insval = (maskbit & data) << int(bitpos)

        # Read Selected Register value
        regval = self.get_register(addr)[4:]
        # Clear write location
        twdata = int(regval, 16) & clrval
        # Input new data bits
        wdata = twdata | insval
        # Format Data word for self.set_register Function
        data = "{0:0>4}".format(str(hex(wdata)).lstrip("0x"))
        # Write new data word
        self.set_register(addr, data, 1)

    def setVClamp(self, voltage):
        """
        set the FCRIC clamping voltage
        :param voltage:
        :return:
        """

        ClampVoltage = str(voltage)
        # print ClampVoltage

        # Device Locator Word
        self.set_register("821D", "9E00", 0)
        # Register Address
        self.set_register("821E", "0001", 0)

        # Register Data
        if (ClampVoltage == "1.60"):
            self.set_register("821F", "8055", 0)
        elif (ClampVoltage == "1.65"):
            self.set_register("821F", "8054", 0)
        elif (ClampVoltage == "1.70"):
            self.set_register("821F", "8051", 0)
        elif (ClampVoltage == "1.75"):
            self.set_register("821F", "8050", 0)
        elif (ClampVoltage == "1.80"):
            self.set_register("821F", "8045", 0)
        elif (ClampVoltage == "1.85"):
            self.set_register("821F", "8044", 0)
        elif (ClampVoltage == "1.90"):
            self.set_register("821F", "8041", 0)
        elif (ClampVoltage == "1.95"):
            self.set_register("821F", "8040", 0)
        elif (ClampVoltage == "2.00"):
            self.set_register("821F", "8015", 0)
        elif (ClampVoltage == "2.05"):
            self.set_register("821F", "8014", 0)
        elif (ClampVoltage == "2.10"):
            self.set_register("821F", "8011", 0)
        elif (ClampVoltage == "2.15"):
            self.set_register("821F", "8010", 0)
        elif (ClampVoltage == "2.20"):
            self.set_register("821F", "8005", 0)
        elif (ClampVoltage == "2.25"):
            self.set_register("821F", "8004", 0)
        elif (ClampVoltage == "2.30"):
            self.set_register("821F", "8001", 0)
        elif (ClampVoltage == "2.35"):
            self.set_register("821F", "8000", 0)
        else:
            print("Invalid Voltage (1.60 to 2.35 in 0.05 steps only)")
            return

        # Send Data Command
        self.set_register("8001", "0105", 0)

    def setContTrig(self):
        # Clear the Focus bit
        self.clearFocusBit()

        # Set Number of Exposures to value = 0000
        self.set_register(crm.REG_NUMBEROFEXPOSURE_REG, "0000", 1)

        # Set the Focus bit
        self.setFocusBit()

    def setTriggerExt(self):
        self.setTriggerMask(3)
        
    def setTriggerSW(self):
        self.setTriggerMask(0)
        
    def setTriggerMask(self, num):
        
        data = "{0:0>4}".format(str(hex(num)).lstrip("0x"))
        self.set_register(crm.REG_TRIGGERMASK_REG, data, 1)
        
    def getTriggerMask(self):
        
        data = self.get_register(crm.REG_TRIGGERMASK_REG)[4:]
        
        return int(data,16)
        
    """
    def setExtTrig():
        import cin_hal
    
        cin_hal.setTrigger_OR()
    """

    def stopTrigger(self):
        # Clear the Focus bit
        self.clearFocusBit()

        # Set Number of Exposures to value = 0001
        self.set_register(crm.REG_NUMBEROFEXPOSURE_REG, "0001", 1)
