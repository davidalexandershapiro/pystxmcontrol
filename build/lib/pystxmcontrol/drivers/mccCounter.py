#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
    Wrapper call demonstrated:        dio_device.d_bit_out()

    Purpose:                          Writes a value to each of the bits for
                                      the specified DIO port

    Demonstration:                    Writes the value of each bit in the
                                      digital port
    Steps:
    1. Call get_daq_device_inventory() to get the list of available DAQ devices
    2. Create a DaqDevice object
    3. Call daq_device.get_info() to get the daq_device_info object for the DAQ device
    4. Verify that the DAQ device has a digital output subsystem
    5. Call daq_device.connect() to establish a UL connection to the DAQ device
    6. Call daq_device.get_dio_device() to get the dio_device object for the digital subsystem
    7. Call dio_device.d_bit_out() to read each bit of the digital port
    8. Display the data for each bit
"""
from __future__ import print_function
from time import sleep
import time
from os import system
from sys import stdout

from uldaq import (get_daq_device_inventory,
                   DaqDevice,
                   InterfaceType,
                   DigitalDirection,
                   DigitalPortIoType,
                   TmrIdleState,
                   TriggerType,
                   PulseOutOption,
                   TmrStatus,
                   get_daq_device_inventory,
                   create_int_buffer,
                   CInScanFlag,
                   ScanStatus,
                   ScanOption,
                   CounterMeasurementType,
                   CounterRegisterType,
                   CounterMeasurementMode,
                   CounterEdgeDetection,
                   CounterTickSize,
                   CounterDebounceMode,
                   CounterDebounceTime,
                   CConfigScanFlag)

class mccCtr:
    def __init__(self, device_index):
        self.retrigger = True
        self.SYSTEM_CLOCK_FREQUENCY = 100000  # timer 0 pulse frequency which is used as our clock ticks
        self.acquisition_under_sampling_factor = 10  # sampling rate reduction factor from system clock rate
        self.descriptor_index = device_index
        self.daq_device = None
        self.dio_device = None
        self.port_to_write = None
        self.port_info = None
        self.interface_type = InterfaceType.USB
        self.port_types_index = 0

        # timer related data member
        self.timer_number = 0
        self.frequency = self.SYSTEM_CLOCK_FREQUENCY  # 100kHz=10us periodicity
        self.duty_cycle = 0.5  # 50 percent
        self.pulse_count = 100000  # 0 = Continuous
        self.initial_delay = 0.0
        self.idle_state = TmrIdleState.LOW
        self.timer_options = PulseOutOption.DEFAULT
        self.interface_type = InterfaceType.USB
        self.daq_device = None
        self.tmr_device = None

        # counters parameters
        # counter 0-3 for normal counting. counter 4 for generating gate signal
        self.low_counter = 0
        self.high_counter = 5
        self.samples_per_channel = 10000  # number of samples per counter
        self.sample_rate = self.frequency / self.acquisition_under_sampling_factor  # Hz samples per second per counter
        if(self.retrigger == True):
            self.scan_options = ScanOption.SINGLEIO | ScanOption.RETRIGGER | ScanOption.CONTINUOUS
        else:
            self.scan_options = ScanOption.DEFAULTIO | ScanOption.EXTTRIGGER

        self.ctr_device = None
        self.count_data = None
        # gate counter parameters
        self.gate_scan_options = ScanOption.DEFAULTIO
        self.scan_flags = CInScanFlag.CTR32_BIT   # .DEFAULT
        self.counter_range = 2147483647  #32767  # = pow(2,15) -1  2147483647)  # pow(2, 31) -1
        # following will be set by actual dwell and idle times later
        self.gate_period_cnt = 100
        self.gate_rollover_high_cnt = 10
        self.gate_rollover_low_cnt = 0

        self.dwell_ms = 40  # default dwell time and idle time in msec
        self.num_points = 100  # number of data points in a line scan
        self.idle_ms = 0.1
        self.num_lines = 1
        self.dio_port_types_index = 0  # dio port number to write
        self.port_to_write = None
        self.dio_port_info = None

    def connect(self):
        # Get descriptors for all of the available DAQ devices.
        devices = get_daq_device_inventory(self.interface_type)
        number_of_devices = len(devices)

        # Verify at least one DAQ device is detected.
        if number_of_devices == 0:
            raise Exception('Error: No DAQ devices found')

        print('Found', number_of_devices, 'DAQ device(s):')
        for i in range(number_of_devices):
            print('    ', devices[i].product_name, ' (', devices[i].unique_id, ')', sep='')

        # Create a DaqDevice object from the first descriptor.
        self.daq_device = DaqDevice(devices[self.descriptor_index])
        self.tmr_device = self.daq_device.get_tmr_device()

        descriptor = self.daq_device.get_descriptor()
        print('\nConnecting to', descriptor.dev_string, '- please wait...')
        # Establish a connection to the device.
        self.daq_device.connect()

        print('\n', descriptor.dev_string, 'ready')
        print('    Function demonstrated: TmrDevice.pulse_out_start')
        print('    Timer:', self.timer_number)
        print('    Frequency:', self.frequency, 'Hz')
        print('    Duty cycle:', self.duty_cycle)
        print('    Initial delay:', self.initial_delay)

        self.ctr_device = self.daq_device.get_ctr_device()

        # Verify the specified DAQ device supports counters.
        if self.ctr_device is None:
            raise Exception('Error: The DAQ device does not support counters')

        # Verify the specified DAQ device supports hardware pacing for counters.
        ctr_info = self.ctr_device.get_info()
        ctr_res = ctr_info.get_resolution()
        print("counter resolution: ", ctr_res)
        if not ctr_info.has_pacer():
            raise Exception('Error: The DAQ device does not support paced counter inputs')

        # Verify that the selected counters support event counting.
        self.verify_counters_support_events(ctr_info, self.low_counter, self.high_counter)

        self.dio_device = self.daq_device.get_dio_device()
        if self.dio_device is None:
            raise Exception('Error: The device does not support digital output')

        # Get the port types for the device(AUXPORT, FIRSTPORTA, ...)
        dio_info = self.dio_device.get_info()
        port_types = dio_info.get_port_types()
        if self.dio_port_types_index >= len(port_types):
            self.dio_port_types_index = len(port_types) - 1

        self.port_to_write = port_types[self.dio_port_types_index]

        # Get the port I/O type and the number of bits for the first port.
        self.dio_port_info = dio_info.get_port_info(self.port_to_write)

        # If the port is bit configurable, then configure the individual bits
        # for output; otherwise, configure the entire port for output.
        if self.dio_port_info.port_io_type == DigitalPortIoType.BITIO:
            # Configure all of the bits for output for the first port.
            for bit_number in range(self.dio_port_info.number_of_bits):
                self.dio_device.d_config_bit(self.port_to_write,
                                             bit_number,
                                             DigitalDirection.OUTPUT)
        elif self.dio_port_info.port_io_type == DigitalPortIoType.IO:
            # Configure the entire port for output.
            self.dio_device.d_config_port(self.port_to_write, DigitalDirection.OUTPUT)

        max_port_value = pow(2.0, self.dio_port_info.number_of_bits) - 1
        print('\n', descriptor.dev_string, ' ready', sep='')
        print('    Function demonstrated: dio_device.d_bit_out()')
        print('    Port: ', self.port_to_write.name)
        print('    Port I/O type: ', self.dio_port_info.port_io_type.name)
        print('    Bits: ', self.dio_port_info.number_of_bits)

    def disconnect(self):
        # Disconnect from the DAQ device.
        if self.daq_device.is_connected():
            self.daq_device.disconnect()
        # Release the DAQ device resource.
        self.daq_device.release()

    def timer_start(self):
        # Start the timer pulse output.
        # convert number of desired data points to pulse count
        # since the output frequency and duty cycle is fixed, and we know the gate counter's
        # rollover value
        self.tmr_device.set_trigger(TriggerType.POS_EDGE, self.timer_number, 1, 0, 1)
        num_pulses = 0  # self.pulse_count,  # 0 means infinite number pulses
        frequency, duty_cycle, initial_delay = self.tmr_device.pulse_out_start(
            self.timer_number,
            self.frequency,
            self.duty_cycle,
            num_pulses,
            self.initial_delay,
            self.idle_state,
            self.timer_options)

    def timer_stop(self):
        if self.tmr_device:
            self.tmr_device.pulse_out_stop(self.timer_number)

    def counter_start(self, numlines):
        self.num_lines = numlines
        self.dio_output(0, 0)
        number_of_counters = self.high_counter - self.low_counter + 1
        for cc in range(self.low_counter, self.high_counter, 1):
            self.ctr_device.c_clear(cc)

        for counter_index in range(self.low_counter, self.high_counter-1, 1):
            self.ctr_device.c_config_scan(counter_index,
                                          CounterMeasurementType.COUNT,
                                          CounterMeasurementMode.GATING_ON |
                                          CounterMeasurementMode.RANGE_LIMIT_ON,
                                          CounterEdgeDetection.RISING_EDGE,
                                          CounterTickSize.TICK_20ns,  # .TICK_20ns,
                                          CounterDebounceMode.NONE,  #.TRIGGER_AFTER_STABLE,
                                          CounterDebounceTime.DEBOUNCE_0ns,
                                          CConfigScanFlag.DEFAULT)
            self.ctr_device.c_load(counter_index, CounterRegisterType.MAX_LIMIT, self.counter_range)  #
            self.ctr_device.c_load(counter_index, CounterRegisterType.MIN_LIMIT, 0)

        self.setup_gate(self.high_counter-1)
        self.setup_mask_pulse(self.high_counter)

        self.samples_per_channel = (int)((self.dwell_ms + (self.num_points-1) * (self.dwell_ms + self.idle_ms)) *
                                         0.001 * self.sample_rate)
        self.samples_per_channel += self.gate_rollover_low_cnt + 10  # add a few extra to make sure we have the point at the end of dwell

        self.ctr_device.set_trigger(TriggerType.POS_EDGE, 0, 3, 0, self.samples_per_channel)

        if not self.retrigger:
            self.num_lines = 1
        # Create a buffer for input data.
        self.count_data = create_int_buffer(number_of_counters, self.samples_per_channel * self.num_lines)
        # Start the input scan.
        self.sample_rate = self.ctr_device.c_in_scan(self.low_counter,
                                                     self.high_counter,
                                                     self.samples_per_channel * self.num_lines,
                                                     self.sample_rate,
                                                     self.scan_options,
                                                     self.scan_flags,
                                                     self.count_data)

    def setup_mask_pulse(self, masking_ctr):
        # setup the counter to send out a long square wave pulse that lasts the duration of the counting period
        # add some arbitrary counts to the end of the masking pulse?
        self.ctr_device.c_load(masking_ctr, CounterRegisterType.MAX_LIMIT, self.counter_range)  #
        self.ctr_device.c_load(masking_ctr, CounterRegisterType.MIN_LIMIT, 0)
        self.ctr_device.c_load(masking_ctr, CounterRegisterType.OUTPUT_VAL0, 1) # self.gate_rollover_low_cnt)  # always 0
        # Rollover high value determines pulses width
        mask_extension = self.pulse_count + (int)((self.dwell_ms + self.idle_ms/10) * 0.001 * self.frequency)
        self.ctr_device.c_load(masking_ctr, CounterRegisterType.OUTPUT_VAL1, mask_extension)
        self.ctr_device.c_config_scan(masking_ctr,
                                      CounterMeasurementType.COUNT,
                                      CounterMeasurementMode.OUTPUT_ON |
                                      CounterMeasurementMode.RANGE_LIMIT_ON |
                                      CounterMeasurementMode.GATE_TRIG_SRC, #.GATING_ON,
                                      CounterEdgeDetection.RISING_EDGE,
                                      CounterTickSize.TICK_20ns,
                                      CounterDebounceMode.NONE,  #.TRIGGER_AFTER_STABLE,
                                      CounterDebounceTime.DEBOUNCE_0ns,  #.DEBOUNCE_1500ns,
                                      CConfigScanFlag.DEFAULT)

    def setup_gate(self, gate_ctr):
        # MAX limit determines pulse period (dwell + idle) time
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.MAX_LIMIT, self.gate_period_cnt)
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.MIN_LIMIT, 0)
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.OUTPUT_VAL0, self.gate_rollover_low_cnt)  # always 0
        # Rollover high value determines pulses width
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.OUTPUT_VAL1, self.gate_rollover_high_cnt+self.gate_rollover_low_cnt)
        self.ctr_device.c_config_scan(gate_ctr,
                                      CounterMeasurementType.COUNT,
                                      CounterMeasurementMode.OUTPUT_ON |
                                      CounterMeasurementMode.RANGE_LIMIT_ON |
                                      CounterMeasurementMode.GATING_ON,
                                      CounterEdgeDetection.RISING_EDGE,
                                      CounterTickSize.TICK_20ns,
                                      CounterDebounceMode.TRIGGER_AFTER_STABLE,
                                      CounterDebounceTime.DEBOUNCE_1500ns,
                                      CConfigScanFlag.DEFAULT)
    def counter_stop(self):
        # Stop the scan.
        if self.ctr_device:
            if not self.retrigger:
                self.ctr_device.scan_stop()  # retrigger test
            for ctr in range(self.high_counter+1):
                self.ctr_device.c_clear(ctr)
        # self.clear_gate(self.high_counter)

    def dio_output(self, data, bit_number):
        # for bit_number in range(self.dio_port_info.number_of_bits):
        bit_value = (int(data) >> bit_number) & 1
        self.dio_device.d_bit_out(self.port_to_write, bit_number, bit_value)
        # print('Bit(', bit_number, ') Data: ', bit_value)

    def dio_stop(self):
        if self.dio_device and self.port_to_write and self.dio_port_info:
            # before disconnecting, set the port back to input
            if (self.dio_port_info.port_io_type == DigitalPortIoType.IO or
                    self.dio_port_info.port_io_type == DigitalPortIoType.BITIO):
                self.dio_device.d_config_port(self.port_to_write,
                                         DigitalDirection.OUTPUT)  # .INPUT)

    def convert_msec_to_ticks(self, dwell_ms, idle_ms, num_data_points):
        # Start the timer pulse output.
        # convert number of desired data points to pulse count
        # since the output frequence and duty cycle is fixed, and we know the gate counter's
        # rollover value
        self.dwell_ms = dwell_ms
        self.idle_ms = idle_ms
        self.num_points = num_data_points
        self.gate_rollover_high_cnt = (int)(dwell_ms*0.001*self.frequency) + self.gate_rollover_low_cnt
        self.gate_period_cnt = (int)((dwell_ms + idle_ms) * 0.001 * self.frequency)
        self.pulse_count = (int)(self.gate_period_cnt * num_data_points)

    # current_line number starts from 0 to num_lines-1
    def wait_till_scan_done(self, current_line):
        if not self.retrigger:
            current_line = 0
        num_ctrs = self.high_counter - self.low_counter + 1
        scan_status, transfer_status = self.ctr_device.get_scan_status()
        segment_size= (int)(len(self.count_data)/self.num_lines)
        max_index = segment_size * (current_line + 1) - num_ctrs
        while transfer_status.current_index < max_index or \
                    (scan_status == ScanStatus.RUNNING and (not self.retrigger)):
                # data not complete
                index = transfer_status.current_index
                if index >= 0:
                    counter_value = self.count_data[index]
                    # print(' index ', index, '   Counter ', 0, ':', str(counter_value).rjust(12), sep='')
                    stdout.flush()
                    sleep(0.001)
                scan_status, transfer_status = self.ctr_device.get_scan_status()

        mycounts = []
        for ii in range(segment_size * current_line, max_index, 1):
            mycounts.append(self.count_data[ii])

        for ii in range(segment_size * current_line, max_index, num_ctrs):
            counter_value = self.count_data[ii]
            # print(' index ', ii/num_ctrs, '   Counter ', 0, ':', str(counter_value).rjust(12), sep='')
        stdout.flush()

    def read_counts(self, ctr_num, current_line):
        if not self.retrigger:
            current_line = 0   # make sure always line 0 for none retrigger mode
        counts = []
        segment_size = (int)(len(self.count_data)/self.num_lines)
        # calculate position of each data point for the counter number requested
        # data is arranged in block wise fashion serially
        # (0 1 2 3...) (0 1 2 3 ...)..
        first_index = segment_size * current_line + ctr_num - self.low_counter  # first reading, base value, to be subtracted from subsequent count
        num_ctrs = self.high_counter - self.low_counter + 1
        for data_pt in range(0, self.num_points, 1):
            block_index = self.msec_to_block_index(data_pt, ctr_num - self.low_counter)
            block_index += segment_size * current_line
            tmp_data = self.count_data[block_index] - self.count_data[first_index]
            counts.append(tmp_data)
        for data_pt in range(self.num_points - 1, 0, -1):
            counts[data_pt] -= counts[data_pt - 1]
        return counts

    def msec_to_block_index(self, data_index,  ctr_num):
        num_ctrs = self.high_counter - self.low_counter + 1
        block_index = (int)((self.dwell_ms + data_index * (self.dwell_ms + self.idle_ms)) * 0.001 * self.sample_rate) * num_ctrs
        return block_index + ctr_num


    def clear_gate(self, gate_ctr):
        # MAX limit determines pulse period (dwell + idle) time
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.MAX_LIMIT, pow(2,31) -1)
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.MIN_LIMIT, 0)
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.OUTPUT_VAL0, self.gate_rollover_low_cnt + 1)  # always 0
        # Rollover high value determines pulses width
        self.ctr_device.c_load(gate_ctr, CounterRegisterType.OUTPUT_VAL1, pow(2,31) -1)
        self.ctr_device.c_clear(gate_ctr)

    def verify_counters_support_events(self, ctr_info, low_counter, high_counter):
        """
        Verifies that the selected counter channels support event counting.

        Raises:
            Exception if a counter channel does not support event counting
            or if a counter channel is not in range.
        """
        num_counters = ctr_info.get_num_ctrs()
        valid_counters_string = 'valid counter channels are 0 - {0:d}'.format(num_counters - 1)
        if low_counter < 0 or low_counter >= num_counters:
            error_message = ' '.join(['Error: Invalid low_counter selection,', valid_counters_string])
            raise Exception(error_message)

        if high_counter < 0 or high_counter >= num_counters:
            error_message = ' '.join(['Error: Invalid high_counter selection,', valid_counters_string])
            raise Exception(error_message)

        if high_counter < low_counter:
            error_message = 'Error: Invalid counter selection, high_counter must be greater than or equal to low_counter'
            raise Exception(error_message)

        for counter in range(low_counter, high_counter + 1):
            supported_meas_types = ctr_info.get_measurement_types(counter)
            if CounterMeasurementType.COUNT not in supported_meas_types:
                error_message = ('Error: Invalid counter selection, counter '
                                 '{0:d} does not support event counting'.format(counter))
                raise Exception(error_message)


class mccTester:
    def __init__(self):
        self.counter = mccCtr(0)
        self.counter.connect()
        self.dwell_ms = 1
        self.idle_ms = 0.1
        self.num_data_points = 1
        self.num_lines = 1
        self.bit_num = 0  # dio port bit to write for trigger point scan
        self.dio_output_hi_byte = 1
        self.dio_output_lo_byte = 0

    def start(self, dwell):
        self.dwell_ms = dwell
        self.idle_ms = 0.1
        self.num_data_points = 1
        self.num_lines = 1
        self.counter.convert_msec_to_ticks(self.dwell_ms, self.idle_ms, self.num_data_points)
        self.bit_num = 0  # dio port bit to write for trigger point scan
        self.dio_output_hi_byte = 1
        self.dio_output_lo_byte = 0
        self.counter.dio_output(self.dio_output_lo_byte, self.bit_num)
        if self.counter.retrigger:
            self.counter.timer_start()
            self.counter.counter_start(self.num_lines)

    def stop(self):
        self.counter.dio_output(self.dio_output_lo_byte, self.bit_num)
        if self.counter.retrigger:
            self.counter.timer_stop()
        self.counter.dio_stop()
        self.counter.disconnect()

    def getPoint(self):
        for ll in range(self.num_lines):
            start_t = time.time()
            if not self.counter.retrigger:
                self.counter.timer_start()
                self.counter.counter_start(self.num_lines)
            time1 = time.time()
            print("counter start: ", str(time1 - start_t))
            self.counter.dio_output(self.dio_output_hi_byte, self.bit_num)
            self.counter.dio_output(self.dio_output_lo_byte, self.bit_num)
            time2 = time.time()
            print("dio output hi: ", str(time2 - time1))
            self.counter.wait_till_scan_done(ll)
            time3 = time.time()
            print("wait time: ", str(time3 - time2))
            for ctr_num in range(self.counter.low_counter, self.counter.high_counter - 1, 1):
                counts = self.counter.read_counts(ctr_num, ll)
                print("counter_: ", str(ctr_num), ": ", counts)
            time4 = time.time()
            print("read time: ", str(time4 - time3))

            #self.counter.dio_output(dio_output_lo_byte, bit_num)
            time5 = time.time()
            print("dio out lo: ", str(time5 - time4))

            self.counter.counter_stop()
            time6 = time.time()
            print("stop time: ", str(time6 - time5))
            print("total time: ", str(time6 - start_t))



def main():
    mycounters = mccCtr(0)
    mycounters.connect()
    dwell_ms = 1
    idle_ms = 0.1
    num_data_points = 10
    mycounters.convert_msec_to_ticks(dwell_ms, idle_ms, num_data_points)
    # timer must be started prior to counter start

    num_lines = 100
    bit_num = 0  # dio port bit to write for trigger point scan
    dio_output_hi_byte = 1
    dio_output_lo_byte = 0
    mycounters.dio_output(dio_output_lo_byte, bit_num)
    if mycounters.retrigger:
        mycounters.timer_start()
        mycounters.counter_start(num_lines)


    sleep(60)

    for ll in range(num_lines):
        start_t = time.time()
        if not mycounters.retrigger:
            mycounters.timer_start()
            mycounters.counter_start(num_lines)
        time1 = time.time()
        print("counter start: ", str(time1 - start_t))
        mycounters.dio_output(dio_output_hi_byte, bit_num)
        mycounters.dio_output(dio_output_lo_byte, bit_num)
        time2 = time.time()
        print("dio output hi: ", str(time2 - time1))
        mycounters.wait_till_scan_done(ll)
        time3 = time.time()
        print("wait time: ", str(time3 - time2))
        for ctr_num in range(mycounters.low_counter, mycounters.high_counter - 1, 1):
            counts = mycounters.read_counts(ctr_num, ll)
            print("counter_: ", str(ctr_num), ": ", counts)
        time4 = time.time()
        print("read time: ", str(time4 - time3))

        #mycounters.dio_output(dio_output_lo_byte, bit_num)
        time5 = time.time()
        print("dio out lo: ", str(time5 - time4))

        mycounters.counter_stop()
        time6 = time.time()
        print("stop time: ", str(time6 - time5))
        print("total time: ", str(time6 - start_t))
        #sleep(0.1)

    mycounters.dio_output(dio_output_lo_byte, bit_num)
    if mycounters.retrigger:
        mycounters.timer_stop()
    mycounters.dio_stop()
    mycounters.disconnect()

if __name__ == '__main__':
    main()
