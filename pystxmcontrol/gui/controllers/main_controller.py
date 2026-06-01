from PySide6.QtCore import QObject, Signal, QThread
from typing import Dict, Any, Optional
import os
import re
import time
import sys
import numpy as np
from queue import Queue

from ..models.scan_model import ScanModel
from ..models.motor_model import MotorModel
from ..models.image_model import ImageModel
from ...controller.client import stxm_client
from ...utils.writeNX import stxm


class TaskAgentThread(QThread):
    """Runs TaskAgent.run() in a background thread."""

    message = Signal(str)        # streaming status/trace lines
    finished_text = Signal(str)  # final text response

    def __init__(self, agent, goal: str):
        QThread.__init__(self)
        self._agent = agent
        self._goal = goal

    def cancel(self):
        self._agent.cancel()

    def run(self):
        result = self._agent.run(self._goal, publish_fn=lambda msg: self.message.emit(msg))
        self.finished_text.emit(result)


class ControlThread(QThread):
    """Thread for handling client communication."""

    controlResponse = Signal(object)
    
    def __init__(self, client, message_queue):
        QThread.__init__(self)
        self.message_queue = message_queue
        self.client = client
        self.monitor = True
        
    def run(self):
        while self.monitor:
            message = self.message_queue.get(True)
            if message != "exit":
                response = self.client.send_message(message)
                if response is None:
                    response = {"command": message["command"], "status": "No response from server"}
                self.controlResponse.emit(response)
            else:
                return


