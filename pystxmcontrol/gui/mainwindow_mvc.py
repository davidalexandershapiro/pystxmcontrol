from pystxmcontrol.gui.mainwindow_UI import Ui_MainWindow
from pystxmcontrol.gui.controllers.main_controller import MainController
from pystxmcontrol.gui.energyDef import energyDefWidget
from pystxmcontrol.gui.scanDef import scanRegionDef
from pystxmcontrol.gui.data_browser_widget import DataBrowserWidget
from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import qdarktheme


class _MajorOnlyAxisItem(pg.AxisItem):
    """Bottom axis that generates only major ticks, suppressing minor sub-ticks."""

    def tickValues(self, minVal, maxVal, size):
        levels = super().tickValues(minVal, maxVal, size)
        return levels[:1] if levels else levels


class _SigFigAxisItem(pg.AxisItem):
    """Y AxisItem that shows tick values normalized to 2+ significant figures
    and annotates the common exponent as ×10ⁿ in the axis label."""

    # Unicode superscript digits and minus for exponent annotation
    _SUP = str.maketrans('0123456789-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁻')

    def __init__(self, orientation, **kwargs):
        # Must be set before super().__init__ because AxisItem.__init__ calls setLabel()
        self._base_label = ''
        self._sig_exp = None
        self._label_pending = False
        self._annotating = False
        super().__init__(orientation, **kwargs)

    # ------------------------------------------------------------------
    def setLabel(self, text='', units='', unitPrefix='', **args):
        if self._annotating:
            super().setLabel(text, units, unitPrefix, **args)
            return
        self._base_label = text or ''
        # If we already know the exponent, write the annotated text directly in
        # one shot so there is no intermediate bare-text repaint (no flicker).
        if self._sig_exp is not None and self._sig_exp != 0:
            sup = str(self._sig_exp).translate(self._SUP)
            annotated = f'{self._base_label}  ×10{sup}'
            self._annotating = True
            super().setLabel(annotated, units, unitPrefix, **args)
            self._annotating = False
        else:
            super().setLabel(text, units, unitPrefix, **args)

    # ------------------------------------------------------------------
    def tickStrings(self, values, scale, spacing):
        if not values:
            return []

        scaled = [v * scale for v in values]
        nonzero = [abs(v) for v in scaled if v != 0]

        if not nonzero:
            self._schedule_exp(0)
            return ['0'] * len(values)

        abs_max = max(nonzero)
        exp = int(np.floor(np.log10(abs_max))) if abs_max > 0 else 0
        factor = 10.0 ** exp

        # Decide how many decimal places are needed to distinguish adjacent ticks.
        # Always at least 1 (→ 2 sig figs for values in [1, 10)).
        scaled_spacing = abs(spacing * scale / factor) if factor != 0 else 1.0
        if scaled_spacing > 0:
            decimals = max(1, -int(np.floor(np.log10(scaled_spacing))))
        else:
            decimals = 1

        self._schedule_exp(exp)
        return [f'{v / factor:.{decimals}f}' for v in scaled]

    # ------------------------------------------------------------------
    def _schedule_exp(self, exp):
        if exp == self._sig_exp:
            return
        self._sig_exp = exp
        if not self._label_pending:
            self._label_pending = True
            QtCore.QTimer.singleShot(0, self._apply_exp_label)

    def _apply_exp_label(self):
        self._label_pending = False
        exp = self._sig_exp
        base = self._base_label
        if exp is None or exp == 0:
            text = base
        else:
            sup = str(exp).translate(self._SUP)
            text = f'{base}  ×10{sup}'
        self._annotating = True
        super().setLabel(text)
        self._annotating = False