class MainController(QObject):
    """Main controller that coordinates between models and views."""
    
    # Signals for view updates
    motor_position_updated = Signal(str, float)  # motor_name, position
    motor_status_updated = Signal(str, bool)     # motor_name, is_moving
    image_updated = Signal(object)               # image data
    scan_progress_updated = Signal(str)          # progress info (region / energy)
    scan_file_updated = Signal(str)              # current scan file name
    error_occurred = Signal(str)                 # error message
    status_updated = Signal(str)                 # status message
    monitor_data_updated = Signal()              # monitor plot needs update
    daq_value_updated = Signal(float)            # DAQ current value
    scan_state_changed = Signal(bool)            # scanning state changed (True=scanning, False=completed)
    estimated_time_updated = Signal(float)       # estimated scan time updated
    elapsed_time_updated = Signal(float)         # elapsed scan time updated
    motor_scan_updated = Signal()                # single motor scan data ready to plot
    live_data_ready = Signal(object, object)     # (stxm object, raw message dict) for stack viewer
    external_scan_started = Signal(str)          # scan started externally (carries scan_type string)
    intelligence_suggestion_received = Signal(dict)  # agent suggestion or anomaly diagnosis
    shutter_state_changed = Signal(str)             # gate mode changed: "open", "close", "auto"
    scan_pause_changed = Signal(bool)               # pause toggled: True=paused, False=resumed
    task_agent_status = Signal(str)                 # streaming trace from TaskAgent
    task_agent_done = Signal(str)                   # final TaskAgent response
    scan_region_geometry_updated = Signal(dict, str)  # (scan config dict, scan_type) for external scans

    def __init__(self):
        super().__init__()
        
        # Initialize models
        self.scan_model = ScanModel()
        self.motor_model = MotorModel()
        self.image_model = ImageModel()
        
        # Initialize client and communication
        self.client = stxm_client()
        self.message_queue = Queue()
        self.control_thread = None
        
        # State tracking
        self.scanning = False
        self.server_status = False
        self.exiting = False
        self._gate_mode = ""
        self._scan_paused = False
        self._task_agent = None
        self._agent_thread = None

        # Display throttle — limit image redraws to this interval (seconds).
        # Scan data is always stored in the model; only the display is rate-limited.
        self._display_min_interval = 1.0 / 30.0   # max 30 fps
        self._last_display_time = 0.0
        self._live_stxm = None  # stxm object maintained during Image scans for stack viewer

        # Profiling — set PROFILE_IMAGE_UPDATE = True to enable timing output
        self.PROFILE_IMAGE_UPDATE = False
        self._prof = {}   # accumulated seconds per label
        self._prof_n = 0  # image line count
        self._prof_interval = 20  # print summary every N lines
        
        # Connect model signals
        self._connect_model_signals()
        
    def _prof_tick(self, label: str, dt: float):
        """Accumulate timing for a labelled section."""
        self._prof[label] = self._prof.get(label, 0.0) + dt

    def _prof_report(self):
        """Print accumulated timing summary and reset counters."""
        total = sum(self._prof.values())
        print(f"\n── Image update profile ({self._prof_n} lines) ──")
        for label, acc in sorted(self._prof.items(), key=lambda x: -x[1]):
            pct = 100.0 * acc / total if total > 0 else 0
            print(f"  {label:<35s} {acc*1000/self._prof_n:7.2f} ms/line  ({pct:.0f}%)")
        print(f"  {'TOTAL':<35s} {total*1000/self._prof_n:7.2f} ms/line")
        self._prof.clear()
        self._prof_n = 0

    def _connect_model_signals(self):
        """Connect model signals to controller methods."""
        self.scan_model.data_changed.connect(self._on_scan_model_changed)
        self.motor_model.data_changed.connect(self._on_motor_model_changed)
        self.image_model.data_changed.connect(self._on_image_model_changed)
        
    def _resolve_daq_list(self, scan_type: str) -> list:
        """
        Return the recordable DAQ keys for *scan_type* by cross-referencing
        scan.json (scanConfig) with daq.json (daqConfig).
        Falls back to ['default'] if config is unavailable.
        """
        try:
            scan_cfg = self.client.scanConfig.get(scan_type, {})
            raw = scan_cfg.get('daq_list', 'default')
            requested = [raw] if isinstance(raw, str) else list(raw)
            daq_cfg = self.client.daqConfig
            resolved = [k for k in requested if k in daq_cfg and daq_cfg[k].get('record', True)]
            return resolved if resolved else ['default']
        except Exception:
            return ['default']

    def _on_scan_model_changed(self, property_name: str, value: Any):
        """Handle scan model changes."""
        if property_name in ['scan_regions', 'energy_regions']:
            self.image_model.set('energy_list', self.scan_model.get_energies())
            # Recalculate estimated time when scan parameters change
            estimated_time = self.scan_model.calculate_estimated_time()
            # Emit signal for view to update
            self.estimated_time_updated.emit(estimated_time)
        elif property_name == 'daq_list':
            # Keep image model in sync so the display layer knows which channels exist
            self.image_model.set('daq_list', value)
            
    def _on_motor_model_changed(self, property_name: str, value: Any):
        """Handle motor model changes."""
        if property_name == 'current_positions':
            for motor_name, position in value.items():
                self.motor_position_updated.emit(motor_name, position)
        elif property_name == 'motor_status':
            for motor_name, is_moving in value.items():
                self.motor_status_updated.emit(motor_name, is_moving)
                
    def _on_image_model_changed(self, property_name: str, value: Any):
        """Handle image model changes."""
        if property_name == 'current_image':
            self.image_updated.emit(value)
        elif property_name == 'monitor_data':
            self.monitor_data_updated.emit()
        elif property_name == 'daq_current_value':
            self.daq_value_updated.emit(value)
        elif property_name == 'channel_key':
            # Channel changed — re-emit the stored image for the new channel so
            # the view updates immediately without waiting for the next scan frame
            self.refresh_channel_image()
        elif property_name in ['cursor_x', 'cursor_y', 'cursor_intensity']:
            pass

    def refresh_channel_image(self):
        """Re-emit image_updated for the currently selected channel.

        Looks at the last complete set of detector images stored in the model
        ('all_detector_images') and emits the slice for the active channel.
        No-ops silently if no image data has been received yet.
        """
        all_images = self.image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return
        channel_key = self.image_model.get('channel_key', 'default')
        image = all_images.get(channel_key)
        if image is None:
            image = all_images.get('default')
        if image is not None:
            self.image_updated.emit(image)
            
    def initialize_client(self):
        """Initialize the client connection."""
        try:
            # Set up control thread
            self.control_thread = ControlThread(self.client, self.message_queue)
            self.control_thread.start()
            self.control_thread.controlResponse.connect(self._handle_client_response)
            
            # Get configuration
            self.client.get_config()
            self.motor_model.set_motor_info(self.client.motorInfo)

            # Seed scan model with the daq_list for the default scan type
            default_scan_type = self.scan_model.get('scan_type', 'Image')
            self.scan_model.set('daq_list', self._resolve_daq_list(default_scan_type))

            # Initialize motor positions from client
            self._initialize_motor_positions()
            
            # Connect to client monitor for real-time updates
            self._connect_client_monitors()
            
            self.server_status = True
            self.status_updated.emit("Connected to server")
            self._initialize_task_agent()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to connect to server: {str(e)}")
            self.server_status = False
            return False
            
    def _initialize_motor_positions(self):
        """Initialize motor positions from client."""
        try:
            if hasattr(self.client, 'currentMotorPositions') and self.client.currentMotorPositions:
                # Update motor model with current positions
                for motor_name, position in self.client.currentMotorPositions.items():
                    if isinstance(position, (int, float)):
                        self.motor_model.update_position(motor_name, position)
                        
            # Set default status (all motors not moving initially)
            motor_info = self.motor_model.get('motor_info', {})
            for motor_name in motor_info.keys():
                self.motor_model.update_status(motor_name, False)
                
        except Exception as e:
            print(f"Warning: Could not initialize motor positions: {e}")
            
    def _connect_client_monitors(self):
        """Connect to client monitor signals for real-time updates."""
        try:
            # Connect to scan data monitor for motor positions and image updates
            self.client.monitor.scan_data.connect(self._handle_monitor_message)
            
            # Try to connect to other monitors
            try:
                self.client.ccd.framedata.connect(self._handle_ccd_data)
            except:
                pass  # CCD monitor not available
                
            try:
                self.client.ptycho.ptychoData.connect(self._handle_ptycho_data)
            except:
                pass  # Ptycho monitor not available
                
        except Exception as e:
            print(f"Warning: Could not connect all monitors: {e}")
            
    def _handle_client_response(self, response):
        """Handle responses from client commands."""
        if response["status"]:
            pass
        else:
            self.status_updated.emit(f"Command response: {response.get('status', 'Unknown')}")
        
    def _handle_monitor_message(self, message):
        """Handle real-time monitor messages from client.  These messages are python dictionaries which
        contain the data and it's definition for live display.  It may either be the idle monitor stream
        or the data images during a scan."""
        # Handle scan completion
        if message == "scan_complete":
            self.scanning = False
            self.reset_pause_state()
            self.status_updated.emit("Scan completed")
            # Force a final display update so the last partial image is always shown
            final_image = self.image_model.get('current_image')
            if final_image is not None:
                self._last_display_time = 0.0  # reset throttle
                self.image_model.set_current_image(final_image)
            self.scan_state_changed.emit(False)  # Signal scan completed
            return  # Early return - nothing else to do

        # If message is not a dict, skip processing
        if not isinstance(message, dict):
            return

        # Intelligence agent suggestion — route directly, skip scan data processing
        if message.get("type") == "intelligence_suggestion":
            self.intelligence_suggestion_received.emit(message)
            return

        # Intelligence recommendation for the task agent — append to the shared queue
        if message.get("type") == "task_recommendation":
            pending = list(self.image_model.get("pending_recommendations") or [])
            pending.append(message)
            self.image_model.set("pending_recommendations", pending)
            self.intelligence_suggestion_received.emit(message)
            return

        try:
            # Gate/shutter state — emit when it changes
            gate_mode = message.get("gate_mode")
            if gate_mode and gate_mode != self._gate_mode:
                self._gate_mode = gate_mode
                self.shutter_state_changed.emit(gate_mode)

            # Extract motor positions and status
            if 'motorPositions' in message:
                motor_positions = message['motorPositions']
                motor_status = message['motorPositions'].get('status', {})
                
                # Update all motor positions in a single batch to avoid the
                # O(N²) signal emission caused by updating one-at-a-time
                # (each update_position call re-emits for the entire dict).
                batch = {
                    k: v for k, v in motor_positions.items()
                    if k != 'status' and isinstance(v, (int, float))
                }
                if batch:
                    _t0 = time.perf_counter()
                    positions = self.motor_model.get('current_positions', {}).copy()
                    positions.update(batch)
                    self.motor_model.set('current_positions', positions)
                    if self.PROFILE_IMAGE_UPDATE:
                        self._prof_tick('1_motor_positions', time.perf_counter() - _t0)

                # Batch motor status update — single set() call, single signal emission
                if motor_status:
                    status = self.motor_model.get('motor_status', {}).copy()
                    status.update(motor_status)
                    self.motor_model.set('motor_status', status)

            # Handle monitor data for plotting
            if message.get("type") == "monitor":
                # Store zone plate calibration data if present
                if 'zonePlateCalibration' in message:
                    self.image_model.set('zonePlateCalibration', message['zonePlateCalibration'])
                if 'zonePlateOffset' in message:
                    self.image_model.set('zonePlateOffset', message['zonePlateOffset'])

                # Monitor data accumulation and plot update are only needed when
                # idle — skip entirely during a scan regardless of message layout.
                if 'rawData' in message and not self.scanning:
                    _t0 = time.perf_counter()
                    raw = message["rawData"]
                    daq_cfg = getattr(self.client, 'daqConfig', {})
                    monitor_data = self.image_model.get('monitor_data', {}).copy()
                    for daq_key, daq_data in raw.items():
                        if isinstance(daq_data, dict) and "data" in daq_data:
                            data = daq_data["data"]
                            if data is None:
                                continue
                            daq_type = daq_cfg.get(daq_key, {}).get('type', 'point')
                            if daq_type == 'spectrum':
                                monitor_data[daq_key] = list(data)
                            elif daq_type == 'image':
                                value = float(np.sum(data))
                                buf = monitor_data.get(daq_key, []) + [value]
                                monitor_data[daq_key] = buf[-500:]
                            else:
                                value = float(data[0])
                                buf = monitor_data.get(daq_key, []) + [value]
                                monitor_data[daq_key] = buf[-500:]
                    if self.PROFILE_IMAGE_UPDATE:
                        self._prof_tick('2a_monitor_data_accumulate', time.perf_counter() - _t0)
                        _t0 = time.perf_counter()
                    self.image_model.set('monitor_data', monitor_data)  # triggers monitor plot redraw
                    if self.PROFILE_IMAGE_UPDATE:
                        self._prof_tick('2b_monitor_plot_signal+render', time.perf_counter() - _t0)
                    # Current-value display and optional image update for selected channel
                    channel_key = self.image_model.get('channel_key', 'default')
                    selected = raw.get(channel_key)
                    if selected is not None and "data" in selected:
                        data = selected["data"]
                        if data is not None:
                            daq_type = daq_cfg.get(channel_key, {}).get('type', 'point')
                            val = float(np.sum(data)) if daq_type == 'image' else float(data[0])
                            self.image_model.set('daq_current_value', val * 10.0)
                            # For image-type DAQs, prefer the minimally processed image
                            # from message['data'][channel_key] over the raw frame.
                            if daq_type == 'image':
                                processed = message.get('data', {}).get(channel_key)
                                frame = (processed if isinstance(processed, np.ndarray) and processed.ndim >= 2
                                         else data if isinstance(data, np.ndarray) and data.ndim >= 2
                                         else None)
                                if frame is not None:
                                    self.image_updated.emit(frame)
                    
            # Handle elapsed time from scan messages
            elif 'elapsedTime' in message:
                elapsed_time = message['elapsedTime']
                if elapsed_time is not None:
                    self.elapsed_time_updated.emit(float(elapsed_time))
                time_remaining = message.get('time_remaining')
                if time_remaining is not None:
                    self.estimated_time_updated.emit(float(time_remaining))
                    self.image_model.set('time_remaining', float(time_remaining))
                
            # Handle Single Motor scan — data arrives as rawData points, not images
            if (message.get('mode') == 'point' and
                    message.get('type') == 'Single Motor' and
                    'scanMotorVal' in message and 'rawData' in message and
                    message['scanMotorVal'] is not None):
                x_val = float(message['scanMotorVal'])
                raw = message['rawData']
                daq_cfg = getattr(self.client, 'daqConfig', {})

                # Accumulate X position
                x_data = self.image_model.get('motor_scan_x_data', []) + [x_val]
                self.image_model._data['motor_scan_x_data'] = x_data

                # Accumulate Y data per channel
                motor_y = self.image_model.get('motor_scan_y_data', {})
                if not isinstance(motor_y, dict):
                    motor_y = {}
                for daq_key, daq_data in raw.items():
                    if isinstance(daq_data, dict) and 'data' in daq_data:
                        if daq_data['data'] is None:
                            continue
                        daq_type = daq_cfg.get(daq_key, {}).get('type', 'point')
                        val = float(np.sum(daq_data['data'])) if daq_type == 'image' else float(daq_data['data'][0])
                        ch_buf = motor_y.get(daq_key, []) + [val]
                        motor_y[daq_key] = ch_buf
                self.image_model._data['motor_scan_y_data'] = motor_y

                # Store motor name and scan type for axis labels
                self.image_model._data['motor_scan_x_motor'] = self.scan_model.get('x_motor', 'Motor')
                self.image_model._data['scan_type'] = 'Single Motor'

                self._on_external_scan_detected('Single Motor')
                self.motor_scan_updated.emit()

            # Handle image data (for both continuous and point mode scans)
            if 'image' in message and message.get('mode') in ['rasterLine', 'continuousLine', 'continuousSpiral', 'ptychographyGrid', 'ptychographySpiral', 'point']:
                # message['image'] is now a dict with keys like 'default', 'xrf', 'tey', etc.
                image_dict = dict(message['image'])

                # For image-type DAQs (e.g. CCD) the server sends both a raw frame in
                # message['image'] and a minimally processed image in message['data'].
                # Override image_dict entries with the processed version for all scan modes.
                if isinstance(message.get('data'), dict):
                    daq_cfg = getattr(self.client, 'daqConfig', {})
                    for daq_key, daq_val in message['data'].items():
                        if daq_val is None:
                            continue
                        if daq_cfg.get(daq_key, {}).get('type') == 'image':
                            image_dict[daq_key] = daq_val

                # Store the full image dictionary
                metadata = {
                    'energy': message.get('energy'),
                    'dwell': message.get('dwell'),
                    'scan_region': message.get('scanRegion'),
                    'energy_index': message.get('energyIndex'),
                    'scan_id': message.get('scanID', ''),
                    'type': message.get('type'),
                    'mode': message.get('mode'),
                    'all_images': image_dict,  # Store all detector images
                    # Per-tile geometry sent by the scan driver (used for tiled scans
                    # where server-generated sub-regions are not in the GUI scan_regions dict)
                    'msg_x_center': message.get('xCenter'),
                    'msg_y_center': message.get('yCenter'),
                    'msg_x_range':  message.get('xRange'),
                    'msg_y_range':  message.get('yRange'),
                    'msg_x_pts':    message.get('xPoints'),
                    'msg_y_pts':    message.get('yPoints'),
                }

                # Extract the selected channel's image for display
                if isinstance(image_dict, dict):
                    channel_key = self.image_model.get('channel_key', 'default')
                    display_image = image_dict.get(channel_key)
                    if display_image is None:
                        display_image = image_dict.get('default')
                    if display_image is not None:
                        _t0 = time.perf_counter()
                        self.update_image_data(display_image, metadata)
                        if self.PROFILE_IMAGE_UPDATE:
                            self._prof_tick('3_update_image_data (total)', time.perf_counter() - _t0)
                            self._prof_n += 1
                            if self._prof_n >= self._prof_interval:
                                self._prof_report()
                    else:
                        print(f"Warning: image dict has no key '{channel_key}' or 'default'. Keys: {list(image_dict.keys())}")
                else:
                    # Fallback for old message format (direct numpy array)
                    self.update_image_data(image_dict, metadata)

                # Update live stxm object for stack viewer
                if self._live_stxm is not None and isinstance(image_dict, dict):
                    try:
                        energy_index = message.get('energyIndex', 0)
                        region_str = message.get('scanRegion', 'Region1')
                        region_num = int(region_str.split('Region')[-1]) - 1
                        for daq, img in image_dict.items():
                            if (daq in self._live_stxm.interp_counts and
                                    region_num < len(self._live_stxm.interp_counts[daq]) and
                                    isinstance(img, np.ndarray) and img.ndim >= 2):
                                self._live_stxm.interp_counts[daq][region_num][energy_index] = img
                        self._live_stxm.NXfile = message.get('scanID', '')
                        self.live_data_ready.emit(self._live_stxm, message)
                    except Exception as ex:
                        print(f"Warning: live stxm update failed: {ex}")

                # Detect scan that started externally (update_image_data has already written
                # scan_type into image_model, so the view will read the correct type).
                scan_type_str = message.get('type', '')
                if not self.scanning and scan_type_str:
                    x_center = message.get('xCenter')
                    x_range  = message.get('xRange')
                    x_pts    = message.get('xPoints')
                    y_center = message.get('yCenter')
                    y_range  = message.get('yRange')
                    y_pts    = message.get('yPoints')
                    if None not in (x_center, x_range, x_pts, y_center, y_range, y_pts):
                        x_step = round(x_range / x_pts, 4) if x_pts else 0.0
                        y_step = round(y_range / y_pts, 4) if y_pts else 0.0
                        geo_config = {
                            'scan_regions': {
                                'Region1': {
                                    'xCenter': x_center, 'yCenter': y_center,
                                    'xRange':  x_range,  'yRange':  y_range,
                                    'xPoints': x_pts,    'yPoints': y_pts,
                                    'xStep':   x_step,   'yStep':   y_step,
                                }
                            }
                        }
                        self.scan_region_geometry_updated.emit(geo_config, scan_type_str)
                self._on_external_scan_detected(scan_type_str)

        except Exception as e:
            print(f"Error handling monitor message: {e}")
            
    def _handle_ccd_data(self, ccd_data):
        """Handle CCD frame data."""
        # Update image model with CCD data
        self.image_model.set('ccd_data', ccd_data)
        
    def _handle_ptycho_data(self, ptycho_data):
        """Handle ptychography data."""
        # Update image model with ptycho data
        self.image_model.set('ptycho_data', ptycho_data)

    def _on_external_scan_detected(self, scan_type: str):
        """Called when scan data arrives while self.scanning is False.

        This covers two scenarios:
          1. The GUI starts up while the server is already running a scan.
          2. A remote scripting interface starts a scan while the GUI is idle.

        Sets the controller scanning state and emits external_scan_started so
        the view can configure itself exactly as if the user had pressed Begin.
        """
        if not self.scanning and scan_type:
            self.scanning = True
            self.image_model._data['motor_scan_x_data'] = []
            self.image_model._data['motor_scan_y_data'] = {}
            self.status_updated.emit(f"External scan detected: {scan_type}")
            self.external_scan_started.emit(scan_type)
            
    def get_available_motors(self) -> list:
        """Get list of available motors for display."""
        motor_info = self.motor_model.get('motor_info', {})
        motors = []
        
        # Sort motors by index
        motor_keys = list(motor_info.keys())
        if motor_keys:
            try:
                motor_indices = [(key, motor_info[key].get('index', 0)) for key in motor_keys]
                motor_indices.sort(key=lambda x: x[1])
                
                for motor_name, _ in motor_indices:
                    if motor_info[motor_name].get('display', False):
                        motors.append(motor_name)
            except (KeyError, TypeError):
                # Fallback if index sorting fails
                motors = [key for key in motor_keys if motor_info[key].get('display', False)]
                
        return motors
        
    def get_available_scan_types(self) -> list:
        """Get list of available scan types."""
        if hasattr(self.client, 'scanConfig') and self.client.scanConfig:
            scan_types = []
            for scan_type in self.client.scanConfig.keys():
                if self.client.scanConfig[scan_type].get("display", False):
                    scan_types.append(scan_type)
            return scan_types
        return ["Image", "Focus Scan", "Line Spectrum", "Single Motor", "Double Motor"]  # Default fallback
            
    def compile_scan_from_view(self, view) -> bool:
        """Compile scan configuration from view widgets."""
        try:
            # Clear existing regions
            self.scan_model.set('scan_regions', {})
            self.scan_model.set('energy_regions', {})
            
            # Get basic scan settings
            scan_type = view.ui.scanType.currentText()
            self.scan_model.set('scan_type', scan_type)
            self.scan_model.set('x_motor', view.ui.xMotorCombo.currentText())
            self.scan_model.set('y_motor', view.ui.yMotorCombo.currentText())
            self.scan_model.set('tiled', view.ui.tiledCheckbox.isChecked())
            self.scan_model.set('coarse_only', False)  # reset; validate_ranges may set True
            self.scan_model.set('defocus', view.ui.defocusCheckbox.isChecked())
            self.scan_model.set('autofocus', view.ui.autofocusCheckbox.isChecked())
            self.scan_model.set('doubleExposure', view.ui.doubleExposureCheckbox.isChecked() if hasattr(view.ui, 'doubleExposureCheckbox') else False)
            self.scan_model.set('proposal', view.ui.proposalComboBox.currentText() if view.ui.proposalComboBox.count() > 0 else '')
            self.scan_model.set('experimenters', view.ui.experimentersLineEdit.text())
            self.scan_model.set('sample', view.ui.sampleLineEdit.text())
            self.scan_model.set('comment', view.ui.commentEdit.toPlainText() if hasattr(view.ui, 'commentEdit') else '')
            self.scan_model.set('driver', self.client.scanConfig[scan_type]['driver'])
            self.scan_model.set('mode', self.client.scanConfig[scan_type].get('mode', 'continuousLine'))

            # DAQ list - get from scan config but filter by what's available in daqConfig
            if 'daq_list' in self.client.scanConfig[scan_type]:
                daq_list_str = self.client.scanConfig[scan_type]['daq_list']
                if isinstance(daq_list_str, str):
                    requested_daqs = daq_list_str.split(',')
                else:
                    requested_daqs = daq_list_str  # Already a list

                # Filter by what's actually available and recordable in daqConfig
                daq_list = []
                for daq_key in requested_daqs:
                    if daq_key in self.client.daqConfig:
                        if self.client.daqConfig[daq_key].get('record', True):
                            daq_list.append(daq_key)

                # If nothing passed the filter, use default
                if not daq_list:
                    daq_list = ['default']

                self.scan_model.set('daq_list', daq_list)
            else:
                # Build from daqConfig - all DAQs with record=True
                daq_list = []
                for daq_key in self.client.daqConfig.keys():
                    if self.client.daqConfig[daq_key].get('record', True):
                        daq_list.append(daq_key)

                if not daq_list:
                    daq_list = ['default']

                self.scan_model.set('daq_list', daq_list)

            # Loop scan parameters
            if hasattr(view.ui, 'loopCheckbox'):
                loop_scan_enabled = view.ui.loopCheckbox.isChecked()
                self.scan_model.set('loop_scan', loop_scan_enabled)
                if loop_scan_enabled:
                    try:
                        self.scan_model.set('loop_motor', view.ui.loopMotor.currentText())
                        self.scan_model.set('loop_center', float(view.ui.loopCenter.text()))
                        self.scan_model.set('loop_range', float(view.ui.loopRange.text()))
                        self.scan_model.set('loop_points', int(view.ui.loopPoints.text()))
                        self.scan_model.set('loop_step', float(view.ui.loopStepSize.text()))
                    except (ValueError, AttributeError) as e:
                        print(f"Warning: Could not read loop scan parameters: {e}")
                        self.scan_model.set('loop_scan', False)
            else:
                self.scan_model.set('loop_scan', False)

            # Collect scan regions from widgets
            for i, region_widget in enumerate(view.scan_region_widgets):
                region_name = f"Region{i + 1}"
                region_data = self._extract_scan_region_data(region_widget, view, scan_type)
                if region_data:
                    self.scan_model.add_scan_region(region_name, region_data)
            
            # Collect energy regions — handle energy list mode separately
            if (hasattr(view.ui, 'energyListCheckbox') and
                    view.ui.energyListCheckbox.isChecked()):
                # Parse comma/space/newline-separated energy values from the text edit
                raw = view.ui.energyListEdit.toPlainText().strip()
                tokens = re.split(r'[\s,;]+', raw)
                energies = []
                for tok in tokens:
                    try:
                        energies.append(float(tok))
                    except ValueError:
                        pass
                if not energies:
                    self.error_occurred.emit("Energy list is empty — enter at least one energy value")
                    return False
                dwell = getattr(view, '_energy_list_dwell', 1000.0)
                n = len(energies)
                step = (energies[-1] - energies[0]) / (n - 1) if n > 1 else 0.0
                self.scan_model.add_energy_region('EnergyRegion1', {
                    'start':      energies[0],
                    'stop':       energies[-1],
                    'step':       step,
                    'dwell':      dwell,
                    'n_energies': n,
                    'energy_list': energies,
                })
                self.scan_model.set('single_energy', False)
                self.scan_model.set('energy_list', energies)
            else:
                self.scan_model.set('energy_list', None)
                self.scan_model.set('single_energy', view.ui.toggleSingleEnergy.isChecked())
                for i, energy_widget in enumerate(view.energy_region_widgets):
                    region_name = f"EnergyRegion{i + 1}"
                    energy_data = self._extract_energy_region_data(energy_widget, view)
                    if energy_data:
                        self.scan_model.add_energy_region(region_name, energy_data)
                    
            # Calculate estimated time and include it in status message
            estimated_time = self.scan_model.calculate_estimated_time()
            if estimated_time < 100:
                time_str = f"{estimated_time:.2f} s"
            elif estimated_time < 3600:
                time_str = f"{estimated_time / 60:.2f} m"
            else:
                time_str = f"{estimated_time / 3600:.2f} hr"
            
            self.status_updated.emit(f"Scan compiled - Estimated time: {time_str}")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to compile scan: {str(e)}")
            return False
            
    def _extract_scan_region_data(self, region_widget, view, scan_type: str) -> dict:
        """Extract scan region data from widget."""
        try:
            if "Image" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                x_points = int(region_widget.ui.xNPoints.text() or 100)
                y_points = int(region_widget.ui.yNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
            elif "Focus" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                z_center = float(view.ui.focusCenterEdit.text())
                # For line-based focus scans, lineLengthEdit/linePointsEdit are authoritative;
                # fall back to the region widget values if those widgets are absent.
                if hasattr(view.ui, 'lineLengthEdit') and view.ui.lineLengthEdit.text():
                    x_range = float(view.ui.lineLengthEdit.text())
                else:
                    x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                z_range = float(view.ui.focusRangeEdit.text())
                z_points = int(view.ui.focusStepsEdit.text())
                if hasattr(view.ui, 'linePointsEdit') and view.ui.linePointsEdit.text():
                    x_points = int(view.ui.linePointsEdit.text())
                else:
                    x_points = int(region_widget.ui.xNPoints.text() or 100)
                y_points = int(region_widget.ui.yNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                z_step = z_range / z_points if z_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': z_center,
                    'zRange': z_range,
                    'zPoints': z_points,
                    'zStep': z_step,
                    'zStart': z_center - z_range / 2.0 + z_step / 2.0,
                    'zStop': z_center + z_range / 2.0 - z_step / 2.0,
                }
            elif "Line Spectrum" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                x_points = int(view.ui.linePointsEdit.text() or 100)
                y_points = 1
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
            elif "Single Motor" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                x_points = int(region_widget.ui.xNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': 0,
                    'xRange': x_range,
                    'yRange': 0,
                    'xPoints': x_points,
                    'yPoints': 1,
                    'xStep': x_step,
                    'yStep': 0,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': 0,
                    'yStop': 0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
            else:
                # Fallback for Double Motor and any other 2D scan types — same
                # layout as Image scan.
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                x_points = int(region_widget.ui.xNPoints.text() or 100)
                y_points = int(region_widget.ui.yNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
        except (ValueError, AttributeError) as e:
            print(f"Error extracting scan region data: {e}")
            return {}
            
    def _extract_energy_region_data(self, energy_widget, view) -> dict:
        """Extract energy region data from widget."""
        try:
            start_energy = float(energy_widget.energyDef.energyStart.text() or 280)
            stop_energy = float(energy_widget.energyDef.energyStop.text() or 320)
            energy_step = float(energy_widget.energyDef.energyStep.text() or 1)
            dwell_time = float(energy_widget.energyDef.dwellTime.text() or 1000)
            n_energies = int(energy_widget.energyDef.nEnergies.text() or 1)
            
            return {
                'start': start_energy,
                'stop': stop_energy,
                'step': energy_step,
                'dwell': dwell_time,
                'n_energies': n_energies
            }
        except (ValueError, AttributeError) as e:
            print(f"Error extracting energy region data: {e}")
            return {}

    def get_geometry_flags(self) -> dict:
        """Return the geometry feature flags from main_config.

        Keys: ``enable_coarse_only`` (bool).
        Defaults to True so that behaviour is unchanged when the key is absent.
        """
        geometry = {}
        try:
            geometry = self.client.main_config.get("geometry", {})
        except Exception:
            pass
        return {
            "enable_coarse_only": bool(geometry.get("enable_coarse_only", True)),
        }

    def start_scan(self) -> bool:
        """Start a scan based on current scan model."""
        if not self.scan_model.validate():
            self.error_occurred.emit("Invalid scan configuration")
            return False

        flags = self.get_geometry_flags()
        ok, msg = self.scan_model.validate_ranges(
            self.motor_model,
            enable_coarse_only=flags["enable_coarse_only"],
        )
        if not ok:
            self.error_occurred.emit(f"Scan range error: {msg}")
            return False
            
        if self.scanning:
            self.error_occurred.emit("Scan already in progress")
            return False
            
        try:
            scan_config = self.scan_model.to_dict()
            message = {"command": "scan", "scan": scan_config}
            self.message_queue.put(message)
            self.scanning = True
            # Reset motor scan data so a new Single Motor scan starts fresh
            self.image_model._data['motor_scan_x_data'] = []
            self.image_model._data['motor_scan_y_data'] = {}
            # Create stxm data object for Image-type scans (used by stack viewer live display)
            scan_type = self.scan_model.get('scan_type', '')
            if 'Image' in scan_type:
                try:
                    self._live_stxm = stxm(scan_config)
                except Exception as e:
                    print(f"Warning: could not create live stxm object: {e}")
                    self._live_stxm = None
            else:
                self._live_stxm = None
            self.status_updated.emit("Scan started")
            self.scan_state_changed.emit(True)  # Signal scan started
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to start scan: {str(e)}")
            return False
            
    def cancel_scan(self):
        """Cancel the current scan."""
        if self.scanning:
            message = {"command": "cancel"}
            self.message_queue.put(message)
            self.scanning = False
            self._scan_paused = False
            self.status_updated.emit("Scan cancelled")
            self.scan_state_changed.emit(False)  # Signal scan completed
        else:
            self.error_occurred.emit("No scan in progress")

    def pause_scan(self):
        """Toggle pause state on the current scan."""
        if self.scanning:
            self.message_queue.put({"command": "pause"})
            self._scan_paused = not self._scan_paused
            self.scan_pause_changed.emit(self._scan_paused)

    def reset_pause_state(self):
        """Clear local pause tracking (called when scan ends)."""
        if self._scan_paused:
            self._scan_paused = False
            self.scan_pause_changed.emit(False)

    def set_gate(self, mode: str):
        """Set the shutter/gate mode. mode must be 'auto', 'open', or 'closed'."""
        self.message_queue.put({"command": "setGate", "mode": mode})

    def _initialize_task_agent(self):
        """Create a TaskAgent if task_agent.enabled=true in main_config."""
        try:
            cfg = self.client.main_config.get("task_agent", {})
            if not cfg.get("enabled", False):
                return
            from ...controller.task_agent import TaskAgent
            self._task_agent = TaskAgent(self.client.main_config, self.client,
                                         image_model=self.image_model)
            self.status_updated.emit("TaskAgent initialized")
        except Exception as e:
            self.error_occurred.emit(f"TaskAgent init failed: {e}")

    def run_task(self, goal: str):
        """Submit a goal to the TaskAgent and run it in a background thread."""
        if self._task_agent is None:
            self.status_updated.emit("TaskAgent not configured (set task_agent.enabled=true)")
            return
        if self._agent_thread is not None and self._agent_thread.isRunning():
            self.status_updated.emit("TaskAgent is already running — please wait")
            return
        self._agent_thread = TaskAgentThread(self._task_agent, goal)
        self._agent_thread.message.connect(self.task_agent_status.emit)
        self._agent_thread.finished_text.connect(self.task_agent_done.emit)
        self._agent_thread.finished.connect(self._on_agent_thread_finished)
        self._agent_thread.start()
        self.task_agent_running.emit(True)

    task_agent_running = Signal(bool)   # True when thread starts, False when done

    def cancel_task(self):
        """Request cancellation of the running TaskAgent task."""
        if self._agent_thread and self._agent_thread.isRunning():
            self._agent_thread.cancel()
            self.task_agent_status.emit("[Cancellation requested — waiting for current step to finish]")

    def reset_task_history(self):
        """Clear the TaskAgent conversation history to start a fresh session."""
        if self._task_agent is not None:
            self._task_agent.reset_history()
        self.task_agent_status.emit("[Conversation cleared — ready for new topic]")

    def _on_agent_thread_finished(self):
        self._agent_thread = None
        self.task_agent_running.emit(False)

    def send_agent_query(self, text: str):
        """Route a free-form query to TaskAgent if available, otherwise to the server's intelligence module."""
        if self._task_agent is not None:
            self.run_task(text)
        else:
            self.message_queue.put({"command": "agent_query", "query": text})

    def move_motor(self, motor_name: str, position: float) -> bool:
        """Move a motor to the specified position."""
        if not self.motor_model.is_scan_position_valid(motor_name, position):
            self.error_occurred.emit(f"Position {position} out of range for {motor_name}")
            return False
            
        try:
            message = {
                "command": "moveMotor",
                "axis": motor_name,
                "pos": position
            }
            self.message_queue.put(message)
            self.motor_model.set_target_position(motor_name, position)
            self.status_updated.emit(f"Moving {motor_name} to {position}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to move motor: {str(e)}")
            return False
            
    def jog_motor(self, motor_name: str, step_size: float, direction: int) -> bool:
        """Jog a motor by the specified step size and direction."""
        current_pos = self.motor_model.get_position(motor_name)
        if current_pos is None:
            self.error_occurred.emit(f"Unknown position for {motor_name}")
            return False
            
        new_position = current_pos + (step_size * direction)
        return self.move_motor(motor_name, new_position)
        
    def update_motor_positions(self, positions: Dict[str, float]):
        """Update motor positions from server."""
        for motor_name, position in positions.items():
            self.motor_model.update_position(motor_name, position)
            
    def update_motor_status(self, status: Dict[str, bool]):
        """Update motor status from server."""
        for motor_name, is_moving in status.items():
            self.motor_model.update_status(motor_name, is_moving)
            
    def update_image_data(self, image_data: np.ndarray, metadata: Dict[str, Any]):
        """Update image data and metadata.  This is called by _handle_monitor_message and updates the image_model
        during the scan.  The model then emits the data changed signal."""

        # Collect all metadata into a single silent write (no per-key signal emissions).
        # set_current_image() is called last so the display fires once with all geometry
        # already in place.
        silent = {}

        if 'all_images' in metadata:
            silent['all_detector_images'] = metadata['all_images']
        if 'energy' in metadata:
            silent['current_energy'] = metadata['energy']
        if 'dwell' in metadata:
            silent['current_dwell'] = metadata['dwell']
        if 'scan_region' in metadata:
            silent['scan_region_index'] = metadata['scan_region']
        if 'energy_index' in metadata:
            silent['energy_index'] = metadata['energy_index']
        if 'type' in metadata:
            silent['scan_type'] = metadata['type']
        if 'scan_id' in metadata and metadata['scan_id']:
            scan_id = metadata['scan_id']
            silent['scan_file_name'] = scan_id
            self.scan_file_updated.emit(os.path.basename(scan_id))

        # Emit region / energy progress string (no model write needed)
        region = metadata.get('scan_region', '')
        energy_idx = metadata.get('energy_index', '')
        parts = []
        if region not in ('', None):
            n_regions = len(self.scan_model.get('scan_regions', {})) or 1
            # Extract the 1-based number from region name (e.g. "Region2" → 2)
            try:
                region_num = int(''.join(filter(str.isdigit, str(region))))
            except (ValueError, TypeError):
                region_num = 1
            parts.append(f"Region {region_num} of {n_regions}")
        if energy_idx not in ('', None):
            # Prefer the live stxm object (created once at scan-start from the
            # compiled config) so that recompiles of scan_model triggered by UI
            # interactions during the scan cannot produce a stale total.
            try:
                n_energies = len(self._live_stxm.energies["default"])
            except (AttributeError, KeyError, TypeError):
                energy_regions = self.scan_model.get('energy_regions', {})
                n_energies = sum(
                    v.get('n_energies', 1) for v in energy_regions.values()
                ) if energy_regions else 1
            parts.append(f"Energy {int(energy_idx) + 1} of {n_energies}")
        if parts:
            self.scan_progress_updated.emit(' | '.join(parts))

        # Compute image geometry.
        # Priority:
        #   1. Focus scan  → must use scan_model: y display axis = ZonePlateZ,
        #      so we need zCenter/zRange which the message does not carry.
        #   2. Message geometry → always accurate; correct for agent/script/tiled
        #      scans where scan_model may hold stale values from a previous GUI scan.
        #   3. scan_model region → fallback for drivers that omit geometry.
        scan_regions = self.scan_model.get('scan_regions', {})
        if 'scan_region' in metadata:
            region_name = metadata['scan_region']
            scan_type = self.scan_model.get('scan_type', '')
            region_data = (scan_regions.get(region_name, {})
                           if scan_regions else {})
            msg_has_geometry = metadata.get('msg_x_center') is not None

            if 'Focus' in scan_type and region_data:
                x_center = region_data.get('xCenter', 0.0)
                x_range  = region_data.get('xRange',  70.0)
                x_pts    = region_data.get('xPoints', 100)
                y_center = region_data.get('zCenter', 0.0)
                y_range  = region_data.get('zRange',  70.0)
                y_pts    = region_data.get('zPoints', 100)

            elif msg_has_geometry:
                x_center = metadata['msg_x_center']
                y_center = metadata['msg_y_center']
                x_range  = metadata['msg_x_range']
                y_range  = metadata['msg_y_range']
                x_pts    = metadata.get('msg_x_pts', 100)
                y_pts    = metadata.get('msg_y_pts', 100)

            elif region_data:
                x_center = region_data.get('xCenter', 0.0)
                x_range  = region_data.get('xRange',  70.0)
                x_pts    = region_data.get('xPoints', 100)
                y_center = region_data.get('yCenter', 0.0)
                y_range  = region_data.get('yRange',  70.0)
                y_pts    = region_data.get('yPoints', 100)

            else:
                region_name = None  # Nothing to update

            if region_name is not None:
                pixel_size_x = x_range / x_pts if x_pts > 0 else 1.0
                pixel_size_y = y_range / y_pts if y_pts > 0 else 1.0

                silent.update({
                    'x_center':    x_center,
                    'y_center':    y_center,
                    'x_range':     x_range,
                    'y_range':     y_range,
                    'image_scale': (pixel_size_x, pixel_size_y),
                    'pixel_size':  pixel_size_x,
                })

        # Write all metadata silently so geometry is ready before any display call.
        if self.PROFILE_IMAGE_UPDATE:
            _t0 = time.perf_counter()
        # Include the image in the silent write so it's always current in the model
        # (needed for channel switches and Image X/Y plots) without triggering a redraw.
        silent['current_image'] = image_data
        self.image_model.silent_update(silent)
        if self.PROFILE_IMAGE_UPDATE:
            self._prof_tick('3a_silent_update', time.perf_counter() - _t0)

        # Throttle the display: only call set_current_image (which triggers setImage
        # in pyqtgraph) when enough time has elapsed since the last repaint.
        # This prevents the Qt event loop from being saturated with repaint events
        # on fast point-mode scans while still keeping the display responsive.
        now = time.perf_counter()
        if now - self._last_display_time >= self._display_min_interval:
            self._last_display_time = now
            if self.PROFILE_IMAGE_UPDATE:
                _t0 = time.perf_counter()
            self.image_model.set_current_image(image_data)
            if self.PROFILE_IMAGE_UPDATE:
                self._prof_tick('3b_set_image+render', time.perf_counter() - _t0)
            
    def set_scan_type(self, scan_type: str):
        """Set the scan type and resolve its daq_list from scan.json."""
        self.scan_model.set('scan_type', scan_type)
        self.scan_model.set('daq_list', self._resolve_daq_list(scan_type))
        
    def add_scan_region(self, region_data: Dict[str, Any]) -> str:
        """Add a scan region and return its name."""
        region_count = len(self.scan_model.get('scan_regions', {}))
        region_name = f"Region{region_count + 1}"
        self.scan_model.add_scan_region(region_name, region_data)
        return region_name
        
    def remove_scan_region(self, region_name: str):
        """Remove a scan region."""
        self.scan_model.remove_scan_region(region_name)
        
    def add_energy_region(self, region_data: Dict[str, Any]) -> str:
        """Add an energy region and return its name."""
        region_count = len(self.scan_model.get('energy_regions', {}))
        region_name = f"EnergyRegion{region_count + 1}"
        self.scan_model.add_energy_region(region_name, region_data)
        return region_name
        
    def remove_energy_region(self, region_name: str):
        """Remove an energy region."""
        self.scan_model.remove_energy_region(region_name)
        
    def set_image_display_settings(self, settings: Dict[str, Any]):
        """Set image display settings."""
        for key, value in settings.items():
            self.image_model.set(key, value)
            
    def handle_mouse_click(self, x: float, y: float):
        """Handle mouse click on image."""
        self.image_model.update_cursor_position(x, y)
        
    def handle_motor_config_change(self, motor_name: str, config_type: str, value: float):
        """Handle motor configuration changes."""
        try:
            message = {
                "command": "changeMotorConfig",
                "data": {
                    "motor": motor_name,
                    "config": config_type,
                    "value": value
                }
            }
            self.message_queue.put(message)
            # Mirror the change into the local motor_info so the label stays current
            motor_info = self.motor_model.get('motor_info', {})
            if motor_name in motor_info:
                motor_info[motor_name][config_type] = value
                self.motor_model.set('motor_info', motor_info)
            self.status_updated.emit(f"Updated {motor_name} {config_type} to {value}")
        except Exception as e:
            self.error_occurred.emit(f"Failed to update motor config: {str(e)}")
            
    def save_scan_definition(self, filename: str) -> bool:
        """Save scan definition to file."""
        try:
            import json
            scan_config = self.scan_model.to_dict()
            with open(filename, 'w') as f:
                json.dump(scan_config, f, indent=4)
            self.status_updated.emit(f"Scan definition saved to {filename}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to save scan definition: {str(e)}")
            return False
            
    def load_scan_definition(self, filename: str) -> bool:
        """Load scan definition from file."""
        try:
            import json
            with open(filename, 'r') as f:
                scan_config = json.load(f)
            self.scan_model.update(scan_config)
            self.status_updated.emit(f"Scan definition loaded from {filename}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load scan definition: {str(e)}")
            return False
            
    def cleanup(self):
        """Stop threads and close connections. Safe to call from closeEvent or menu."""
        if self.exiting:
            return
        self.exiting = True
        if self.control_thread:
            self.control_thread.monitor = False
            self.message_queue.put("exit")
            self.control_thread.wait(2000)  # give the thread up to 2s to exit cleanly
        if self.client:
            self.client.disconnect()

    def quit_application(self):
        """Quit via the menu action."""
        self.cleanup()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
        
    def get_scan_model(self) -> ScanModel:
        """Get the scan model."""
        return self.scan_model
        
    def get_motor_model(self) -> MotorModel:
        """Get the motor model."""
        return self.motor_model

    def query_motor_history(self, motor_name: str, start_time: float,
                            end_time: float, limit: int = 10000) -> list:
        """
        Fetch historical motor position records from the server for a time range.

        Returns a list of dicts with 'timestamp' and 'actual_position' keys,
        sorted chronologically.  Returns [] on error or if not connected.
        """
        try:
            response = self.client.query_motor_history(
                motor_name, start_time, end_time, limit
            )
            if response and response.get("status"):
                records = response.get("data", [])
                records.sort(key=lambda r: r["timestamp"])
                return records
        except Exception as e:
            self.error_occurred.emit(f"Motor history query failed: {e}")
        return []
        
    def get_image_model(self) -> ImageModel:
        """Get the image model."""
        return self.image_model
        
    def refresh_motor_positions(self):
        """Manually refresh motor positions from client."""
        try:
            if hasattr(self.client, 'currentMotorPositions') and self.client.currentMotorPositions:
                for motor_name, position in self.client.currentMotorPositions.items():
                    if isinstance(position, (int, float)):
                        self.motor_model.update_position(motor_name, position)
                self.status_updated.emit("Motor positions refreshed")
        except Exception as e:
            self.error_occurred.emit(f"Failed to refresh motor positions: {str(e)}")
            
    def simulate_motor_updates(self):
        """Simulate motor position updates for testing."""
        import random
        test_motors = ['SampleX', 'SampleY', 'Energy', 'ZonePlateZ']
        
        for motor in test_motors:
            # Generate random position
            position = random.uniform(-100, 100)
            self.motor_model.update_position(motor, position)
            
            # Random status
            is_moving = random.choice([True, False])
            self.motor_model.update_status(motor, is_moving)
            
        self.status_updated.emit("Simulated motor updates completed")
        
    def simulate_monitor_data(self, num_points: int = 10):
        """Simulate monitor data updates for testing."""
        import random
        import time
        
        for _ in range(num_points):
            # Generate random monitor value
            monitor_value = random.uniform(0.1, 1.0)
            self.image_model.add_monitor_data(monitor_value, max_points=500)
            
            # Update DAQ display value
            daq_display_value = monitor_value * 10.0
            self.image_model.set('daq_current_value', daq_display_value)
            
            # Signals will be emitted automatically by model changes
            
            # Small delay to see the updates
            time.sleep(0.1)
            
        self.status_updated.emit(f"Simulated {num_points} monitor data points")