class MainWindowMVC(QtWidgets.QMainWindow):
    """
    Main window class refactored to follow MVC architecture.
    This class is now primarily responsible for view-related operations.
    """
    
    def __init__(self, parent=None):
        super(MainWindowMVC, self).__init__(parent)
        
        # Set up the UI
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # Initialize the controller
        self.controller = MainController()
        
        # View-specific state
        self.scan_region_widgets = []
        self.energy_region_widgets = []
        self.roi_list = []
        self.pen_colors = self._generate_pen_colors()
        self.pen_styles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        
        # Image display objects
        self.horizontal_line = None
        self.vertical_line = None
        self.beam_position = None
        self.range_roi = None
        self.current_plot = None
        self.x_plot = None
        self.y_plot = None

        # Other randos
        self.consoleStr = ''
        self.static_style = "color: white;"
        self.moving_style = "color: red;"
        self.lineAngle = 0.0

        # Store current cursor coordinates from mouse movement
        self.current_cursor_x = 0.0   # updated continuously on mouse move
        self.current_cursor_y = 0.0
        self.crosshair_x = None       # set only when user clicks (crosshair placed)
        self.crosshair_y = None

        # Proposal management
        self.esaf_list = []
        self.participants_list = []

        # Additional data structures from mainwindow.py
        self.images = {}  # Dictionary of composite image items keyed by scanID:region
        self._composite_scan_counter = 0  # Increments each scan for unique composite keys
        self.currentCCDData = None
        self.currentRPIData = None
        self.ptychoXpixm = 1.0
        self.ptychoYpixm = 1.0
        self.scaleBarLength = 0.0
        self.currentLoadFile = ''
        self.currentDataDir = ''
        self.currentFile = ''

        # Focus scan calibration
        self.zonePlateCalibration = 0.0
        self.zonePlateOffset = 0.0
        self.cursorFocusZ = 0.0

        # Saved dwell for energy list mode (captured before region widgets are removed)
        self._energy_list_dwell = 1000.0
        self._saved_multi_energy = []   # saved energy region values while Single Energy is checked
        self._single_energy_active = False  # tracks current state to detect transitions

        # Scan parameters
        self.tiled_scan = False
        self.maxVelocity = 1.0
        self.velocity = 0.0
        self.focusRange = 100
        self.focusSteps = 50
        self.focusStepSize = 2.0
        self.lineLength = 10.0
        self.linePoints = 50
        self.xLineRange = 10.0
        self.yLineRange = 0.0
        self.last_scan = {}

        # Timing overheads
        self.pointOverhead = 0.01
        self.lineOverhead = 0.17
        self.energyOverhead = 5.0

        # Image scan types
        self.imageScanTypes = ["ptychographyGrid", "rasterLine", "continuousLine", 'continuousSpiral', 'point']
        
        # Load main.json from disk (independent of server connection)
        self._local_main_config = self._read_main_config_from_disk()

        # Initialize the controller
        if self.controller.initialize_client():
            self._populate_combo_boxes()
        else:
            # If client initialization fails, populate with defaults
            self._populate_default_combo_boxes()

        # Initialize the view — signals must be live before _apply_last_scan
        self._setup_ui_connections()
        self._setup_controller_connections()
        # Restore last scan params, then enforce deactivated startup state
        self._apply_last_scan(self.ui.scanType.currentText())
        self._deactivate_gui()
        self._initialize_display()
        self._create_range_roi()
        
    def _generate_pen_colors(self, count=100):
        """Generate random colors for ROIs."""
        colors = []
        for _ in range(count):
            color = list(np.random.choice(range(256), size=3))
            if sum(color) / 3. > 80.:
                colors.append(color)
        if colors:
            colors[0] = [255, 100, 180]  # Set first color
        return colors
        
    def _setup_ui_connections(self):
        """Connect UI signals to view methods."""
        # Menu actions
        self.ui.action_Open_Image_Data.triggered.connect(self.open_scan_file)
        self.ui.action_Save_Scan_Definition.triggered.connect(self.save_scan_definition)
        self.ui.action_Open_Energy_Definition.triggered.connect(self.open_energy_definition)
        self.ui.action_Open_Scan_Definition.triggered.connect(self.open_scan_definition)
        self.ui.action_light_theme.triggered.connect(self.set_light_theme)
        self.ui.action_dark_theme.triggered.connect(self.set_dark_theme)
        self.ui.action_init.triggered.connect(self.re_init)
        self.ui.action_load_config_from_server.triggered.connect(self.load_config)
        self.ui.action_quit.triggered.connect(self.controller.quit_application)
        
        # Add test menu items for debugging
        from PySide6.QtGui import QAction
        test_monitor_action = QAction("Test Monitor Plot", self)
        test_monitor_action.triggered.connect(self.test_monitor_plot)
        self.ui.menuHelp.addAction(test_monitor_action)
        
        test_scan_action = QAction("Test Scan Compilation", self)
        test_scan_action.triggered.connect(self.test_scan_compilation)
        self.ui.menuHelp.addAction(test_scan_action)

        set_password_action = QAction("Set Staff Password…", self)
        set_password_action.triggered.connect(self.set_staff_password)
        self.ui.menuFile.addAction(set_password_action)
        
        # Scan controls
        self.ui.scanType.currentIndexChanged.connect(self.on_scan_type_changed)
        self.ui.beginScanButton.clicked.connect(self.on_begin_scan)
        self.ui.cancelButton.clicked.connect(self.on_cancel_scan)
        
        # Motor controls
        self.ui.motorMover1Button.clicked.connect(self.on_move_motor1)
        self.ui.motorMover2Button.clicked.connect(self.on_move_motor2)
        self.ui.motorMover1Plus.clicked.connect(self.on_jog_motor1_plus)
        self.ui.motorMover1Minus.clicked.connect(self.on_jog_motor1_minus)
        self.ui.motorMover2Plus.clicked.connect(self.on_jog_motor2_plus)
        self.ui.motorMover2Minus.clicked.connect(self.on_jog_motor2_minus)
        self.ui.jogToggleButton.clicked.connect(self.toggle_jog_mode)
        
        # Energy controls
        self.ui.energyEdit.returnPressed.connect(self.on_energy_changed)
        self.ui.A0Edit.returnPressed.connect(self.on_a0_changed)

        # Additional beamline motor controls
        if hasattr(self.ui, 'A1Edit'):
            self.ui.A1Edit.returnPressed.connect(self.on_a1_changed)
        if hasattr(self.ui, 'dsEdit'):
            self.ui.dsEdit.returnPressed.connect(self.on_ds_changed)
        if hasattr(self.ui, 'ndsEdit'):
            self.ui.ndsEdit.returnPressed.connect(self.on_nds_changed)
        if hasattr(self.ui, 'm101Edit'):
            self.ui.m101Edit.returnPressed.connect(self.on_m101_changed)
        if hasattr(self.ui, 'fbkEdit'):
            self.ui.fbkEdit.returnPressed.connect(self.on_fbk_changed)
        if hasattr(self.ui, 'polEdit'):
            self.ui.polEdit.returnPressed.connect(self.on_pol_changed)
        if hasattr(self.ui, 'epuEdit'):
            self.ui.epuEdit.returnPressed.connect(self.on_epu_changed)
        if hasattr(self.ui, 'harSpin'):
            self.ui.harSpin.setEnabled(False)  # read-back only

        # Shutter control
        if hasattr(self.ui, 'shutterComboBox'):
            self.ui.shutterComboBox.currentIndexChanged.connect(self.on_shutter_changed)

        # Loop scan controls
        if hasattr(self.ui, 'loopCheckbox'):
            self.ui.loopCheckbox.stateChanged.connect(self.update_loop)
        if hasattr(self.ui, 'loopRange'):
            self.ui.loopRange.returnPressed.connect(self.update_loop)
        if hasattr(self.ui, 'loopPoints'):
            self.ui.loopPoints.returnPressed.connect(self.update_loop)

        # Additional scan controls
        if hasattr(self.ui, 'setCursor2ZeroButton'):
            self.ui.setCursor2ZeroButton.clicked.connect(self.set_cursor_to_zero)
        if hasattr(self.ui, 'beamToCursorButton'):
            self.ui.beamToCursorButton.clicked.connect(self.beam_to_cursor)
        if hasattr(self.ui, 'focusToCursorButton'):
            self.ui.focusToCursorButton.clicked.connect(self.on_focus_to_cursor)
        if hasattr(self.ui, 'motors2CursorButton'):
            self.ui.motors2CursorButton.clicked.connect(self.beam_to_cursor)
        if hasattr(self.ui, 'showBeamPosition'):
            self.ui.showBeamPosition.stateChanged.connect(self.toggle_beam_position)
        if hasattr(self.ui, 'firstEnergyButton'):
            self.ui.firstEnergyButton.clicked.connect(self.move_to_first_energy)
        
        # Focus and line parameter controls
        self.ui.focusStepsEdit.textChanged.connect(self.update_focus_step_size)
        self.ui.focusRangeEdit.textChanged.connect(self.update_focus_step_size)
        self.ui.linePointsEdit.textChanged.connect(self.update_line_parameters)
        self.ui.lineLengthEdit.textChanged.connect(self.update_line_parameters)
        self.ui.lineAngleEdit.textChanged.connect(self.update_line_parameters)
        
        # Image interactions
        self.ui.mainImage.scene.sigMouseMoved.connect(self.on_mouse_moved)
        self.ui.mainImage.scene.sigMouseClicked.connect(self.on_mouse_clicked)
        self.ui.mainPlot.scene().sigMouseMoved.connect(self.on_plot_mouse_moved)
        
        # Display controls
        self.ui.channelSelect.currentIndexChanged.connect(self.on_channel_changed)
        self.ui.plotType.currentIndexChanged.connect(self.on_plot_type_changed)
        self.ui.plotClearButton.clicked.connect(self.clear_plot)
        self.ui.clearImageButton.clicked.connect(self.clear_image)
        self.ui.removeLastImageButton.clicked.connect(self.remove_last_image)
        if hasattr(self.ui, 'compositeImageCheckbox'):
            self.ui.compositeImageCheckbox.stateChanged.connect(self.update_composite_image)
        
        # Region controls
        self.ui.scanRegSpinbox.valueChanged.connect(self.update_scan_regions)
        self.ui.energyRegSpinbox.valueChanged.connect(self.update_energy_regions)
        self.ui.roiCheckbox.stateChanged.connect(self.toggle_roi_display)
        self.ui.showRangeFinder.stateChanged.connect(self.toggle_range_roi_display)
        
        # Energy list controls
        self.ui.energyListCheckbox.stateChanged.connect(self.toggle_energy_list)
        self.ui.toggleSingleEnergy.stateChanged.connect(self.toggle_single_energy)
        
        # Proposal controls
        self.ui.proposalComboBox.activated.connect(lambda idx: self.on_proposal_changed())
        
    def _setup_controller_connections(self):
        """Connect controller signals to view update methods."""
        self.controller.motor_position_updated.connect(self.update_motor_position_display)
        self.controller.motor_status_updated.connect(self.update_motor_status_display)
        self.controller.image_updated.connect(self.update_image_display)
        self.controller.scan_progress_updated.connect(self.update_scan_progress_display)
        self.controller.scan_file_updated.connect(self.update_scan_file_display)
        self.controller.error_occurred.connect(self.show_error_message)
        self.controller.status_updated.connect(self.update_status_display)
        self.controller.monitor_data_updated.connect(self.update_monitor_plot)
        self.controller.daq_value_updated.connect(self.update_daq_value_display)
        self.controller.scan_state_changed.connect(self._set_scan_ui_state)
        self.controller.elapsed_time_updated.connect(self.update_elapsed_time_display)
        self.controller.motor_scan_updated.connect(self.update_motor_scan_plot)
        self.controller.live_data_ready.connect(self.ui.stack_viewer.recv_live_data)

    def _initialize_display(self):
        """Initialize the display elements."""
        # Set up image view with proper coordinate system
        # Create a default image that matches the motor coordinate system
        default_image = np.zeros((100, 100))
        
        # Set up the image view to display motor coordinates correctly
        # This matches the coordinate system used by the range ROI
        image_model = self.controller.get_image_model()
        x_center = image_model.get('x_center', 0.0)
        y_center = image_model.get('y_center', 0.0) 
        x_range = image_model.get('x_range', 70.0)
        y_range = image_model.get('y_range', 70.0)
        image_scale = image_model.get('image_scale', (0.7, 0.7))  # Match typical scan range
        
        # Position the image so its center aligns with motor coordinate center
        pos = (x_center - x_range / 2.0, y_center - y_range / 2.0)
        
        self.ui.mainImage.setImage(
            default_image,
            autoRange=False,  # Don't auto-range to preserve coordinate system
            pos=pos,
            scale=image_scale
        )

        # Invert Y axis so that moving the ROI upward gives more negative Y,
        # matching the microscope convention (moving sample down = field of view moves up).
        self.ui.mainImage.getView().invertY(True)
        
        # Set up default values
        self.ui.focusRangeEdit.setText('100')
        self.ui.focusStepsEdit.setText('50')
        self.ui.lineLengthEdit.setText('10')
        self.ui.lineAngleEdit.setText('0')
        self.ui.linePointsEdit.setText('50')
        
        # Set default pen color and style (do this early in case it's needed)
        self.default_pen = pg.mkPen(
            self.pen_colors[0],
            width=3,
            style=self.pen_styles[0]
        )

        # Calculate initial step sizes
        self.update_focus_step_size()
        self.update_line_step_size()

        # Initialize scan regions
        self.update_scan_regions()
        self.update_energy_regions()

        # Create initial ROIs
        #self._update_rois_from_regions()

        #set initial theme
        self.set_light_theme()

        #set the jog/move buttons
        self.toggle_jog_mode()
        self.ui.showRangeFinder.setChecked(False)
        self.toggle_range_roi_display()
        if hasattr(self.ui, 'compositeImageCheckbox'):
            self.ui.compositeImageCheckbox.setChecked(False)
        
        # Initialize energy list widget as hidden
        self.ui.energyListWidget.setVisible(False)
        
        # Initialize the Browser tab
        self._initialize_browser()

        # Style the mainPlot
        self._initialize_main_plot()

    def _initialize_main_plot(self):
        """Configure mainPlot: custom sig-fig axis, bounding frame, grid, theme."""
        pi = self.ui.mainPlot.getPlotItem()

        # Install the 2-sig-fig custom Y axis and major-only bottom axis
        pi.setAxisItems({
            'left':   _SigFigAxisItem('left'),
            'bottom': _MajorOnlyAxisItem('bottom'),
        })

        # Show top and right axes as bounding lines (no tick values)
        pi.showAxis('top')
        pi.showAxis('right')
        pi.getAxis('top').setStyle(showValues=False)
        pi.getAxis('right').setStyle(showValues=False)
        pi.getAxis('top').setHeight(10)
        pi.getAxis('right').setWidth(10)

        # Major-tick grid on both axes
        pi.showGrid(x=True, y=True, alpha=0.25)

        # Apply initial colour theme (light)
        self._apply_plot_theme(light=True)

    def _apply_plot_theme(self, light: bool):
        """Switch mainPlot between light (blue/white) and dark (green/black) themes."""
        plot = self.ui.mainPlot
        pi = plot.getPlotItem()

        if light:
            bg_color = 'w'
            ax_pen = pg.mkPen('k')
            line_color = (30, 100, 210)   # blue
        else:
            bg_color = 'k'
            ax_pen = pg.mkPen('w')
            line_color = (50, 205, 80)    # green

        plot.setBackground(bg_color)
        for axis_name in ('left', 'bottom', 'top', 'right'):
            ax = pi.getAxis(axis_name)
            ax.setPen(ax_pen)
            ax.setTextPen(ax_pen)

        self._main_plot_pen = pg.mkPen(color=line_color, width=1.5)

        # Update any live curves immediately
        if getattr(self, 'current_plot', None) is not None:
            self.current_plot.setPen(self._main_plot_pen)
        if getattr(self, 'x_plot', None) is not None:
            self.x_plot.setPen(self._main_plot_pen)

    def _initialize_browser(self):
        """Populate the Browser tab with the data file thumbnail browser."""
        self.browser_widget = DataBrowserWidget()
        layout = QtWidgets.QVBoxLayout(self.ui.tab_13)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser_widget)

    def _populate_combo_boxes(self):
        """Populate combo boxes with data from controller."""
        # Populate scan types - access client directly for now
        self.ui.scanType.clear()
        scan_types = self.controller.get_available_scan_types()
        for scan_type in scan_types:
            self.ui.scanType.addItem(scan_type)

        # Populate motor combo boxes - access client directly for now
        motors = self.controller.get_available_motors()
        
        # Clear existing items
        self.ui.motorMover1.clear()
        self.ui.motorMover2.clear()
        self.ui.xMotorCombo.clear()
        self.ui.yMotorCombo.clear()
        if hasattr(self.ui, 'loopMotor'):
            self.ui.loopMotor.clear()

        # Add motors to combo boxes
        for motor in motors:
            self.ui.motorMover1.addItem(motor)
            self.ui.motorMover2.addItem(motor)
            self.ui.xMotorCombo.addItem(motor)
            self.ui.yMotorCombo.addItem(motor)
            if hasattr(self.ui, 'loopMotor'):
                self.ui.loopMotor.addItem(motor)
            
        # Set default selections if motors are available
        if motors:
            # Try to set default motors
            if "SampleX" in motors:
                self.ui.motorMover1.setCurrentText("SampleX")
                self.ui.xMotorCombo.setCurrentText("SampleX")
            if "SampleY" in motors:
                self.ui.motorMover2.setCurrentText("SampleY")
                self.ui.yMotorCombo.setCurrentText("SampleY")
                
        # Populate channel selector from daqConfig; store DAQ key as item data
        self.ui.channelSelect.clear()
        if hasattr(self.controller, 'client') and hasattr(self.controller.client, 'daqConfig'):
            for daq_key, daq_cfg in self.controller.client.daqConfig.items():
                if daq_cfg.get("record", True):
                    daq_name = daq_cfg.get("name", daq_key)
                    self.ui.channelSelect.addItem(daq_name, daq_key)
        else:
            # Fallback — use key == name
            for name in ["Diode", "CCD", "RPI"]:
                self.ui.channelSelect.addItem(name, name)
            
        # Populate plot type selector
        if self.ui.plotType.count() == 0:
            self.ui.plotType.addItems(["Monitor", "Motor Scan", "Image X", "Image Y", "Image XY"])

        # Populate proposal combobox
        self._populate_proposal_combobox()

    def _populate_default_combo_boxes(self):
        """Populate combo boxes with default values when client is not available."""
        # Default scan types
        default_scan_types = ["Image", "Focus Scan", "Line Spectrum", "Single Motor", "Double Motor"]
        self.ui.scanType.clear()
        for scan_type in default_scan_types:
            self.ui.scanType.addItem(scan_type)
            
        # Default motors
        default_motors = ["SampleX", "SampleY", "Energy", "ZonePlateZ"]

        # Clear and populate motor combo boxes
        combo_list = [self.ui.motorMover1, self.ui.motorMover2, self.ui.xMotorCombo, self.ui.yMotorCombo]
        if hasattr(self.ui, 'loopMotor'):
            combo_list.append(self.ui.loopMotor)

        for combo in combo_list:
            combo.clear()
            for motor in default_motors:
                combo.addItem(motor)

        # Set default selections
        self.ui.motorMover1.setCurrentText("SampleX")
        self.ui.motorMover2.setCurrentText("SampleY")
        self.ui.xMotorCombo.setCurrentText("SampleX")
        self.ui.yMotorCombo.setCurrentText("SampleY")
        
        # Populate channel selector with defaults
        if self.ui.channelSelect.count() == 0:
            self.ui.channelSelect.addItems(["Diode", "CCD", "RPI"])
            
        if self.ui.plotType.count() == 0:
            self.ui.plotType.addItems(["Monitor", "Motor Scan", "Image X", "Image Y", "Image XY"])
            
        # Populate proposal combobox with defaults
        self._populate_proposal_combobox()
            
    def _create_range_roi(self):
        """Create the range ROI that shows motor scan limits."""
        try:
            # Get motor limits from controller
            motor_model = self.controller.get_motor_model()
            motor_info = motor_model.get('motor_info', {})
            
            # Get current scan motors
            x_motor = self.ui.xMotorCombo.currentText() or 'SampleX'
            y_motor = self.ui.yMotorCombo.currentText() or 'SampleY'
            
            # Get scan limits for these motors
            if x_motor in motor_info and y_motor in motor_info:
                x_min = motor_info[x_motor].get('minScanValue', -50.0)
                x_max = motor_info[x_motor].get('maxScanValue', 50.0)
                y_min = motor_info[y_motor].get('minScanValue', -50.0)
                y_max = motor_info[y_motor].get('maxScanValue', 50.0)
            else:
                # Default values if motor info not available
                x_min, x_max = -50.0, 50.0
                y_min, y_max = -50.0, 50.0
            
            # Create ROI pen (white dashed line)
            roi_pen = pg.mkPen((255, 255, 255), width=1, style=QtCore.Qt.DashLine)
            
            # Create the range ROI rectangle using motor coordinates directly
            # The image view should be configured to display motor coordinates
            self.range_roi = pg.RectROI(
                (x_min, y_min), 
                (x_max - x_min, y_max - y_min), 
                snapSize=0.0, 
                pen=roi_pen,
                rotatable=False, 
                resizable=False, 
                movable=False, 
                removable=False
            )
            
            # Remove the default handle (corner drag handle)
            handles = self.range_roi.getHandles()
            if handles:
                self.range_roi.removeHandle(handles[0])
            
            # Store range info in image model for coordinate transformations
            image_model = self.controller.get_image_model()
            image_model.set('scan_x_range', x_max - x_min)
            image_model.set('scan_y_range', y_max - y_min)
            image_model.set('scan_x_center', (x_min + x_max) / 2.0)
            image_model.set('scan_y_center', (y_min + y_max) / 2.0)
            image_model.set('x_range', x_max - x_min)
            image_model.set('y_range', y_max - y_min)
            image_model.set('x_center', (x_min + x_max) / 2.0)
            image_model.set('y_center', (y_min + y_max) / 2.0)
            
            # Set up initial image coordinate system to match motor coordinates
            # This ensures the range ROI is displayed correctly relative to any image
            center_x = (x_min + x_max) / 2.0
            center_y = (y_min + y_max) / 2.0
            range_x = x_max - x_min
            range_y = y_max - y_min
            
            # Set default image scale (can be overridden when actual images are displayed)
            image_model.set('image_scale', (0.1, 0.1))  # Default scale like original
            
        except Exception as e:
            print(f"Warning: Could not create range ROI: {e}")
            # Create a default range ROI if motor info fails
            roi_pen = pg.mkPen((255, 255, 255), width=1, style=QtCore.Qt.DashLine)
            self.range_roi = pg.RectROI(
                (-50, -50), (100, 100), 
                snapSize=0.0, pen=roi_pen,
                rotatable=False, resizable=False, 
                movable=False, removable=False
            )
            handles = self.range_roi.getHandles()
            if handles:
                self.range_roi.removeHandle(handles[0])
            
            # Store default values
            image_model = self.controller.get_image_model()
            image_model.set('scan_x_range', 100.0)
            image_model.set('scan_y_range', 100.0)
            image_model.set('x_range', 100.0)
            image_model.set('y_range', 100.0)
            image_model.set('x_center', 0.0)
            image_model.set('y_center', 0.0)
            image_model.set('image_scale', (0.1, 0.1))
            
    def _recreate_range_roi(self):
        """Recreate the range ROI when motor configuration changes."""
        # Remove existing range ROI if it exists
        if self.range_roi is not None:
            if self.range_roi in self.ui.mainImage.getView().allChildItems():
                self.ui.mainImage.removeItem(self.range_roi)
            self.range_roi = None
            
        # Create new range ROI
        self._create_range_roi()
        
        # Show it if the checkbox is checked
        if hasattr(self.ui, 'showRangeFinder') and self.ui.showRangeFinder.isChecked():
            self.toggle_range_roi_display()
        
    # View event handlers
    def _update_y_axis_label(self, scan_type: str):
        """Set Y/Z cursor label based on scan type (Focus scans use Z as vertical axis)."""
        if "Focus" in scan_type:
            html = ("<html><head/><body><p><span style=\" font-weight:700;\">"
                    "Z:</span></p></body></html>")
        else:
            html = ("<html><head/><body><p><span style=\" font-weight:700;\">"
                    "Y:</span></p></body></html>")
        self.ui.label_23.setText(html)

    def on_scan_type_changed(self):
        """Handle scan type change."""
        scan_type = self.ui.scanType.currentText()
        self.controller.set_scan_type(scan_type)
        self._update_ui_for_scan_type(scan_type)
        self._update_y_axis_label(scan_type)

        # Default ROI checkbox to checked when switching to an Image scan type
        if "Image" in scan_type:
            self.ui.roiCheckbox.setChecked(True)

        # Restore last-used values for this scan type
        self._apply_last_scan(scan_type)

        # For Focus scans, always initialise the Z centre to the current ZonePlateZ
        # position (i.e. where the microscope is focused right now).  This must run
        # after _apply_last_scan so the current motor position takes precedence over
        # whatever was saved in main.json.
        if "Focus" in scan_type and hasattr(self.ui, 'focusCenterEdit'):
            try:
                motor_positions = self.controller.get_motor_model().get('current_positions', {})
                zone_plate_z = motor_positions.get('ZonePlateZ', 0)
                self.ui.focusCenterEdit.setText(f"{zone_plate_z:.2f}")
            except Exception:
                pass

        # Recreate range ROI with updated motor configuration
        self._recreate_range_roi()

        # Update scan ROIs for new scan type
        self._update_rois_from_regions()
        
    def on_begin_scan(self):
        """Handle begin scan button click."""
        # First compile scan configuration from UI widgets
        if self.controller.compile_scan_from_view(self):
            # Then start the scan
            success = self.controller.start_scan()
            if success:
                self._set_scan_ui_state(scanning=True)
        else:
            self.show_error_message("Failed to compile scan configuration")
            
    def on_cancel_scan(self):
        """Handle cancel scan button click."""
        self.controller.cancel_scan()
        self._set_scan_ui_state(scanning=False)
        
    def on_move_motor1(self):
        """Handle motor 1 move button click."""
        motor_name = self.ui.motorMover1.currentText()
        try:
            position = float(self.ui.motorMover1Edit.text())
            self.controller.move_motor(motor_name, position)
        except ValueError:
            self.show_error_message("Invalid position value")
            
    def on_move_motor2(self):
        """Handle motor 2 move button click."""
        motor_name = self.ui.motorMover2.currentText()
        try:
            position = float(self.ui.motorMover2Edit.text())
            self.controller.move_motor(motor_name, position)
        except ValueError:
            self.show_error_message("Invalid position value")
            
    def on_jog_motor1_plus(self):
        """Handle motor 1 jog plus button click."""
        motor_name = self.ui.motorMover1.currentText()
        try:
            step_size = float(self.ui.motorMover1Edit.text())
            self.controller.jog_motor(motor_name, step_size, 1)
        except ValueError:
            self.show_error_message("Invalid step size value")
            
    def on_jog_motor1_minus(self):
        """Handle motor 1 jog minus button click."""
        motor_name = self.ui.motorMover1.currentText()
        try:
            step_size = float(self.ui.motorMover1Edit.text())
            self.controller.jog_motor(motor_name, step_size, -1)
        except ValueError:
            self.show_error_message("Invalid step size value")
            
    def on_jog_motor2_plus(self):
        """Handle motor 2 jog plus button click."""
        motor_name = self.ui.motorMover2.currentText()
        try:
            step_size = float(self.ui.motorMover2Edit.text())
            self.controller.jog_motor(motor_name, step_size, 1)
        except ValueError:
            self.show_error_message("Invalid step size value")
            
    def on_jog_motor2_minus(self):
        """Handle motor 2 jog minus button click."""
        motor_name = self.ui.motorMover2.currentText()
        try:
            step_size = float(self.ui.motorMover2Edit.text())
            self.controller.jog_motor(motor_name, step_size, -1)
        except ValueError:
            self.show_error_message("Invalid step size value")
            
    def on_energy_changed(self):
        """Handle energy change."""
        try:
            energy = float(self.ui.energyEdit.text())
            self.controller.move_motor("Energy", energy)
        except ValueError:
            self.show_error_message("Invalid energy value")
            
    def on_a0_changed(self):
        """Handle A0 change."""
        try:
            a0_value = float(self.ui.A0Edit.text())
            self.controller.handle_motor_config_change("Energy", "A0", a0_value)
            self.ui.A0Label.setText(f"{int(a0_value)}")
        except ValueError:
            self.show_error_message("Invalid A0 value")

    def on_a1_changed(self):
        """Handle A1 change."""
        try:
            a1_value = float(self.ui.A1Edit.text())
            self.controller.handle_motor_config_change("Energy", "A1", a1_value)
        except ValueError:
            self.show_error_message("Invalid A1 value")

    def on_ds_changed(self):
        """Handle dispersive slit change."""
        try:
            value = float(self.ui.dsEdit.text())
            self.controller.move_motor("DISPERSIVE_SLIT", value)
        except ValueError:
            self.show_error_message("Invalid dispersive slit value")

    def on_nds_changed(self):
        """Handle non-dispersive slit change."""
        try:
            value = float(self.ui.ndsEdit.text())
            self.controller.move_motor("NONDISPERSIVE_SLIT", value)
        except ValueError:
            self.show_error_message("Invalid non-dispersive slit value")

    def on_m101_changed(self):
        """Handle M101 pitch change."""
        try:
            value = float(self.ui.m101Edit.text())
            self.controller.move_motor("M101PITCH", value)
        except ValueError:
            self.show_error_message("Invalid M101 pitch value")

    def on_fbk_changed(self):
        """Handle feedback offset change."""
        try:
            value = float(self.ui.fbkEdit.text())
            self.controller.move_motor("FBKOFFSET", value)
        except ValueError:
            self.show_error_message("Invalid feedback offset value")

    def on_pol_changed(self):
        """Handle polarization change."""
        try:
            value = float(self.ui.polEdit.text())
            self.controller.move_motor("POLARIZATION", value)
        except ValueError:
            self.show_error_message("Invalid polarization value")

    def on_epu_changed(self):
        """Handle EPU offset change."""
        try:
            value = float(self.ui.epuEdit.text())
            self.controller.move_motor("EPUOFFSET", value)
        except ValueError:
            self.show_error_message("Invalid EPU offset value")

    def on_harmonic_changed(self):
        """Handle harmonic change."""
        value = self.ui.harSpin.value()
        self.controller.move_motor("HARMONIC", float(value))

    def on_shutter_changed(self):
        """Handle shutter control change."""
        shutter_text = self.ui.shutterComboBox.currentText()
        if shutter_text == "Shutter Auto":
            mode = "auto"
        elif shutter_text == "Shutter Open":
            mode = "open"
        elif shutter_text == "Shutter Closed":
            mode = "closed"
        else:
            return
        # Send gate command through controller
        if hasattr(self.controller, 'set_gate'):
            self.controller.set_gate(mode)
            
    def update_focus_step_size(self):
        """Update focus step size label when range or steps change."""
        try:
            focus_range = float(self.ui.focusRangeEdit.text())
            focus_steps = float(self.ui.focusStepsEdit.text())
            if focus_steps > 0:
                step_size = focus_range / focus_steps
                self.ui.focusStepSizeLabel.setText(f"{step_size:.2f}")
        except (ValueError, ZeroDivisionError):
            self.ui.focusStepSizeLabel.setText("0.00")
            
    def update_line_step_size(self):
        """Update line step size label when length or points change."""
        try:
            line_length = float(self.ui.lineLengthEdit.text())
            line_points = float(self.ui.linePointsEdit.text())
            if line_points > 0:
                step_size = line_length / line_points
                self.ui.lineStepSizeLabel.setText(f"{step_size:.3f}")
        except (ValueError, ZeroDivisionError):
            self.ui.lineStepSizeLabel.setText("0.000")
            
    def update_line_parameters(self):
        """Update line parameters including step size and angle."""
        # Update step size
        self.update_line_step_size()

        # Store line angle for other calculations if needed
        try:
            self.lineAngle = float(self.ui.lineAngleEdit.text())
        except ValueError:
            self.lineAngle = 0.0

        self.update_line_roi()

    def update_loop(self):
        """Update loop scan parameters and calculate step size."""
        if not hasattr(self.ui, 'loopRange'):
            return
        try:
            r = float(self.ui.loopRange.text())
            p = int(self.ui.loopPoints.text())
            c = float(self.ui.loopCenter.text())
        except:
            if hasattr(self.ui, 'loopCheckbox'):
                self.ui.loopCheckbox.setChecked(False)
            self.show_error_message("Please check the values entered for the Center, Range and Points")
        else:
            if p > 1:
                s = np.round(r / (p-1), 3)
                if hasattr(self.ui, 'loopStepSize'):
                    self.ui.loopStepSize.setText(str(s))

    def set_cursor_to_zero(self):
        """Set cursor position to zero coordinates by adjusting motor offsets."""
        if self.crosshair_x is None or self.crosshair_y is None:
            self.show_error_message("Please click on the image first to set cursor position")
            return

        scan_type = self.ui.scanType.currentText()
        if "Image" not in scan_type and "Double Motor" not in scan_type:
            self.show_error_message("This function only works for Image and Double Motor scans")
            return

        x = round(self.crosshair_x, 2)
        y = round(self.crosshair_y, 2)

        # Get current motors
        motor_model = self.controller.get_motor_model()
        motor_info = motor_model.get('motor_info', {})

        x_motor = self.ui.xMotorCombo.currentText() or 'SampleX'
        y_motor = self.ui.yMotorCombo.currentText() or 'SampleY'

        # Get current offsets
        x_current_offset = motor_info.get(x_motor, {}).get('offset', 0)
        y_current_offset = motor_info.get(y_motor, {}).get('offset', 0)

        # Confirm with user
        result = self.warning_popup(f"Set {x_motor} = {x} and {y_motor} = {y} to 0?")
        if result:
            message = f"Setting {x_motor} = {x} and {y_motor} = {y} to 0"
            self.update_status_display(message)

            # Update offsets
            self.controller.handle_motor_config_change(x_motor, "offset", x_current_offset - x)
            self.controller.handle_motor_config_change(y_motor, "offset", y_current_offset - y)

            # Remove crosshairs
            if self.horizontal_line:
                self.ui.mainImage.removeItem(self.horizontal_line)
                self.horizontal_line = None
            if self.vertical_line:
                self.ui.mainImage.removeItem(self.vertical_line)
                self.vertical_line = None

    def beam_to_cursor(self):
        """Move motors to the crosshair (clicked) position."""
        if self.controller.get_scan_model().get('scanning', False):
            return

        if self.crosshair_x is None or self.crosshair_y is None:
            self.show_error_message("Please click on the image first to set cursor position")
            return

        x_motor = self.ui.xMotorCombo.currentText() or 'SampleX'
        y_motor = self.ui.yMotorCombo.currentText() or 'SampleY'

        self.controller.move_motor(x_motor, self.crosshair_x)
        self.controller.move_motor(y_motor, self.crosshair_y)

    def on_focus_to_cursor(self):
        """Calibrate focus using the Z position the user clicked in a Focus scan image.

        Mirrors setFocusZ() from the legacy mainwindow.py:
        - OSA Focus or uncalibrated A0 → adjust ZonePlateZ offset so the clicked
          Z position maps to the zone-plate calibration position.
        - Regular Focus with calibrated A0 → adjust A0 (and SampleZ offset) instead.
        In both cases, move ZonePlateZ to the calibration position afterwards.
        """
        self.ui.focusToCursorButton.setEnabled(False)

        if self.crosshair_y is None:
            self.show_error_message("Please click on the image first to set cursor position")
            return

        cursor_focus_z = self.crosshair_y  # y-axis = Z in Focus scan images; use clicked position

        image_model = self.controller.get_image_model()
        zone_plate_calibration = image_model.get('zonePlateCalibration', 0.0)
        zone_plate_offset = image_model.get('zonePlateOffset', 0.0)

        motor_model = self.controller.get_motor_model()
        motor_info = motor_model.get('motor_info', {})
        a0 = motor_info.get('Energy', {}).get('A0', 0.0)
        current_positions = motor_model.get('current_positions', {})

        scan_type = image_model.get('scan_type', '')
        a0_calibrated = False
        try:
            a0_calibrated = self.controller.client.main_config.get(
                'geometry', {}).get('A0_calibrated', False)
        except Exception:
            pass

        if "OSA" in scan_type or not a0_calibrated:
            # Adjust ZonePlateZ offset to bring clicked position to calibration point
            offset_delta = zone_plate_calibration - a0 - cursor_focus_z
            new_offset = zone_plate_offset + offset_delta
            print(f"setFocusZ: setting ZonePlateZ offset to {new_offset:.3f}")
            self.controller.handle_motor_config_change("ZonePlateZ", "offset", new_offset)
        else:
            # Calibrated A0 path: adjust A0 and SampleZ offset
            new_a0 = a0 - (zone_plate_calibration - cursor_focus_z)
            sample_z = current_positions.get('SampleZ', 0.0)
            sample_z_offset = motor_info.get('SampleZ', {}).get('offset', 0.0)
            new_sample_z_offset = sample_z_offset + (new_a0 - sample_z)
            print(f"setFocusZ: setting A0 to {new_a0:.3f}, SampleZ offset to {new_sample_z_offset:.3f}")
            self.controller.handle_motor_config_change("SampleZ", "offset", new_sample_z_offset)
            self.controller.handle_motor_config_change("Energy", "A0", new_a0)

        # Move ZonePlateZ to the calibration position
        self.controller.move_motor("ZonePlateZ", zone_plate_calibration)

        # Remove crosshairs
        if self.horizontal_line:
            self.ui.mainImage.removeItem(self.horizontal_line)
            self.horizontal_line = None
        if self.vertical_line:
            self.ui.mainImage.removeItem(self.vertical_line)
            self.vertical_line = None

    def toggle_beam_position(self):
        """Toggle beam position display on image."""
        # This will be implemented when beam position ROI is created
        pass

    def move_to_first_energy(self):
        """Move Energy motor to first energy in energy region list."""
        if self.energy_region_widgets:
            try:
                first_energy = float(self.energy_region_widgets[0].energyDef.energyStart.text())
                self.controller.move_motor("Energy", first_energy)
            except (ValueError, AttributeError) as e:
                self.show_error_message(f"Cannot move to first energy: {e}")

    def update_line_roi(self):
        """Update line ROI based on current line parameters."""
        # Only update if we have scan regions
        if not self.scan_region_widgets:
            return
        self._clear_rois()
        roi = self._calculate_line_roi()
        roi.sigRegionChanged.connect(self._update_region_from_roi)
        self.roi_list.append(roi)
        self._show_rois()
            
    def on_mouse_moved(self, pos):
        """Handle mouse movement over image."""
        # Convert scene position directly to view (motor) coordinates using the
        # ViewBox transform — this is always correct regardless of image_scale or
        # which scan type is active.
        view_pos = self.ui.mainImage.getView().mapSceneToView(pos)
        x_real = view_pos.x()
        y_real = view_pos.y()

        # Store current cursor coordinates for use in click events
        self.current_cursor_x = x_real
        self.current_cursor_y = y_real

        # Update cursor position labels.
        # For Focus scans the vertical image axis is Z, so relabel accordingly.
        displayed_scan_type = self.controller.get_image_model().get('scan_type', '')
        self._update_y_axis_label(displayed_scan_type)
        self.ui.xCursorPos.setText(f"{x_real:.3f}")
        self.ui.yCursorPos.setText(f"{y_real:.3f}")

        # Calculate and update scale bar using the ImageItem's actual pixel size
        if hasattr(self.ui, 'scaleBarLength') and hasattr(self.ui.mainImage, 'imageItem'):
            try:
                pixel_size = self.ui.mainImage.imageItem.pixelSize()[0]
                if pixel_size > 0:
                    self.scaleBarLength = np.round(100. / pixel_size, 3)
                    if self.scaleBarLength < 1.:
                        scale_text = f"{self.scaleBarLength * 1000.} nm"
                    else:
                        scale_text = f"{self.scaleBarLength} um"
                    self.ui.scaleBarLength.setText(scale_text)
            except:
                pass

        # Read image intensity at cursor position (needs pixel coords from ImageItem)
        scene_pos = self.ui.mainImage.getImageItem().mapFromScene(pos)
        self._update_cursor_intensity(scene_pos)

        # Update Image X/Y/XY line plots if that mode is active
        self._show_image_line_plots(scene_pos)
        
    def _update_cursor_intensity(self, scene_pos):
        """Update cursor intensity from image data."""
        try:
            # Get current image from the image model
            current_image = self.controller.get_image_model().get_current_image()
            
            if current_image is not None:
                # Convert scene position to image array indices
                row = int(round(scene_pos.x()))
                col = int(round(scene_pos.y()))
                
                # Get image shape
                if len(current_image.shape) == 2:
                    y_size, x_size = current_image.shape
                    # Check bounds
                    if 0 <= row < x_size and 0 <= col < y_size:
                        # Read intensity (note: image is transposed for display)
                        intensity = current_image[col, row]
                        self.ui.cursorIntensity.setText(f"{intensity:.3f}")
                    else:
                        self.ui.cursorIntensity.setText("0")
                elif len(current_image.shape) == 3:
                    z_size, y_size, x_size = current_image.shape
                    frame_index = getattr(self.ui.mainImage, 'currentIndex', 0)
                    # Check bounds
                    if 0 <= row < x_size and 0 <= col < y_size and 0 <= frame_index < z_size:
                        # Read intensity from current frame
                        intensity = current_image[frame_index, col, row]
                        self.ui.cursorIntensity.setText(f"{intensity:.3f}")
                    else:
                        self.ui.cursorIntensity.setText("0")
                else:
                    self.ui.cursorIntensity.setText("0")
            else:
                self.ui.cursorIntensity.setText("0")
                
        except (IndexError, ValueError, AttributeError):
            self.ui.cursorIntensity.setText("0")
        
    def on_mouse_clicked(self, pos):
        """Handle mouse click on image."""
        image_model = self.controller.get_image_model()
        if self.ui.channelSelect.currentText() == "CCD":
            return
            
        # Use the coordinates from the last mouse movement event
        # This avoids coordinate transformation issues when clicking on ROIs
        x_real = self.current_cursor_x
        y_real = self.current_cursor_y
        
        # Pass real coordinates to controller for cursor position tracking
        self.controller.handle_mouse_click(x_real, y_real)

        # Activate action buttons as appropriate for the scan type
        displayed_type = image_model.get('scan_type', '')
        if not self.controller.scanning:
            if "Image" in displayed_type:
                self.ui.motors2CursorButton.setEnabled(True)
            if "Focus" in displayed_type:
                self.ui.focusToCursorButton.setEnabled(True)
        
        # Store the clicked position separately — this is what action buttons use,
        # as opposed to current_cursor_x/y which follow the mouse continuously.
        self.crosshair_x = x_real
        self.crosshair_y = y_real

        # Update crosshair using real coordinates (this is what the user sees)
        self._update_crosshair(x_real, y_real)
        
    def on_plot_mouse_moved(self, pos):
        """Handle mouse movement over plot."""        
        vb = self.ui.mainPlot.getPlotItem().vb
        idx = vb.mapSceneToView(pos).x()
        if self.ui.plotType.currentText() == "Motor Scan":
            motor_data = self.controller.get_image_model().get('motor_scan_data', [])
            xdata = idx
            ydata = np.interp(idx,motor_data[1],motor_data[0])
        elif self.ui.plotType.currentText() == "Monitor":
            _im = self.controller.get_image_model()
            monitor_data = _im.get_monitor_data(_im.get('channel_key', 'default'))
            xdata = idx
            ydata = np.interp(idx,np.arange(len(monitor_data)),monitor_data)
        self.ui.xCursorPos.setText(str(round(xdata,3)))
        self.ui.cursorIntensity.setText(str(round(ydata,3)))
        
    def on_channel_changed(self):
        """Handle channel selection change."""
        channel = self.ui.channelSelect.currentText()
        # itemData holds the raw DAQ key; fall back to the display name if unset
        channel_key = self.ui.channelSelect.currentData() or channel
        self.controller.set_image_display_settings({
            'channel_select': channel,
            'channel_key':    channel_key,
        })
        # Re-display whichever image is already stored for the new channel
        self.controller.refresh_channel_image()
        
    def on_plot_type_changed(self):
        """Handle plot type change."""
        plot_type = self.ui.plotType.currentText()
        settings = {'plot_type': plot_type}
        self.controller.set_image_display_settings(settings)
        
        # Clear existing plots (including Image X/Y line plots)
        if self.current_plot:
            self.ui.mainPlot.removeItem(self.current_plot)
            self.current_plot = None
        if self.x_plot:
            self.ui.mainPlot.removeItem(self.x_plot)
            self.x_plot = None
        if self.y_plot:
            self.ui.mainPlot.removeItem(self.y_plot)
            self.y_plot = None

        # Update to new plot type
        self._update_plot_display()
        
    # View update methods (called by controller signals)
    def update_motor_position_display(self, motor_name: str, position: float):
        """Update motor position display."""
        # Update motor position labels based on motor name
        if motor_name == self.ui.motorMover1.currentText():
            self.ui.motorMover1Pos.setText(f"{position:.3f}")
        if motor_name == self.ui.motorMover2.currentText():
            self.ui.motorMover2Pos.setText(f"{position:.3f}")
            
        # Update specific motor labels
        if motor_name == "Energy":
            self.ui.energyLabel.setText(f"{position:.1f} eV")
            self.ui.energyLabel_2.setText(f"{position:.1f} eV")
        elif motor_name == "DISPERSIVE_SLIT":
            self.ui.dsLabel.setText(f"{position:.1f}")
        elif motor_name == "NONDISPERSIVE_SLIT":
            self.ui.ndsLabel.setText(f"{position:.1f}")
        elif motor_name == "POLARIZATION":
            self.ui.polLabel.setText(f"{position:.2f}")
        elif motor_name == "M101PITCH":
            self.ui.m101Label.setText(f"{position:.2f}")
        elif motor_name == "FBKOFFSET":
            self.ui.fbkLabel.setText(f"{position:.2f}")
        elif motor_name == "EPUOFFSET":
            self.ui.epuLabel.setText(f"{position:.2f}")
        elif motor_name == "HARMONIC":
            try:
                self.ui.harSpin.setValue(int(position))
            except:
                pass
                
        # A0/A1 labels are updated by on_a0_changed / handle_motor_config_change,
        # not here — updating them on every motor position message is unnecessary overhead.
            
    def update_motor_status_display(self, motor_name: str, is_moving: bool):
        """Update motor status display."""
        # Define styles for moving and static motors
        #moving_style = "color: red;"
        #static_style = "color: black;"
        style = self.moving_style if is_moving else self.static_style
        
        # Update motor mover position labels
        if motor_name == self.ui.motorMover1.currentText():
            self.ui.motorMover1Pos.setStyleSheet(style)
        if motor_name == self.ui.motorMover2.currentText():
            self.ui.motorMover2Pos.setStyleSheet(style)
            
        # Update specific motor status labels
        if motor_name == "Energy":
            self.ui.energyLabel.setStyleSheet(style)
            self.ui.energyLabel_2.setStyleSheet(style)
        elif motor_name == "DISPERSIVE_SLIT":
            self.ui.dsLabel.setStyleSheet(style)
        elif motor_name == "NONDISPERSIVE_SLIT":
            self.ui.ndsLabel.setStyleSheet(style)
        elif motor_name == "POLARIZATION":
            self.ui.polLabel.setStyleSheet(style)
        elif motor_name == "M101PITCH":
            self.ui.m101Label.setStyleSheet(style)
        elif motor_name == "FBKOFFSET":
            self.ui.fbkLabel.setStyleSheet(style)
        elif motor_name == "EPUOFFSET":
            self.ui.epuLabel.setStyleSheet(style)
            
    def update_image_display(self, image_data):
        """Update image display."""
        if image_data is None:
            return

        # Handle case where image_data might be a dict (from scan messages)
        if isinstance(image_data, dict):
            channel_key = self.controller.get_image_model().get('channel_key', 'default')
            img = image_data.get(channel_key)
            if img is None:
                img = image_data.get('default')
            if img is None:
                return
            image_data = img

        # Verify we have a numpy array (None is expected when zmq recv fails)
        if not isinstance(image_data, np.ndarray):
            return

        # Get current image geometry settings to maintain coordinate system
        image_model = self.controller.get_image_model()
        x_center = image_model.get('x_center', 0.0)
        y_center = image_model.get('y_center', 0.0)
        x_range = image_model.get('x_range', 70.0)
        y_range = image_model.get('y_range', 70.0)
        image_scale = image_model.get('image_scale', (0.7, 0.7))

        scan_type = image_model.get('scan_type', '')

        # Image scans: lock aspect ratio so physical proportions are preserved.
        # Focus scans: unlock so the image always stretches to fill the viewport.
        self.ui.mainImage.getView().setAspectLocked("Focus" not in scan_type)

        if "Spectrum" in scan_type:
            energies = np.array(image_model.get('energy_list', [700, 720]))
            if energies.size > 0:
                image_scale = [image_model.get('x_pts', 50)/energies.size, 1.0]
                y_center = 0.0
                y_range = energies.max() - energies.min()
                image_data = image_data.T

        # Calculate position to center the image at the motor coordinate center
        pos = (x_center - x_range / 2.0, y_center - y_range / 2.0)

        auto_range = self.ui.autorangeCheckbox.isChecked()
        auto_scale = self.ui.autoscaleCheckbox.isChecked()

        # Compute levels from non-zero data when autoscale is on
        levels = None
        if auto_scale:
            pos_data = image_data[image_data > 0]
            if pos_data.size > 0:
                levels = [float(pos_data.min()), float(pos_data.max())]

        tiled_scan = self.controller.scan_model.get('tiled', False)
        composite_on = tiled_scan or (hasattr(self.ui, 'compositeImageCheckbox') and
                                      self.ui.compositeImageCheckbox.isChecked())

        if composite_on:
            # Build a unique key for this scan region
            region = image_model.get('scan_region_index', 0)
            image_id = f"scan_{self._composite_scan_counter}:{region}"
            if image_id in self.images:
                if levels is not None:
                    self.images[image_id].setImage(image_data.T, autoLevels=False, levels=levels)
                else:
                    self.images[image_id].setImage(image_data.T, autoLevels=False)
            else:
                # Create a new ImageItem positioned in motor coordinates
                img = pg.ImageItem()
                tr = QtGui.QTransform()
                tr.scale(image_scale[0], image_scale[1])
                tr.translate(pos[0] / image_scale[0], pos[1] / image_scale[1])
                img.setTransform(tr)
                if levels is not None:
                    img.setImage(image_data.T, autoLevels=False, levels=levels)
                else:
                    img.setImage(image_data.T, autoLevels=False)
                self.images[image_id] = img
                self.ui.mainImage.addItem(img)
        else:
            # Normal (non-composite) mode — update the main ImageView directly
            if levels is not None:
                self.ui.mainImage.setImage(
                    image_data.T,
                    autoRange=auto_range,
                    autoLevels=False,
                    levels=levels,
                    autoHistogramRange=auto_range,
                    pos=pos,
                    scale=image_scale
                )
            else:
                self.ui.mainImage.setImage(
                    image_data.T,
                    autoRange=auto_range,
                    autoLevels=False,
                    autoHistogramRange=auto_range,
                    pos=pos,
                    scale=image_scale
                )

            
    def update_scan_progress_display(self, progress_info: str):
        """Update scan progress display."""
        self.ui.imageCountText.setText(progress_info)

    def update_scan_file_display(self, filename: str):
        """Update scan file name label."""
        self.ui.scanFileName.setText(filename)
        
    def show_error_message(self, error_message: str):
        """Show error message to user."""
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Critical)
        msg.setText("Error!")
        msg.setInformativeText(error_message)
        msg.setWindowTitle("Error")
        msg.exec()

    def warning_popup(self, message: str) -> bool:
        """Show warning popup with OK/Cancel buttons.
        Returns True if OK was clicked, False otherwise."""
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setText("Warning!")
        msg.setInformativeText(message)
        msg.setWindowTitle("Warning")
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Ok)
        result = msg.exec()
        return result == QtWidgets.QMessageBox.Ok
        
    def update_status_display(self, status_message: str):
        """Update status display."""
        # Add timestamp to status message
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped_message = f"[{timestamp}] {status_message}"
        
        # Update status bar or status label
        self.statusBar().showMessage(timestamped_message, 5000)
        self.printToConsole(timestamped_message)
        
        # Update estimated time label if the message contains estimated time
        if "Estimated time:" in status_message:
            # Extract the time portion from the message
            time_part = status_message.split("Estimated time: ")[1]
            self.ui.estimatedTime.setText(time_part)
            
    def update_estimated_time(self):
        """Update estimated time by compiling current scan parameters.  Called by update_scan_regions
        and update_energy_regions"""
        try:
            self.controller.compile_scan_from_view(self)
            velocity = self.controller.scan_model.get_scan_velocity()
            self.ui.scanVelocity.setText(f"{velocity:.3f} mm/s")
            if velocity > self.maxVelocity:
                self.ui.scanVelocity.setStyleSheet("color: red;")
            else:
                self.ui.scanVelocity.setStyleSheet("")
        except Exception as e:
            print(f"Error updating estimated time: {e}")

    def printToConsole(self, message):
        self.lastMessage = message
        self.consoleStr = message + '\n' + self.consoleStr
        self.ui.serverOutput.setText(self.consoleStr)
        
    def update_monitor_plot(self):
        """Update the monitor plot with new data."""
        # Only update if Monitor plot type is selected
        if self.ui.plotType.currentText() == "Monitor":
            self._show_monitor_plot()
            
    def update_daq_value_display(self, daq_value: float):
        """Update the DAQ current value display."""
        self.ui.daqCurrentValue.setText(f"{daq_value:.1f}")

    def update_elapsed_time_display(self, elapsed_seconds: float):
        """Update elapsed time display.  This is called when the controller emits an update.  Those values
        come in messages from the server."""
        try:
            if elapsed_seconds < 100:
                time_str = f"{elapsed_seconds:.2f} s"
            elif elapsed_seconds < 3600:
                time_str = f"{elapsed_seconds / 60:.2f} m"
            else:
                time_str = f"{elapsed_seconds / 3600:.2f} hr"
                
            self.ui.elapsedTime.setText(time_str)
        except Exception as e:
            print(f"Error updating elapsed time display: {e}")

    def _set_focus_widgets(self,value: bool):
        self.ui.focusCenterEdit.setEnabled(value)
        self.ui.focusRangeEdit.setEnabled(value)
        self.ui.focusStepsEdit.setEnabled(value)

    def _set_line_widgets(self, value: bool):
        self.ui.lineLengthEdit.setEnabled(value)
        self.ui.lineAngleEdit.setEnabled(value)
        self.ui.lineAngleEdit.setText(str(self.lineAngle))
        self.ui.linePointsEdit.setEnabled(value)
        
    # UI helper methods
    def _update_ui_for_scan_type(self, scan_type: str):
        """Update UI elements based on scan type.  This function is called when the ui.scanType
        index is changed."""
        # Clear crosshairs
        if self.horizontal_line is not None:
            self.ui.mainImage.removeItem(self.horizontal_line)
            self.horizontal_line = None
        if self.vertical_line is not None:
            self.ui.mainImage.removeItem(self.vertical_line)
            self.vertical_line = None
            
        # Disable cursor-based buttons initially
        self.ui.motors2CursorButton.setEnabled(False)
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.setCursor2ZeroButton.setEnabled(False)
        
        # Set motor combos based on scan config if available
        if hasattr(self.controller.client, 'scanConfig') and self.controller.client.scanConfig:
            scan_config = self.controller.client.scanConfig
            if scan_type in scan_config:
                x_motor = scan_config[scan_type].get("xMotor")
                y_motor = scan_config[scan_type].get("yMotor")
                if x_motor:
                    self.ui.xMotorCombo.setCurrentText(x_motor)
                if y_motor:
                    self.ui.yMotorCombo.setCurrentText(y_motor)
        
        if "Focus" in scan_type:
            # Focus scan settings
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(False)
            if hasattr(self.ui, 'beamToCursorButton'):
                self.ui.beamToCursorButton.setEnabled(False)
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.doubleExposureCheckbox.setChecked(False)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setChecked(False)
            self.ui.multiFrameCheckbox.setEnabled(False)
            self._set_focus_widgets(True)
            self._set_line_widgets(True)
            
            # Update both focus and line step sizes
            self.update_focus_step_size()
            self.update_line_step_size()
            
            # Ensure only one scan region for focus
            if self.ui.scanRegSpinbox.value() != 1:
                self.ui.scanRegSpinbox.setValue(1)
                
            # Disable scan region widgets except center controls
            for region_widget in self.scan_region_widgets:
                region_widget.setEnabled(False)
                # Enable center controls only
                if hasattr(region_widget, 'ui'):
                    region_widget.ui.xCenter.setEnabled(True)
                    region_widget.ui.yCenter.setEnabled(True)
            
            # Update focus step size
            self.update_focus_step_size()
                
            # Hide range ROI
            if self.range_roi is not None:
                self.ui.mainImage.removeItem(self.range_roi)
                
        elif scan_type == "Line Spectrum":
            # Line spectrum settings
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setChecked(False)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.doubleExposureCheckbox.setChecked(False)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setChecked(False)
            self.ui.multiFrameCheckbox.setEnabled(False)
            self._set_focus_widgets(False)
            self._set_line_widgets(True)
            
            # Update line step size
            self.update_line_step_size()
            
            # Ensure only one scan region for line spectrum
            if self.ui.scanRegSpinbox.value() != 1:
                self.ui.scanRegSpinbox.setValue(1)
                
            # Disable scan region widgets
            for region_widget in self.scan_region_widgets:
                region_widget.setEnabled(False)
                
            # Hide range ROI
            if self.range_roi is not None:
                self.ui.mainImage.removeItem(self.range_roi)
                
        elif "Image" in scan_type:
            # Image scan settings
            self.ui.scanRegSpinbox.setEnabled(True)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.xMotorCombo.setEnabled(False)  # Usually fixed for image scans
            self.ui.yMotorCombo.setEnabled(False)
            self.ui.toggleSingleEnergy.setEnabled(True)
            self._set_focus_widgets(False)
            self._set_line_widgets(False)
            
            # Enable scan region widgets
            for region_widget in self.scan_region_widgets:
                region_widget.setEnabled(True)
                
            # Ptychography-specific settings
            if "Ptychography" in scan_type:
                self.ui.doubleExposureCheckbox.setEnabled(True)
                self.ui.multiFrameCheckbox.setEnabled(True)
                self.ui.defocusCheckbox.setEnabled(True)
            else:
                self.ui.doubleExposureCheckbox.setChecked(False)
                self.ui.doubleExposureCheckbox.setEnabled(False)
                self.ui.multiFrameCheckbox.setChecked(False)
                self.ui.multiFrameCheckbox.setEnabled(False)
                self.ui.defocusCheckbox.setEnabled(False)
                
            # Show range ROI if enabled
            if hasattr(self.ui, 'showRangeFinder') and self.ui.showRangeFinder.isChecked() and self.range_roi is not None:
                self.ui.mainImage.addItem(self.range_roi)
                
        elif scan_type == "Single Motor":
            # Single motor settings
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(True)  # Allow motor selection
            self.ui.yMotorCombo.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self._set_focus_widgets(False)
            self._set_line_widgets(False)
            
            # Ensure only one scan region
            if self.ui.scanRegSpinbox.value() != 1:
                self.ui.scanRegSpinbox.setValue(1)
                
            # Disable most checkboxes
            self.ui.doubleExposureCheckbox.setChecked(False)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setChecked(False)
            self.ui.multiFrameCheckbox.setEnabled(False)
            
        elif scan_type == "Double Motor":
            # Double motor settings
            self.ui.xMotorCombo.setEnabled(True)
            self.ui.yMotorCombo.setEnabled(True)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.scanRegSpinbox.setEnabled(True)
            self.ui.roiCheckbox.setEnabled(True)
            self._set_focus_widgets(False)
            self._set_line_widgets(False)
            
            # Enable scan region widgets
            for region_widget in self.scan_region_widgets:
                region_widget.setEnabled(True)
                
        # Update ROI enabled state based on current image type (checked state managed separately)
        current_image_type = self.controller.get_image_model().get('scan_type')
        if "Image" in current_image_type:
            self.ui.roiCheckbox.setEnabled(True)
        else:
            self.ui.roiCheckbox.setChecked(False)
            self.ui.roiCheckbox.setEnabled(False)
            
    def _set_scan_ui_state(self, scanning: bool):

        """Set UI state for scanning/not scanning.  This function is called with the controller emits
        scan_state_changed.  That occurs when a scan starts, completes or is cancelled."""

        if scanning:
            self._composite_scan_counter += 1

        # Basic scan controls
        self.ui.beginScanButton.setEnabled(not scanning)
        self.ui.cancelButton.setEnabled(scanning)
        self.ui.scanType.setEnabled(not scanning)
        self.ui.scanRegSpinbox.setEnabled(not scanning)
        self.ui.energyRegSpinbox.setEnabled(not scanning)
        
        # Image controls
        if hasattr(self.ui, 'compositeImageCheckbox'):
            self.ui.compositeImageCheckbox.setEnabled(not scanning)
        self.ui.removeLastImageButton.setEnabled(not scanning)
        self.ui.clearImageButton.setEnabled(not scanning)
        if hasattr(self.ui, 'firstEnergyButton'):
            self.ui.firstEnergyButton.setEnabled(not scanning)
        self.ui.toggleSingleEnergy.setEnabled(not scanning)
        
        # Motor controls
        self.ui.xMotorCombo.setEnabled(not scanning)
        self.ui.yMotorCombo.setEnabled(not scanning)
        # focusToCursorButton is only enabled when the user clicks inside a Focus scan
        # image — always disable it here; on_mouse_clicked re-enables it as needed.
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.motors2CursorButton.setEnabled(not scanning)
        
        # Scan region widgets
        for region_widget in self.scan_region_widgets:
            if hasattr(region_widget, 'region'):
                region_widget.region.setEnabled(not scanning)
            elif hasattr(region_widget, 'setEnabled'):
                region_widget.setEnabled(not scanning)
            
        # Energy region widgets
        for energy_widget in self.energy_region_widgets:
            if hasattr(energy_widget, 'widget'):
                energy_widget.widget.setEnabled(not scanning)
            elif hasattr(energy_widget, 'setEnabled'):
                energy_widget.setEnabled(not scanning)
            
        # ROI display
        self._hide_rois()
        self.ui.roiCheckbox.setChecked(False)
        self._update_ui_for_scan_type(self.controller.get_image_model().get('scan_type'))
        # Override ROI checkbox during scanning — always disabled+unchecked while running
        if scanning:
            self.ui.roiCheckbox.setChecked(False)
            self.ui.roiCheckbox.setEnabled(False)
        
    def _update_crosshair(self, x: float, y: float):
        """Update crosshair position on image."""
        if self.horizontal_line:
            self.ui.mainImage.removeItem(self.horizontal_line)
        if self.vertical_line:
            self.ui.mainImage.removeItem(self.vertical_line)
            
        pen = pg.mkPen(color=(0, 255, 0), width=1, style=QtCore.Qt.SolidLine)
        self.horizontal_line = pg.InfiniteLine(pos=y, angle=0, pen=pen)
        self.vertical_line = pg.InfiniteLine(pos=x, angle=90, pen=pen)
        
        self.ui.mainImage.addItem(self.horizontal_line)
        self.ui.mainImage.addItem(self.vertical_line)
        
    def _update_plot_display(self):
        """Update plot display based on current plot type."""
        plot_type = self.ui.plotType.currentText()
        if plot_type == "Monitor":
            self._show_monitor_plot()
        elif plot_type == "Motor Scan":
            self._show_motor_scan_plot()
            
    def _show_monitor_plot(self):
        """Show monitor data plot."""
        image_model = self.controller.get_image_model()
        channel_key = image_model.get('channel_key', 'default')
        monitor_data = image_model.get_monitor_data(channel_key)

        if not monitor_data:
            return

        data_array = np.array(monitor_data)

        if self.current_plot is None:
            self.current_plot = self.ui.mainPlot.plot(
                data_array,
                pen=self._main_plot_pen,
            )
        else:
            self.current_plot.setData(data_array)

        self.ui.mainPlot.setLabel("bottom", "Monitor")
        self.ui.mainPlot.setLabel("left", channel_key)
        self.ui.mainPlot.getPlotItem().getViewBox().autoRange()
            
    def update_motor_scan_plot(self):
        """Called when new Single Motor scan data arrives — switch plot and update."""
        if self.ui.plotType.currentText() != "Motor Scan":
            self.ui.plotType.blockSignals(True)
            self.ui.plotType.setCurrentText("Motor Scan")
            self.ui.plotType.blockSignals(False)
        self._show_motor_scan_plot()

    def _show_motor_scan_plot(self):
        """Show motor scan data plot with correct axis labels."""
        image_model = self.controller.get_image_model()
        x_data = image_model.get('motor_scan_x_data', [])
        motor_y = image_model.get('motor_scan_y_data', {})

        # Support both old flat-list format and new per-channel dict format
        channel_key = image_model.get('channel_key', 'default')
        if isinstance(motor_y, dict):
            y_data = motor_y.get(channel_key) or (next(iter(motor_y.values())) if motor_y else [])
        else:
            y_data = motor_y

        if not x_data or not y_data:
            return

        x_arr = np.array(x_data)
        y_arr = np.array(y_data)

        if self.current_plot is None:
            self.current_plot = self.ui.mainPlot.plot(
                x_arr, y_arr,
                pen=self._main_plot_pen,
            )
        else:
            self.current_plot.setData(x_arr, y_arr)

        x_motor = image_model.get('motor_scan_x_motor', 'Motor')
        self.ui.mainPlot.setLabel("bottom", x_motor)
        self.ui.mainPlot.setLabel("left", channel_key)
        self.ui.mainPlot.getPlotItem().getViewBox().autoRange()
            
    def _show_image_line_plots(self, scene_pos):
        """Update Image X / Image Y / Image XY line plots from mouse position.

        scene_pos is the position in ImageItem pixel coordinates:
          scene_pos.x() → x pixel index (column in display = row in array)
          scene_pos.y() → y pixel index (row in display = col in array)
        """
        plot_type = self.ui.plotType.currentText()
        if plot_type not in ("Image X", "Image Y", "Image XY"):
            return

        image_model = self.controller.get_image_model()
        current_image = image_model.get_current_image()
        if current_image is None:
            return

        # Image stored as (y_size, x_size) or (z_size, y_size, x_size)
        if current_image.ndim == 2:
            y_size, x_size = current_image.shape
            frame_index = None
        elif current_image.ndim == 3:
            z_size, y_size, x_size = current_image.shape
            try:
                frame_index = self.ui.mainImage.currentIndex
            except Exception:
                frame_index = 0
        else:
            return

        # Pixel indices from scene position
        x_pix = int(round(scene_pos.x()))   # x pixel (axis 1 of image array)
        y_pix = int(round(scene_pos.y()))   # y pixel (axis 0 of image array)

        x_center = image_model.get('x_center', 0.0)
        y_center = image_model.get('y_center', 0.0)
        x_range  = image_model.get('x_range',  1.0)
        y_range  = image_model.get('y_range',  1.0)

        x_axis = np.linspace(x_center - x_range / 2, x_center + x_range / 2, x_size)
        y_axis = np.linspace(y_center - y_range / 2, y_center + y_range / 2, y_size)

        want_x = plot_type in ("Image X", "Image XY")
        want_y = plot_type in ("Image Y", "Image XY")

        # Remove stale line plots
        if self.x_plot:
            self.ui.mainPlot.removeItem(self.x_plot)
            self.x_plot = None
        if self.y_plot:
            self.ui.mainPlot.removeItem(self.y_plot)
            self.y_plot = None

        channel_key = image_model.get('channel_key', 'default')

        if want_x and 0 <= y_pix < y_size:
            if frame_index is None:
                x_line = current_image[y_pix, :]
            else:
                x_line = current_image[frame_index, y_pix, :]
            self.x_plot = self.ui.mainPlot.plot(
                x_axis, x_line,
                pen=self._main_plot_pen,
            )
            self.ui.mainPlot.setLabel("bottom", "X (µm)")
            self.ui.mainPlot.setLabel("left", channel_key)

        if want_y and 0 <= x_pix < x_size:
            if frame_index is None:
                y_line = current_image[:, x_pix]
            else:
                y_line = current_image[frame_index, :, x_pix]
            self.y_plot = self.ui.mainPlot.plot(
                y_axis, y_line,
                pen=pg.mkPen(color=(200, 60, 30), width=1.5),
            )
            self.ui.mainPlot.setLabel("bottom", "Y (µm)")
            self.ui.mainPlot.setLabel("left", channel_key)

        if want_x and want_y:
            self.ui.mainPlot.setLabel("bottom", "Motor position (µm)")

        self.ui.mainPlot.getPlotItem().getViewBox().autoRange()

    # File operations
    def open_scan_file(self):
        """Open scan file dialog."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Scan File', self.currentDataDir or '', 'STXM Files (*.stxm);;All Files (*)'
        )
        if filename:
            self.currentLoadFile = filename
            self.load_scan_file()

    def load_scan_file(self):
        """Load and display scan data from .stxm file."""
        if not self.currentLoadFile:
            return

        try:
            from pystxmcontrol.utils.writeNX import stxm
            self.nx = stxm(stxm_file=self.currentLoadFile)
            print(f"Loading file {self.currentLoadFile}")

            scan_type = self.nx.meta.get("scan_type", "")

            if "Image" in scan_type or scan_type == "Double Motor":
                self.ui.scanFileName.setText(self.currentLoadFile.split('/')[-1])
                image_data = self.nx.data["entry0"]["counts"]["default"]

                # Get image dimensions
                ne, y, x = image_data.shape

                # Get position arrays
                xpos = self.nx.data['entry0']['xpos']
                ypos = self.nx.data['entry0']['ypos']

                # Calculate image parameters
                x_range = xpos.max() - xpos.min()
                y_range = ypos.max() - ypos.min()
                x_center = xpos.min() + x_range / 2.
                y_center = ypos.min() + y_range / 2.
                x_scale = float(x_range) / float(x)
                y_scale = float(y_range) / float(y)
                pos = (x_center - float(x_range) / 2., y_center - float(y_range) / 2.)

                # Update image model
                image_model = self.controller.get_image_model()
                image_model.set('x_center', x_center)
                image_model.set('y_center', y_center)
                image_model.set('x_range', x_range)
                image_model.set('y_range', y_range)
                image_model.set('image_scale', (x_scale, y_scale))

                # Display image (transpose for correct orientation)
                axes = (0, 2, 1)
                self.ui.mainImage.setImage(
                    np.transpose(image_data, axes=axes),
                    autoRange=True,
                    autoLevels=True,
                    autoHistogramRange=True,
                    pos=pos,
                    scale=(x_scale, y_scale)
                )

                # Update scan type
                if scan_type in [item.strip() for item in [self.ui.scanType.itemText(i) for i in range(self.ui.scanType.count())]]:
                    self.ui.scanType.setCurrentText(scan_type)

                # Build scan-region and energy-region dicts from the stxm data
                # and push them into the UI widgets.
                scan_regions_cfg = {}
                for ri in range(self.nx.nRegions):
                    entry = self.nx.data[f'entry{ri}']
                    xp = np.atleast_1d(entry['xpos']).flatten()
                    yp = np.atleast_1d(entry['ypos']).flatten()
                    xr = float(xp.max() - xp.min())
                    yr = float(yp.max() - yp.min())
                    xc = float(xp.min() + xr / 2.0)
                    yc = float(yp.min() + yr / 2.0)
                    nx_pts = int(xp.size)
                    ny_pts = int(yp.size)
                    xs = float(entry.get('xstepsize', xr / nx_pts if nx_pts > 1 else xr))
                    ys = float(entry.get('ystepsize', yr / ny_pts if ny_pts > 1 else yr))
                    scan_regions_cfg[f'Region{ri + 1}'] = {
                        'xCenter': round(xc, 4), 'yCenter': round(yc, 4),
                        'xRange':  round(xr, 4), 'yRange':  round(yr, 4),
                        'xPoints': nx_pts,        'yPoints': ny_pts,
                        'xStep':   round(xs, 4),  'yStep':   round(ys, 4),
                    }

                # Energy region — reconstruct from entry0's energy array
                energy_arr = np.atleast_1d(self.nx.data['entry0']['energy']).flatten()
                dwell_arr  = np.atleast_1d(self.nx.data['entry0']['dwell']).flatten()
                ne_pts = int(energy_arr.size)
                e_start = round(float(energy_arr[0]), 3)
                e_stop  = round(float(energy_arr[-1]), 3)
                e_step  = round(float((e_stop - e_start) / (ne_pts - 1)), 3) if ne_pts > 1 else 1.0
                dwell_val = round(float(np.mean(dwell_arr)), 3)
                energy_regions_cfg = {
                    'EnergyRegion1': {
                        'start': e_start, 'stop': e_stop,
                        'step': e_step,   'n_energies': ne_pts,
                        'dwell': dwell_val,
                    }
                }

                self._populate_ui_from_scan_config(
                    {'scan_regions': scan_regions_cfg, 'energy_regions': energy_regions_cfg},
                    scan_type=scan_type,
                )

            elif scan_type == "Single Motor":
                self.ui.scanFileName.setText(self.currentLoadFile.split('/')[-1])
                self.ui.plotType.setCurrentText("Motor Scan")
                # Handle single motor scan plotting
                pass

            else:
                self.warning_popup(f"File {self.currentLoadFile} is {scan_type} scan type.")

        except Exception as e:
            self.show_error_message(f"Failed to open file: {self.currentLoadFile}\nError: {str(e)}")
            import traceback
            traceback.print_exc()
            
    def save_scan_definition(self):
        """Save scan definition dialog."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Save Scan Definition', '', 'JSON Files (*.json);;All Files (*)'
        )
        if filename:
            self.controller.save_scan_definition(filename)
            
    def open_energy_definition(self):
        """Open energy definition dialog."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Energy Definition', '', 'JSON Files (*.json);;All Files (*)'
        )
        if not filename:
            return
        try:
            import json
            with open(filename, 'r') as f:
                data = json.load(f)
            # Accept either {"energy_regions": {...}} or the raw regions dict
            if 'energy_regions' in data:
                cfg = {'energy_regions': data['energy_regions']}
            else:
                cfg = {'energy_regions': data}
            self._populate_ui_from_scan_config(cfg)
        except Exception as e:
            self.show_error_message(f"Failed to open energy definition: {filename}\nError: {str(e)}")

    def open_scan_definition(self):
        """Open scan definition dialog."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Scan Definition', '', 'JSON Files (*.json);;All Files (*)'
        )
        if not filename:
            return
        try:
            import json
            with open(filename, 'r') as f:
                data = json.load(f)
            self.controller.load_scan_definition(filename)
            scan_type = data.get('scan_type', self.ui.scanType.currentText())
            if scan_type:
                self.ui.scanType.setCurrentText(scan_type)
            self._populate_ui_from_scan_config(data, scan_type=scan_type)
        except Exception as e:
            self.show_error_message(f"Failed to open scan definition: {filename}\nError: {str(e)}")
            
    # Theme and appearance
    def set_light_theme(self):
        """Set light theme."""
        self.static_style = "color: black;"
        self.setStyleSheet(qdarktheme.load_stylesheet("light"))
        if hasattr(self, '_main_plot_pen'):
            self._apply_plot_theme(light=True)

    def set_dark_theme(self):
        """Set dark theme."""
        self.static_style = "color: white;"
        self.setStyleSheet(qdarktheme.load_stylesheet())
        if hasattr(self, '_main_plot_pen'):
            self._apply_plot_theme(light=False)
        
    # Initialization methods
    def re_init(self):
        """Re-initialize the application."""
        self.controller.initialize_client()
        
    def load_config(self):
        """Load configuration from server."""
        # This would be handled through the controller
        pass
        
    # Region management
    def update_scan_regions(self):
        """Update scan region widgets."""
        requested_count = self.ui.scanRegSpinbox.value()
        current_count = len(self.scan_region_widgets)
        
        # Add widgets if needed
        while current_count < requested_count:
            widget = scanRegionDef()
            widget.ui.regNum.setText(f"Region {current_count + 1}")
            
            # Set default values for new region widgets
            widget.ui.xCenter.setText("0.0")
            widget.ui.yCenter.setText("0.0") 
            widget.ui.xRange.setText("70.0")
            widget.ui.yRange.setText("70.0")
            widget.ui.xNPoints.setText("100")
            widget.ui.yNPoints.setText("100")
            widget.ui.xStep.setText("0.7")
            widget.ui.yStep.setText("0.7")
            
            # Connect region change signals to update ROIs
            widget.regionChanged.connect(self._update_rois_from_regions)
            
            self.ui.regionDefWidget.addWidget(widget.region)
            self.scan_region_widgets.append(widget)
            current_count += 1
            
        # Remove widgets if needed
        while current_count > requested_count:
            widget = self.scan_region_widgets.pop()
            self.ui.regionDefWidget.removeWidget(widget.region)
            widget.region.deleteLater()
            current_count -= 1
            
        # Update ROIs to match new region count
        self._update_rois_from_regions()
            
    def update_energy_regions(self):
        """Update energy region widgets."""
        requested_count = self.ui.energyRegSpinbox.value()
        current_count = len(self.energy_region_widgets)

        # Refresh _saved_multi_energy from live widget values so any user edits
        # to energyStart (or other fields) made since the last single→multi
        # transition are preserved if the user later toggles Single Energy again.
        if not self._single_energy_active:
            refreshed = []
            for ew in self.energy_region_widgets:
                if hasattr(ew, 'energyDef'):
                    ed = ew.energyDef
                    refreshed.append({
                        'start':      ed.energyStart.text(),
                        'stop':       ed.energyStop.text(),
                        'step':       ed.energyStep.text(),
                        'n_energies': ed.nEnergies.text(),
                        'dwell':      ed.dwellTime.text(),
                    })
            if refreshed:
                self._saved_multi_energy = refreshed

        # Add widgets if needed
        while current_count < requested_count:
            widget = energyDefWidget()
            widget.energyDef.regNum.setText(f"Region {current_count + 1}")

            # Default multi-energy values for the new region
            defaults = {'start': '700', 'stop': '720', 'step': '1',
                        'n_energies': '21', 'dwell': '1'}
            widget.energyDef.energyStart.setText(defaults['start'])
            widget.energyDef.energyStop.setText(defaults['stop'])
            widget.energyDef.energyStep.setText(defaults['step'])
            widget.energyDef.nEnergies.setText(defaults['n_energies'])

            if current_count == 0:
                # Region 1 is the dwell master — connect its return-press to propagate
                widget.energyDef.dwellTime.setText(defaults['dwell'])
                widget.energyDef.dwellTime.returnPressed.connect(self._propagate_dwell)
            else:
                # Non-master regions mirror Region 1's dwell and are not editable
                if self.energy_region_widgets:
                    dwell_val = self.energy_region_widgets[0].energyDef.dwellTime.text()
                else:
                    dwell_val = defaults['dwell']
                widget.energyDef.dwellTime.setText(dwell_val)
                widget.energyDef.dwellTime.setEnabled(False)
                defaults['dwell'] = dwell_val

            self.ui.energyDefWidget.addWidget(widget.widget)
            self.energy_region_widgets.append(widget)

            # While single energy is active, save the new region's defaults so
            # unchecking Single Energy later restores them, then apply single-energy overwrite
            if self._single_energy_active:
                self._saved_multi_energy.append(defaults)
                widget.setSingleEnergy()
                ed = widget.energyDef
                ed.energyStep.setText("1")
                ed.nEnergies.setText("1")
                ed.energyStop.setText(defaults['start'])

            current_count += 1

        # Apply current single energy state to all widgets
        self.toggle_single_energy()
            
        # Remove widgets if needed
        while current_count > requested_count:
            widget = self.energy_region_widgets.pop()
            self.ui.energyDefWidget.removeWidget(widget.widget)
            widget.widget.deleteLater()
            current_count -= 1
            # Keep saved list in sync
            if self._saved_multi_energy:
                self._saved_multi_energy = self._saved_multi_energy[:current_count]
            
    def _read_main_config_from_disk(self) -> dict:
        """Read main.json from disk without requiring a server connection."""
        try:
            import sys, json, os
            path = os.path.join(sys.prefix, 'pystxmcontrol_cfg', 'main.json')
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _apply_last_scan(self, scan_type: str):
        """Populate UI widgets with the last-used values for *scan_type* from main.json."""
        last_scan = self._local_main_config.get("lastScan", {}).get(scan_type)
        if not last_scan:
            # No saved state — default to single energy
            self._saved_multi_energy = []
            self._single_energy_active = False
            self.ui.toggleSingleEnergy.blockSignals(True)
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.blockSignals(False)
            self.toggle_single_energy()
            return

        # Don't restore the proposal — it is the activation gate.
        self.ui.experimentersLineEdit.setText(last_scan.get("experimenters", ""))
        self.ui.sampleLineEdit.setText(last_scan.get("sample", ""))

        x_motor = last_scan.get("x_motor", "")
        y_motor = last_scan.get("y_motor", "")
        if x_motor:
            self.ui.xMotorCombo.setCurrentText(x_motor)
        if y_motor:
            self.ui.yMotorCombo.setCurrentText(y_motor)

        self._populate_ui_from_scan_config(last_scan, scan_type=scan_type)

    def _populate_ui_from_scan_config(self, config: dict, scan_type: str = ""):
        """Populate scan-region and energy-region widgets from a scan config dict.

        *config* must contain 'scan_regions' and/or 'energy_regions' keys in the
        same format used by the scan model / main.json.  *scan_type* is only used
        to decide whether to fill z-axis (focus) fields.
        """
        # ── scan regions ──────────────────────────────────────────────────────
        scan_regions = config.get("scan_regions", {})
        if scan_regions:
            self.ui.scanRegSpinbox.setValue(len(scan_regions))
            for i, region in enumerate(scan_regions.values()):
                if i >= len(self.scan_region_widgets):
                    break
                w = self.scan_region_widgets[i]
                w.ui.xCenter.setText(str(region.get("xCenter", 0.0)))
                w.ui.yCenter.setText(str(region.get("yCenter", 0.0)))
                w.ui.xRange.setText(str(region.get("xRange", 70.0)))
                w.ui.yRange.setText(str(region.get("yRange", 70.0)))
                w.ui.xNPoints.setText(str(region.get("xPoints", 100)))
                w.ui.yNPoints.setText(str(region.get("yPoints", 100)))
                w.ui.xStep.setText(str(region.get("xStep", 0.7)))
                w.ui.yStep.setText(str(region.get("yStep", 0.7)))

            if scan_type and ("Focus" in scan_type or "OSA Focus" in scan_type):
                first_region = next(iter(scan_regions.values()))
                if hasattr(self.ui, "focusCenterEdit"):
                    self.ui.focusCenterEdit.setText(str(first_region.get("zCenter", 0.0)))
                if hasattr(self.ui, "focusRangeEdit"):
                    self.ui.focusRangeEdit.setText(str(first_region.get("zRange", 100.0)))
                if hasattr(self.ui, "focusStepsEdit"):
                    self.ui.focusStepsEdit.setText(str(first_region.get("zPoints", 50)))

        # ── energy regions ────────────────────────────────────────────────────
        energy_regions = config.get("energy_regions", {})
        if energy_regions:
            self.ui.energyRegSpinbox.setValue(len(energy_regions))
            for i, region in enumerate(energy_regions.values()):
                if i >= len(self.energy_region_widgets):
                    break
                w = self.energy_region_widgets[i]
                w.energyDef.energyStart.setText(str(region.get("start", 700.0)))
                w.energyDef.energyStop.setText(str(region.get("stop", 720.0)))
                w.energyDef.energyStep.setText(str(region.get("step", 1.0)))
                w.energyDef.nEnergies.setText(str(region.get("n_energies", 21)))
                w.energyDef.dwellTime.setText(str(region.get("dwell", 1.0)))

            max_n = max(r.get("n_energies", 1) for r in energy_regions.values())
            self.ui.toggleSingleEnergy.blockSignals(True)
            self.ui.toggleSingleEnergy.setChecked(max_n <= 1)
            self.ui.toggleSingleEnergy.blockSignals(False)
        else:
            self.ui.toggleSingleEnergy.blockSignals(True)
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.blockSignals(False)

        # Reset transition state so toggle_single_energy fires correctly
        self._saved_multi_energy = []
        self._single_energy_active = False
        self.toggle_single_energy()

        self._update_rois_from_regions()

    def toggle_energy_list(self):
        """Toggle between energy regions and energy list."""
        if self.ui.energyListCheckbox.isChecked():
            # Switch to energy list mode — uncheck Single Energy first
            self.ui.toggleSingleEnergy.blockSignals(True)
            self.ui.toggleSingleEnergy.setChecked(False)
            self.ui.toggleSingleEnergy.blockSignals(False)

            # Save the dwell before removing widgets
            if self.energy_region_widgets:
                try:
                    self._energy_list_dwell = float(
                        self.energy_region_widgets[0].energyDef.dwellTime.text() or 1000
                    )
                except (ValueError, AttributeError):
                    pass

            # Remove all energy region widgets
            while len(self.energy_region_widgets) > 0:
                widget = self.energy_region_widgets.pop()
                self.ui.energyDefWidget.removeWidget(widget.widget)
                widget.widget.deleteLater()
            
            # Show energy list widget and disable energy region spinbox
            self.ui.energyListWidget.setVisible(True)
            self.ui.energyRegSpinbox.setEnabled(False)
        else:
            # Switch to energy regions mode
            self.ui.energyRegSpinbox.setEnabled(True)
            
            # Set single energy if only one region
            if self.ui.energyRegSpinbox.value() == 1:
                self.ui.toggleSingleEnergy.setChecked(True)
                
            # Hide energy list widget
            self.ui.energyListWidget.setVisible(False)
            
            # Recreate energy region widgets
            self.update_energy_regions()
            
    def toggle_single_energy(self):
        """Toggle single energy mode for energy regions."""
        is_single_energy = self.ui.toggleSingleEnergy.isChecked()

        if is_single_energy and self.ui.energyListCheckbox.isChecked():
            # Uncheck energy list silently and restore energy region widgets
            self.ui.energyListCheckbox.blockSignals(True)
            self.ui.energyListCheckbox.setChecked(False)
            self.ui.energyListCheckbox.blockSignals(False)
            self.ui.energyListWidget.setVisible(False)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.energyRegSpinbox.setValue(1)
            self.update_energy_regions()

        if is_single_energy:
            # When switching to single energy mode, reduce to 1 energy region
            if self.ui.energyRegSpinbox.value() != 1:
                self.ui.energyRegSpinbox.setValue(1)
                self.update_energy_regions()

            # Disable the energy region spinbox so user can't add more regions
            self.ui.energyRegSpinbox.setEnabled(False)
        else:
            # When switching to multi-energy mode, re-enable the energy region spinbox
            self.ui.energyRegSpinbox.setEnabled(True)
        
        # Apply settings to all energy region widgets
        transitioning_to_single = is_single_energy and not self._single_energy_active
        transitioning_to_multi = not is_single_energy and self._single_energy_active
        self._single_energy_active = is_single_energy

        if transitioning_to_single:
            # Save the current multi-energy definition before overwriting
            self._saved_multi_energy = []
            for energy_widget in self.energy_region_widgets:
                if hasattr(energy_widget, 'energyDef'):
                    ed = energy_widget.energyDef
                    self._saved_multi_energy.append({
                        'start':      ed.energyStart.text(),
                        'stop':       ed.energyStop.text(),
                        'step':       ed.energyStep.text(),
                        'n_energies': ed.nEnergies.text(),
                        'dwell':      ed.dwellTime.text(),
                    })
        elif transitioning_to_multi:
            # Restore saved multi-energy definition if available
            if self._saved_multi_energy:
                for i, energy_widget in enumerate(self.energy_region_widgets):
                    if i >= len(self._saved_multi_energy):
                        break
                    if hasattr(energy_widget, 'energyDef'):
                        ed = energy_widget.energyDef
                        saved = self._saved_multi_energy[i]
                        ed.energyStart.setText(saved['start'])
                        ed.energyStop.setText(saved['stop'])
                        ed.energyStep.setText(saved['step'])
                        ed.nEnergies.setText(saved['n_energies'])
                        ed.dwellTime.setText(saved['dwell'])

        # When switching to single energy, use current energy motor position as start
        current_energy_str = None
        if is_single_energy and transitioning_to_single:
            try:
                motor_positions = self.controller.get_motor_model().get('current_positions', {})
                energy_motor = self.controller.scan_model.get('energy_motor', 'Energy')
                energy_val = motor_positions.get(energy_motor)
                if energy_val is not None:
                    current_energy_str = f"{energy_val:.3f}"
            except Exception:
                pass

        for energy_widget in self.energy_region_widgets:
            if hasattr(energy_widget, 'energyDef'):
                if is_single_energy:
                    energy_widget.setSingleEnergy()
                    ed = energy_widget.energyDef
                    if current_energy_str is not None:
                        ed.energyStart.setText(current_energy_str)
                    ed.energyStep.setText("1")
                    ed.nEnergies.setText("1")
                    ed.energyStop.setText(ed.energyStart.text())
                else:
                    energy_widget.setMultiEnergy()

        # Ensure non-Region-1 dwell fields stay locked to Region 1
        if not is_single_energy:
            self._propagate_dwell()

    def _propagate_dwell(self):
        """Copy Region 1's dwell time to all other energy regions and disable their field."""
        if not self.energy_region_widgets:
            return
        dwell_val = self.energy_region_widgets[0].energyDef.dwellTime.text()
        for widget in self.energy_region_widgets[1:]:
            ed = widget.energyDef
            ed.dwellTime.setText(dwell_val)
            ed.dwellTime.setEnabled(False)

    def toggle_roi_display(self):
        """Toggle ROI display."""
        if self.ui.roiCheckbox.isChecked():
            self._show_rois()
        else:
            self._hide_rois()
            
    def toggle_range_roi_display(self):
        """Toggle range ROI display."""
        if self.ui.showRangeFinder.isChecked():
            if self.range_roi is not None:
                # Only add if it's not already in the scene
                if self.range_roi not in self.ui.mainImage.getView().allChildItems():
                    print("Showing range_roi")
                    self.ui.mainImage.addItem(self.range_roi)
        else:
            if self.range_roi is not None:
                # Only remove if it's currently in the scene
                if self.range_roi in self.ui.mainImage.getView().allChildItems():
                    print("Hiding range_roi")
                    self.ui.mainImage.removeItem(self.range_roi)
            
    def _update_rois_from_regions(self):
        """Update ROIs based on current scan region widgets."""
        # Clear existing ROIs
        self._clear_rois()

        # Create new ROIs from scan region widgets
        scan_type = self.ui.scanType.currentText()
        if hasattr(self.controller, 'client') and self.controller.client and hasattr(self.controller.client, 'scanConfig'):
            try:
                config_scan_type = self.controller.client.scanConfig.get(scan_type, {}).get("type", "image")
            except:
                config_scan_type = "image"
        else:
            config_scan_type = "image"  # Default

        for i, region_widget in enumerate(self.scan_region_widgets):
            self._add_roi_from_region(region_widget, i, config_scan_type)

        # Show ROIs if checkbox is checked
        if self.ui.roiCheckbox.isChecked():
            self._show_rois()

        self.update_estimated_time()

    def _calculate_line_roi(self):
        """Calculate line ROI from current line parameters."""
        # Check if we have scan regions
        if not self.scan_region_widgets:
            # Return a default line ROI if no regions exist yet
            roi = pg.LineSegmentROI(
                positions=((-5, 0), (5, 0)),
                pen=self.default_pen if hasattr(self, 'default_pen') else pg.mkPen('r', width=3),
                movable=True
            )
            return roi

        region_widget = self.scan_region_widgets[-1]
        x_center = float(region_widget.ui.xCenter.text() or 0)
        y_center = float(region_widget.ui.yCenter.text() or 0)
        line_length = float(self.ui.lineLengthEdit.text() or 10)
        line_angle = float(self.ui.lineAngleEdit.text() or 0)

        # Convert angle from degrees to radians
        angle_rad = np.radians(line_angle)

        # Calculate half-length offsets
        half_length = line_length / 2
        dx = half_length * np.cos(angle_rad)
        dy = half_length * np.sin(angle_rad)

        # Calculate endpoints based on center position, length, and angle
        x1 = x_center - dx
        y1 = y_center - dy
        x2 = x_center + dx
        y2 = y_center + dy

        roi = pg.LineSegmentROI(
            positions=((x1, y1), (x2, y2)), 
            pen=self.default_pen,
            movable=True
        )
        return roi
            
    def _add_roi_from_region(self, region_widget, index: int, scan_type: str):
        """Add a single ROI from a region widget."""
        try:
            x_center = float(region_widget.ui.xCenter.text() or 0)
            y_center = float(region_widget.ui.yCenter.text() or 0)
            x_range = float(region_widget.ui.xRange.text() or 10)
            y_range = float(region_widget.ui.yRange.text() or 10)
            
            # Get pen color and style
            color_index = index % len(self.pen_colors)
            style_index = int(index / len(self.pen_colors)) % len(self.pen_styles)
            roi_pen = pg.mkPen(
                self.pen_colors[color_index],
                width=3,
                style=self.pen_styles[style_index]
            )
            
            # Calculate ROI position using motor coordinates
            x_min = x_center - x_range / 2
            y_min = y_center - y_range / 2
            
            # Create appropriate ROI based on scan type
            if "image" in scan_type.lower():
                roi = pg.RectROI(
                    (x_min, y_min), 
                    (x_range, y_range), 
                    snapSize=5.0, 
                    pen=roi_pen,
                    movable=True,
                    resizable=True,
                    rotatable=False
                )
            elif "line" in scan_type.lower():
                # For line ROIs, use line length and angle parameters
                try:
                    roi = self._calculate_line_roi()

                except (ValueError, AttributeError):
                    # Fallback to horizontal line if parameters are invalid
                    x_max = x_center + x_range / 2
                    roi = pg.LineSegmentROI(
                        positions=((x_min, y_center), (x_max, y_center)),
                        pen=roi_pen,
                        movable=True
                    )
            else:
                # Default to rectangle
                roi = pg.RectROI(
                    (x_min, y_min), 
                    (x_range, y_range), 
                    snapSize=5.0, 
                    pen=roi_pen,
                    movable=True,
                    resizable=True,
                    rotatable=False
                )
            
            # Connect ROI change signal to update region widgets
            roi.sigRegionChanged.connect(self._update_region_from_roi)

            self.roi_list.append(roi)
            
        except (ValueError, AttributeError) as e:
            print(f"Error creating ROI for region {index}: {e}")
            
    def _update_region_from_roi(self):
        """Update region widgets when ROI is dragged."""
        try:
            # Find which ROI was changed by checking the sender
            sender_roi = self.sender()
            if sender_roi not in self.roi_list:
                return
                
            roi_index = self.roi_list.index(sender_roi)
            
            # Make sure we have a corresponding scan region widget
            if roi_index >= len(self.scan_region_widgets):
                return
                
            region_widget = self.scan_region_widgets[roi_index]
            
            # Get the current scan type to handle different ROI types
            scan_type = self.ui.scanType.currentText()
            config_scan_type = "image"  # Default
            if hasattr(self.controller, 'client') and self.controller.client and hasattr(self.controller.client, 'scanConfig'):
                try:
                    config_scan_type = self.controller.client.scanConfig.get(scan_type, {}).get("type", "image")
                except:
                    pass
            
            # Update region widget based on ROI type
            if isinstance(sender_roi, pg.RectROI):
                # Get ROI position and size
                roi_pos = sender_roi.pos()
                roi_size = sender_roi.size()
                
                # Calculate center and range in motor coordinates
                x_center = roi_pos.x() + roi_size.x() / 2
                y_center = roi_pos.y() + roi_size.y() / 2
                x_range = roi_size.x()
                y_range = roi_size.y()
                
                # Calculate step sizes based on current point counts
                try:
                    x_points = int(region_widget.ui.xNPoints.text() or 100)
                    y_points = int(region_widget.ui.yNPoints.text() or 100)
                    x_step = x_range / x_points if x_points > 0 else 0.1
                    y_step = y_range / y_points if y_points > 0 else 0.1
                except (ValueError, ZeroDivisionError):
                    x_step, y_step = 0.1, 0.1
                
                # Update the region widget (temporarily disconnect signals to avoid recursion)
                region_widget.regionChanged.disconnect()
                
                region_widget.ui.xCenter.setText(f"{x_center:.3f}")
                region_widget.ui.yCenter.setText(f"{y_center:.3f}")
                region_widget.ui.xRange.setText(f"{x_range:.3f}")
                region_widget.ui.yRange.setText(f"{y_range:.3f}")
                region_widget.ui.xStep.setText(f"{x_step:.3f}")
                region_widget.ui.yStep.setText(f"{y_step:.3f}")
                
                # Reconnect signals
                region_widget.regionChanged.connect(self._update_rois_from_regions)
                
            elif isinstance(sender_roi, pg.LineSegmentROI):
                # Handle line ROI updates
                handles = sender_roi.getHandles()
                if len(handles) >= 2:
                    # Get positions in parent (image) coordinates
                    pos1 = sender_roi.mapToParent(handles[0].pos())
                    pos2 = sender_roi.mapToParent(handles[1].pos())

                    # Calculate line center, length, and angle
                    x_center = (pos1.x() + pos2.x()) / 2
                    y_center = (pos1.y() + pos2.y()) / 2

                    dx = pos2.x() - pos1.x()
                    dy = pos2.y() - pos1.y()
                    line_length = (dx**2 + dy**2)**0.5
                    line_angle = np.degrees(np.arctan2(dy, dx))

                    # Update the region widget (disconnect to avoid recursion)
                    region_widget.regionChanged.disconnect(self._update_rois_from_regions)

                    region_widget.ui.xCenter.setText(f"{x_center:.3f}")
                    region_widget.ui.yCenter.setText(f"{y_center:.3f}")
                    region_widget.ui.xRange.setText(f"{abs(dx):.3f}")
                    region_widget.ui.yRange.setText(f"{abs(dy):.3f}")

                    # For line spectrum and focus scans, update the line length and angle edits.
                    # Block signals to prevent textChanged → update_line_parameters → update_line_roi
                    # from clearing and recreating the ROI while it is being dragged.
                    if hasattr(self.ui, 'lineLengthEdit'):
                        self.ui.lineLengthEdit.blockSignals(True)
                        self.ui.lineLengthEdit.setText(f"{line_length:.3f}")
                        self.ui.lineLengthEdit.blockSignals(False)
                        self.update_line_step_size()
                    if hasattr(self.ui, 'lineAngleEdit'):
                        self.ui.lineAngleEdit.blockSignals(True)
                        self.ui.lineAngleEdit.setText(f"{line_angle:.3f}")
                        self.ui.lineAngleEdit.blockSignals(False)

                    # Reconnect signal
                    region_widget.regionChanged.connect(self._update_rois_from_regions)
                    
        except Exception as e:
            print(f"Error updating region from ROI: {e}")
            # Reconnect signals in case of error
            try:
                if roi_index < len(self.scan_region_widgets):
                    self.scan_region_widgets[roi_index].regionChanged.connect(self._update_rois_from_regions)
            except:
                pass
        
    def _clear_rois(self):
        """Clear all ROIs from display and list."""
        for roi in self.roi_list:
            try:
                roi.sigRegionChanged.disconnect(self._update_region_from_roi)
            except:
                pass  # Signal may not be connected
            if roi in self.ui.mainImage.getView().allChildItems():
                self.ui.mainImage.removeItem(roi)
        self.roi_list.clear()
            
    def _show_rois(self):
        """Show ROIs on image."""
        for roi in self.roi_list:
            if roi not in self.ui.mainImage.getView().allChildItems():
                self.ui.mainImage.addItem(roi)
            
    def _hide_rois(self):
        """Hide ROIs from image."""
        for roi in self.roi_list:
            if roi in self.ui.mainImage.getView().allChildItems():
                self.ui.mainImage.removeItem(roi)
            
    def toggle_jog_mode(self):
        """Toggle between jog and move mode."""
        jog_mode = self.ui.motorMover1Minus.isEnabled()
        
        # Toggle jog buttons
        self.ui.motorMover1Minus.setEnabled(not jog_mode)
        self.ui.motorMover1Plus.setEnabled(not jog_mode)
        self.ui.motorMover2Minus.setEnabled(not jog_mode)
        self.ui.motorMover2Plus.setEnabled(not jog_mode)
        
        # Toggle move buttons
        self.ui.motorMover1Button.setEnabled(jog_mode)
        self.ui.motorMover2Button.setEnabled(jog_mode)
        
        # Update edit fields
        if jog_mode:  # Switching to move mode
            motor1 = self.ui.motorMover1.currentText()
            motor2 = self.ui.motorMover2.currentText()
            pos1 = self.controller.get_motor_model().get_position(motor1) or 0.0
            pos2 = self.controller.get_motor_model().get_position(motor2) or 0.0
            self.ui.motorMover1Edit.setText(f"{pos1:.3f}")
            self.ui.motorMover2Edit.setText(f"{pos2:.3f}")
        else:  # Switching to jog mode
            self.ui.motorMover1Edit.setText("10.0")
            self.ui.motorMover2Edit.setText("10.0")
            
    def clear_plot(self):
        """Clear the plot."""
        if self.current_plot:
            self.ui.mainPlot.removeItem(self.current_plot)
            self.current_plot = None
        self.controller.get_image_model().clear_monitor_data()
        self.controller.get_image_model().clear_motor_scan_data()
        
    def clear_image(self):
        """Clear all images."""
        # Clear composite images
        for item in self.images.values():
            item.setImage()
            self.ui.mainImage.removeItem(item)
        self.images = {}

        # Clear main image
        self.ui.mainImage.clear()
        self.controller.get_image_model().clear_image_stack()

    def remove_last_image(self):
        """Remove the last image from composite display."""
        if not self.images:
            return
        key = list(self.images.keys())[-1]
        self.images[key].setImage()
        self.ui.mainImage.removeItem(self.images[key])
        del self.images[key]

    def update_image_from_ccd(self, ccd_data):
        """Update image display from CCD camera data."""
        self.currentCCDData = ccd_data
        if self.ui.channelSelect.currentText() == "CCD":
            # Log-scale CCD data for display
            modified_CCD = ccd_data.T + 10
            modified_CCD[modified_CCD < 1] = 1
            modified_CCD = np.log(modified_CCD)
            self.ui.mainImage.setImage(
                modified_CCD,
                autoRange=self.ui.autorangeCheckbox.isChecked(),
                autoLevels=self.ui.autoscaleCheckbox.isChecked(),
                autoHistogramRange=self.ui.autorangeCheckbox.isChecked(),
                pos=(0, 0),
                scale=(1, 1)
            )

    def update_image_from_rpi(self, rpi_data):
        """Update image display from RPI (Ptychography) reconstruction."""
        self.currentRPIData, self.ptychoXpixm, self.ptychoYpixm = rpi_data
        if self.ui.channelSelect.currentText() == "RPI":
            image_model = self.controller.get_image_model()
            x_center = image_model.get('x_center', 0.0)
            y_center = image_model.get('y_center', 0.0)
            x_range = image_model.get('x_range', 70.0)
            y_range = image_model.get('y_range', 70.0)

            # RPI uses micron pixel scale
            xScale = self.ptychoXpixm * 1e6
            yScale = self.ptychoYpixm * 1e6
            pos = (x_center - x_range / 2., y_center - y_range / 2.)

            self.ui.mainImage.setImage(
                self.currentRPIData,
                autoRange=True,
                autoLevels=True,
                autoHistogramRange=True,
                pos=pos,
                scale=(xScale, yScale)
            )

    def update_composite_image(self):
        """Toggle composite image display mode."""
        if not hasattr(self.ui, 'compositeImageCheckbox') or not self.images:
            return
        if self.ui.compositeImageCheckbox.isChecked():
            # Re-add all composite items (order matters for z-stacking)
            for item in self.images.values():
                self.ui.mainImage.removeItem(item)
            for item in self.images.values():
                self.ui.mainImage.addItem(item)
        else:
            # Hide all but the most recent composite item
            last_key = list(self.images.keys())[-1]
            for key, item in self.images.items():
                if key != last_key:
                    self.ui.mainImage.removeItem(item)
        
    def _populate_proposal_combobox(self):
        """Populate the proposal combobox with ESAF proposals."""
        try:
            # Clear existing items
            self.ui.proposalComboBox.clear()
            
            # Add default "Select a Proposal" option
            self.ui.proposalComboBox.addItem("Select a Proposal")
            
            # Try to get ESAF list from server
            try:
                from pystxmcontrol.utils.alsapi import getCurrentEsafList
                self.esaf_list, self.participants_list = getCurrentEsafList()

                # Add each proposal to the combobox
                for esaf in self.esaf_list:
                    self.ui.proposalComboBox.addItem(esaf)
                    
            except Exception as e:
                print(f"Could not fetch ESAF list: {e}")
                # Initialize empty lists if fetch fails
                self.esaf_list = []
                self.participants_list = []
            
            # Add "Staff Access" option at the end
            self.ui.proposalComboBox.addItem("Staff Access")
            
            # Initially deactivate GUI until proposal is selected
            self._deactivate_gui()
            
        except Exception as e:
            print(f"Error populating proposal combobox: {e}")
            # Initialize empty lists as fallback
            self.esaf_list = []
            self.participants_list = []
            
    def on_proposal_changed(self):
        """Handle proposal selection changes."""
        try:
            selected_text = self.ui.proposalComboBox.currentText()
            selected_index = self.ui.proposalComboBox.currentIndex()

            if selected_text == "Staff Access":
                if not self._check_staff_password():
                    # Reset combo back to "Select a Proposal" without re-firing signal
                    self.ui.proposalComboBox.blockSignals(True)
                    self.ui.proposalComboBox.setCurrentIndex(0)
                    self.ui.proposalComboBox.blockSignals(False)
                    return
                self._activate_gui()
                self._activate_staff()
                self._set_warning_banner("Users cannot access this data!")
                self.ui.experimentersLineEdit.setText("")

            elif selected_index > 0 and selected_index <= len(self.esaf_list):
                # Valid proposal selected
                try:
                    # Get participant list for this proposal
                    participants = self.participants_list[selected_index - 1]  # -1 because index 0 is "Select a Proposal"

                    # Activate GUI first (on_scan_type_changed inside it overwrites experimentersLineEdit)
                    self._activate_gui()
                    self._set_warning_banner(None)
                    # Set experimenters after _activate_gui so it isn't overwritten
                    self.ui.experimentersLineEdit.setText(', '.join(participants))

                except (IndexError, AttributeError) as e:
                    print(f"Error setting experimenters: {e}")
                    self.ui.experimentersLineEdit.setText("")
                    self._activate_gui()
                    self._set_warning_banner(None)

            else:
                # "Select a Proposal" or invalid selection
                self.ui.experimentersLineEdit.setText("")
                self._set_warning_banner("Select a proposal to activate the GUI")
                self._deactivate_gui()
                self._deactivate_staff()

        except Exception as e:
            print(f"Error handling proposal change: {e}")
            
    def _activate_gui(self):
        """Activate GUI elements when a valid proposal is selected."""
        # Enable main scan controls
        if hasattr(self.ui, 'compositeImageCheckbox'):
            self.ui.compositeImageCheckbox.setEnabled(True)
        self.ui.removeLastImageButton.setEnabled(True)
        self.ui.clearImageButton.setEnabled(True)
        if hasattr(self.ui, 'firstEnergyButton'):
            self.ui.firstEnergyButton.setEnabled(True)
        self.ui.beginScanButton.setEnabled(True)
        self.ui.scanType.setEnabled(True)
        self.ui.scanRegSpinbox.setEnabled(True)
        self.ui.energyRegSpinbox.setEnabled(True)

        # Enable motor controls (these might be disabled by scan type)
        scan_type = self.ui.scanType.currentText()
        if scan_type in ("Image", "Spiral Image", "Double Motor"):
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setEnabled(True)
            for reg in self.scan_region_widgets:
                if hasattr(reg, 'setEnabled'):
                    reg.setEnabled(True)

        # Enable other controls based on scan type
        self.on_scan_type_changed()

    def _deactivate_gui(self):
        """Deactivate GUI elements when no valid proposal is selected."""
        # Disable main scan controls
        if hasattr(self.ui, 'compositeImageCheckbox'):
            self.ui.compositeImageCheckbox.setEnabled(False)
        self.ui.removeLastImageButton.setEnabled(False)
        self.ui.clearImageButton.setEnabled(False)
        if hasattr(self.ui, 'firstEnergyButton'):
            self.ui.firstEnergyButton.setEnabled(False)
        self.ui.toggleSingleEnergy.setEnabled(False)
        self.ui.beginScanButton.setEnabled(False)
        self.ui.scanType.setEnabled(False)
        self.ui.scanRegSpinbox.setEnabled(False)
        self.ui.energyRegSpinbox.setEnabled(False)
        self.ui.roiCheckbox.setEnabled(False)
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.xMotorCombo.setEnabled(False)
        self.ui.yMotorCombo.setEnabled(False)
        self.ui.motors2CursorButton.setEnabled(False)

        # Hide ROIs
        self._hide_rois()
        self.ui.roiCheckbox.setChecked(False)

        # Hide beam position
        if self.beam_position is not None:
            if self.beam_position in self.ui.mainImage.getView().allChildItems():
                self.ui.mainImage.removeItem(self.beam_position)

        # Remove crosshairs
        if self.horizontal_line is not None:
            self.ui.mainImage.removeItem(self.horizontal_line)
            self.horizontal_line = None
        if self.vertical_line is not None:
            self.ui.mainImage.removeItem(self.vertical_line)
            self.vertical_line = None

        # Disable region widgets
        for reg in self.scan_region_widgets:
            if hasattr(reg, 'setEnabled'):
                reg.setEnabled(False)
        for reg in self.energy_region_widgets:
            if hasattr(reg, 'setEnabled'):
                reg.setEnabled(False)

    # ------------------------------------------------------------------
    # Staff password helpers
    # ------------------------------------------------------------------

    def _staff_config_path(self):
        import sys, os
        return os.path.join(sys.prefix, 'pystxmcontrol_cfg', 'main.json')

    def _read_main_json(self):
        import json
        try:
            with open(self._staff_config_path()) as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_main_json(self, data: dict):
        import json
        try:
            with open(self._staff_config_path(), 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.show_error_message(f"Could not save config: {e}")

    def _hash_password(self, password: str, salt: bytes) -> str:
        import hashlib
        return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 260000).hex()

    def _check_staff_password(self) -> bool:
        """Prompt for the staff password. Returns True if authenticated."""
        import os, hashlib
        cfg = self._read_main_json()
        stored_hash = cfg.get('staff_password_hash')
        stored_salt = cfg.get('staff_password_salt')

        if not stored_hash:
            # No password set yet — prompt to create one
            reply = QtWidgets.QMessageBox.question(
                self, "Staff Password",
                "No staff password is set. Set one now?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.set_staff_password()
                # Re-read after setting
                cfg = self._read_main_json()
                stored_hash = cfg.get('staff_password_hash')
                stored_salt = cfg.get('staff_password_salt')
                if not stored_hash:
                    return False  # User cancelled set
            else:
                return False

        password, ok = QtWidgets.QInputDialog.getText(
            self, "Staff Access", "Enter staff password:",
            QtWidgets.QLineEdit.Password
        )
        if not ok or not password:
            return False

        salt = bytes.fromhex(stored_salt)
        return self._hash_password(password, salt) == stored_hash

    def set_staff_password(self):
        """Prompt to set a new staff password and save the hash to main.json."""
        import os
        password, ok = QtWidgets.QInputDialog.getText(
            self, "Set Staff Password", "Enter new staff password:",
            QtWidgets.QLineEdit.Password
        )
        if not ok or not password:
            return

        confirm, ok = QtWidgets.QInputDialog.getText(
            self, "Set Staff Password", "Confirm new staff password:",
            QtWidgets.QLineEdit.Password
        )
        if not ok or confirm != password:
            QtWidgets.QMessageBox.warning(self, "Staff Password", "Passwords do not match.")
            return

        salt = os.urandom(32)
        hashed = self._hash_password(password, salt)
        cfg = self._read_main_json()
        cfg['staff_password_hash'] = hashed
        cfg['staff_password_salt'] = salt.hex()
        self._write_main_json(cfg)
        QtWidgets.QMessageBox.information(self, "Staff Password", "Staff password updated.")

    def _activate_staff(self):
        """Activate staff-only controls."""
        if hasattr(self.ui, 'A1Edit'):
            self.ui.A1Edit.setEnabled(True)
        if hasattr(self.ui, 'serverAddressEdit'):
            self.ui.serverAddressEdit.setEnabled(True)
        if hasattr(self.ui, 'serverConnectButton'):
            self.ui.serverConnectButton.setEnabled(True)

    def _deactivate_staff(self):
        """Deactivate staff-only controls."""
        if hasattr(self.ui, 'A1Edit'):
            self.ui.A1Edit.setEnabled(False)
        if hasattr(self.ui, 'serverAddressEdit'):
            self.ui.serverAddressEdit.setEnabled(False)
        if hasattr(self.ui, 'serverConnectButton'):
            self.ui.serverConnectButton.setEnabled(False)
        
    def _set_warning_banner(self, warning_text):
        """Set or clear the warning banner."""
        if warning_text:
            self.ui.warningLabel.setStyleSheet("color: red; background-color: yellow")
            self.ui.warningLabel.setText(warning_text)
        else:
            self.ui.warningLabel.setStyleSheet("")
            self.ui.warningLabel.setText("")
        
    def test_monitor_plot(self):
        """Test method to add sample monitor data for testing."""
        # Set plot type to Monitor
        self.ui.plotType.setCurrentText("Monitor")
        
        # Add some test data
        import random
        test_values = [random.uniform(0.1, 1.0) for _ in range(20)]
        
        for value in test_values:
            self.controller.image_model.add_monitor_data(value, max_points=500)
            daq_value = value * 10.0
            self.controller.image_model.set('daq_current_value', daq_value)
            
        self.show_error_message("Added 20 test monitor data points. Check the monitor plot!")
        
    def test_scan_compilation(self):
        """Test method to compile scan from current UI settings."""
        # Compile scan from current UI
        if self.controller.compile_scan_from_view(self):
            # Get the compiled scan data
            scan_data = self.controller.get_scan_model().to_dict()

            # Show summary
            scan_regions = scan_data.get('scan_regions', {})
            energy_regions = scan_data.get('energy_regions', {})

            message = f"""Scan compilation successful!

Scan Type: {scan_data.get('scan_type', 'Unknown')}
Motors: X={scan_data.get('x_motor', 'None')}, Y={scan_data.get('y_motor', 'None')}
Scan Regions: {len(scan_regions)}
Energy Regions: {len(energy_regions)}

Scan Regions:
{chr(10).join([f"  {name}: {data}" for name, data in scan_regions.items()])}

Energy Regions:
{chr(10).join([f"  {name}: {data}" for name, data in energy_regions.items()])}
"""
            self.show_error_message(message)
        else:
            self.show_error_message("Scan compilation failed!")

    def disconnect(self):
        """Cleanup and disconnect from server."""
        # This would be called on application exit
        # Cleanup resources, close connections, etc.
        pass