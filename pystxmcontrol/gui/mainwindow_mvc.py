from pystxmcontrol.gui.mainwindow_UI import Ui_MainWindow
from pystxmcontrol.gui.controllers.main_controller import MainController
from pystxmcontrol.gui.energyDef import energyDefWidget
from pystxmcontrol.gui.scanDef import scanRegionDef
from PySide6 import QtWidgets, QtCore
import pyqtgraph as pg
import numpy as np
import qdarktheme


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
        self.current_cursor_x = 0.0
        self.current_cursor_y = 0.0
        
        # Proposal management
        self.esaf_list = []
        self.participants_list = []
        
        # Initialize the controller
        if self.controller.initialize_client():
            self._populate_combo_boxes()
        else:
            # If client initialization fails, populate with defaults
            self._populate_default_combo_boxes()

        # Initialize the view
        self._setup_ui_connections()
        self._setup_controller_connections()
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
        
        # Region controls
        self.ui.scanRegSpinbox.valueChanged.connect(self.update_scan_regions)
        self.ui.energyRegSpinbox.valueChanged.connect(self.update_energy_regions)
        self.ui.roiCheckbox.stateChanged.connect(self.toggle_roi_display)
        self.ui.showRangeFinder.stateChanged.connect(self.toggle_range_roi_display)
        
        # Energy list controls
        self.ui.energyListCheckbox.stateChanged.connect(self.toggle_energy_list)
        self.ui.toggleSingleEnergy.stateChanged.connect(self.toggle_single_energy)
        
        # Proposal controls
        self.ui.proposalComboBox.currentIndexChanged.connect(self.on_proposal_changed)
        
    def _setup_controller_connections(self):
        """Connect controller signals to view update methods."""
        self.controller.motor_position_updated.connect(self.update_motor_position_display)
        self.controller.motor_status_updated.connect(self.update_motor_status_display)
        self.controller.image_updated.connect(self.update_image_display)
        self.controller.scan_progress_updated.connect(self.update_scan_progress_display)
        self.controller.error_occurred.connect(self.show_error_message)
        self.controller.status_updated.connect(self.update_status_display)
        self.controller.monitor_data_updated.connect(self.update_monitor_plot)
        self.controller.daq_value_updated.connect(self.update_daq_value_display)
        self.controller.scan_state_changed.connect(self._set_scan_ui_state)
        self.controller.elapsed_time_updated.connect(self.update_elapsed_time_display)
        
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
        
        # Set up default values
        self.ui.focusRangeEdit.setText('100')
        self.ui.focusStepsEdit.setText('50')
        self.ui.lineLengthEdit.setText('10')
        self.ui.lineAngleEdit.setText('0')
        self.ui.linePointsEdit.setText('50')
        
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

        # Set default pen color and style
        self.default_pen = pg.mkPen(
            self.pen_colors[0],
            width=3,
            style=self.pen_styles[0]
        )
        self.ui.showRangeFinder.setChecked(False)
        self.toggle_range_roi_display()
        
        # Initialize energy list widget as hidden
        self.ui.energyListWidget.setVisible(False)
        
        # Set default single energy state
        self.ui.toggleSingleEnergy.setChecked(True)
        
    def _populate_combo_boxes(self):
        """Populate combo boxes with data from controller."""
        # Populate scan types
        scan_types = self.controller.get_available_scan_types()
        self.ui.scanType.clear()
        for scan_type in scan_types:
            self.ui.scanType.addItem(scan_type)
            
        # Populate motor combo boxes
        motors = self.controller.get_available_motors()
        
        # Clear existing items
        self.ui.motorMover1.clear()
        self.ui.motorMover2.clear()
        self.ui.xMotorCombo.clear()
        self.ui.yMotorCombo.clear()
        
        # Add motors to combo boxes
        for motor in motors:
            self.ui.motorMover1.addItem(motor)
            self.ui.motorMover2.addItem(motor)
            self.ui.xMotorCombo.addItem(motor)
            self.ui.yMotorCombo.addItem(motor)
            
        # Set default selections if motors are available
        if motors:
            # Try to set default motors
            if "SampleX" in motors:
                self.ui.motorMover1.setCurrentText("SampleX")
                self.ui.xMotorCombo.setCurrentText("SampleX")
            if "SampleY" in motors:
                self.ui.motorMover2.setCurrentText("SampleY")
                self.ui.yMotorCombo.setCurrentText("SampleY")
                
        # Populate channel selector (these are usually fixed)
        if self.ui.channelSelect.count() == 0:
            self.ui.channelSelect.addItems(["Diode", "CCD", "RPI"])
            
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
        for combo in [self.ui.motorMover1, self.ui.motorMover2, self.ui.xMotorCombo, self.ui.yMotorCombo]:
            combo.clear()
            for motor in default_motors:
                combo.addItem(motor)
                
        # Set default selections
        self.ui.motorMover1.setCurrentText("SampleX")
        self.ui.motorMover2.setCurrentText("SampleY")
        self.ui.xMotorCombo.setCurrentText("SampleX")
        self.ui.yMotorCombo.setCurrentText("SampleY")
        
        # Populate other combo boxes
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
    def on_scan_type_changed(self):
        """Handle scan type change."""
        scan_type = self.ui.scanType.currentText()
        self.controller.set_scan_type(scan_type)
        self._update_ui_for_scan_type(scan_type)
        
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
        except ValueError:
            self.show_error_message("Invalid A0 value")
            
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

    def update_line_roi(self):
        self._clear_rois()
        self.roi_list.append(self._calculate_line_roi())
        self._show_rois()
            
    def on_mouse_moved(self, pos):
        """Handle mouse movement over image."""
        # Update cursor position display
        scene_pos = self.ui.mainImage.getImageItem().mapFromScene(pos)
        
        # Get image geometry from the image model
        image_model = self.controller.get_image_model()
        scan_type = image_model.get('scan_type')
        y_motor = 'y'
        if "Focus" in scan_type:
            y_motor = 'z'
        x_center = image_model.get('x_center', 0.0)
        y_center = image_model.get(y_motor+'_center', 0.0)
        x_range = image_model.get('x_range', 70.0)
        y_range = image_model.get(y_motor+'_range', 70.0)
        image_scale = image_model.get('image_scale', (1.0, 1.0))
        if "Spectrum" in scan_type:
            energies = np.array(image_model.get('energy_list'))
            image_scale = [image_model.get('x_pts')/energies.size,1.0]
            x_center = (energies.max() + energies.min()) / 2.0
            x_range = energies.max() - energies.min()
        
        print(x_center,x_range,y_center,y_range)

        # Convert to real coordinates based on image geometry
        x_real = (scene_pos.x() * image_scale[0]) + x_center - x_range / 2.0
        y_real = (scene_pos.y() * image_scale[1]) + y_center - y_range / 2.0
        
        # Store current cursor coordinates for use in click events
        self.current_cursor_x = x_real
        self.current_cursor_y = y_real
        
        # Update cursor position labels (note: y-coordinate is negated for display)
        self.ui.xCursorPos.setText(f"{x_real:.3f}")
        self.ui.yCursorPos.setText(f"{-y_real:.3f}")
        
        # Read image intensity at cursor position
        self._update_cursor_intensity(scene_pos)
        
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
        if self.ui.channelSelect.currentText() == "CCD":
            return
            
        # Use the coordinates from the last mouse movement event
        # This avoids coordinate transformation issues when clicking on ROIs
        x_real = self.current_cursor_x
        y_real = self.current_cursor_y
        
        # Pass real coordinates to controller for cursor position tracking
        self.controller.handle_mouse_click(x_real, y_real)
        
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
            monitor_data = self.controller.get_image_model().get('monitor_data', [])
            xdata = idx
            ydata = np.interp(idx,np.arange(len(monitor_data)),monitor_data)
        self.ui.xCursorPos.setText(str(round(xdata,3)))
        self.ui.cursorIntensity.setText(str(round(ydata,3)))
        
    def on_channel_changed(self):
        """Handle channel selection change."""
        channel = self.ui.channelSelect.currentText()
        settings = {'channel_select': channel}
        self.controller.set_image_display_settings(settings)
        
    def on_plot_type_changed(self):
        """Handle plot type change."""
        plot_type = self.ui.plotType.currentText()
        settings = {'plot_type': plot_type}
        self.controller.set_image_display_settings(settings)
        
        # Clear existing plot
        if self.current_plot:
            self.ui.mainPlot.removeItem(self.current_plot)
            self.current_plot = None
            
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
                
        # Update A0 label from motor info (this comes from client config, not motor position)
        motor_model = self.controller.get_motor_model()
        motor_info = motor_model.get('motor_info', {})
        if 'Energy' in motor_info:
            a0_value = motor_info['Energy'].get('A0', 0)
            self.ui.A0Label.setText(f"{int(a0_value)}")
            
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
        if image_data is not None:
            # Get current image geometry settings to maintain coordinate system
            image_model = self.controller.get_image_model()
            x_center = image_model.get('x_center', 0.0)
            y_center = image_model.get('y_center', 0.0) 
            x_range = image_model.get('x_range', 70.0)
            y_range = image_model.get('y_range', 70.0)
            image_scale = image_model.get('image_scale', (0.7, 0.7))
            if "Spectrum" in image_model.get('scan_type'):
                energies = np.array(image_model.get('energy_list'))
                image_scale = [image_model.get('x_pts')/energies.size,1.0]
                y_center = 0.0
                y_range = energies.max() - energies.min()
                image_data = image_data.T
            
            # Calculate position to center the image at the motor coordinate center
            pos = (x_center - x_range / 2.0, y_center - y_range / 2.0)
            
            # Update image while preserving coordinate system
            self.ui.mainImage.setImage(
                image_data.T, 
                autoRange=self.ui.autorangeCheckbox.isChecked(),
                autoLevels=self.ui.autoscaleCheckbox.isChecked(),
                pos=pos,
                scale=image_scale
            )
            
    def update_scan_progress_display(self, progress_info: str):
        """Update scan progress display."""
        self.ui.imageCountText.setText(progress_info)
        
    def show_error_message(self, error_message: str):
        """Show error message to user."""
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Critical)
        msg.setText("Error!")
        msg.setInformativeText(error_message)
        msg.setWindowTitle("Error")
        msg.exec()
        
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
        # Compile scan to calculate estimated time
            self.controller.compile_scan_from_view(self)
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
        self.ui.beamToCursorButton.setEnabled(False)
        self.ui.focusToCursorButton.setEnabled(False)
        
        # Set motor combos based on scan config if available
        if hasattr(self.controller.client, 'scanConfig') and self.controller.client.scanConfig:
            scan_config = self.controller.client.scanConfig.get("scans", {})
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
            
            # Set focus parameters
            try:
                motor_positions = self.controller.get_motor_model().get('current_positions', {})
                zone_plate_z = motor_positions.get('ZonePlateZ', 0)
                self.ui.focusCenterEdit.setText(f"{zone_plate_z:.2f}")
            except:
                pass
                
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
            self.ui.toggleSingleEnergy.setChecked(True)
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
                
        # Update ROI display based on current image type
        current_image_type = self.controller.get_image_model().get('scan_type')
        if "Image" in current_image_type:
            self.ui.roiCheckbox.setChecked(True)
            self.ui.roiCheckbox.setEnabled(True)
        else:
            self.ui.roiCheckbox.setChecked(False)
            self.ui.roiCheckbox.setEnabled(False)
            
    def _set_scan_ui_state(self, scanning: bool):

        """Set UI state for scanning/not scanning.  This function is called with the controller emits
        scan_state_changed.  That occurs when a scan starts, completes or is cancelled."""
        
        # Basic scan controls
        self.ui.beginScanButton.setEnabled(not scanning)
        self.ui.cancelButton.setEnabled(scanning)
        self.ui.scanType.setEnabled(not scanning)
        self.ui.scanRegSpinbox.setEnabled(not scanning)
        self.ui.energyRegSpinbox.setEnabled(not scanning)
        
        # Image controls
        self.ui.compositeImageCheckbox.setEnabled(not scanning)
        self.ui.removeLastImageButton.setEnabled(not scanning)
        self.ui.clearImageButton.setEnabled(not scanning)
        self.ui.firstEnergyButton.setEnabled(not scanning)
        self.ui.toggleSingleEnergy.setEnabled(not scanning)
        
        # Motor controls
        self.ui.xMotorCombo.setEnabled(not scanning)
        self.ui.yMotorCombo.setEnabled(not scanning)
        self.ui.beamToCursorButton.setEnabled(not scanning)
        self.ui.focusToCursorButton.setEnabled(not scanning)
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
        if scanning:
            self._hide_rois()
        self._update_ui_for_scan_type(self.controller.get_image_model().get('scan_type'))
        
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
        monitor_data = self.controller.get_image_model().get('monitor_data', [])
        
        # Remove existing plot
        if self.current_plot:
            self.ui.mainPlot.removeItem(self.current_plot)
            self.current_plot = None
        
        # Plot new data if available
        if monitor_data:
            self.current_plot = self.ui.mainPlot.plot(
                np.array(monitor_data),
                pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine),
                symbol='o', symbolPen='g', symbolSize=3,
                symbolBrush=(0, 255, 0)
            )
            # Set plot labels
            self.ui.mainPlot.setLabel("bottom", "Monitor")
            self.ui.mainPlot.setLabel("left", "Intensity")
            
            # Auto-scale the plot for better visibility
            self.ui.mainPlot.getPlotItem().getViewBox().autoRange()
            
    def _show_motor_scan_plot(self):
        """Show motor scan data plot."""
        image_model = self.controller.get_image_model()
        x_data = image_model.get('motor_scan_x_data', [])
        y_data = image_model.get('motor_scan_y_data', [])
        
        if x_data and y_data and self.current_plot:
            self.ui.mainPlot.removeItem(self.current_plot)
            
        if x_data and y_data:
            self.current_plot = self.ui.mainPlot.plot(
                np.array(x_data), np.array(y_data),
                pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine),
                symbol='o', symbolPen='g', symbolSize=3,
                symbolBrush=(255, 255, 255)
            )
            
    # File operations
    def open_scan_file(self):
        """Open scan file dialog."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Scan File', '', 'STXM Files (*.stxm);;All Files (*)'
        )
        if filename:
            # Load scan file through controller
            pass
            
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
        if filename:
            # Load energy definition through controller
            pass
            
    def open_scan_definition(self):
        """Open scan definition dialog."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Scan Definition', '', 'JSON Files (*.json);;All Files (*)'
        )
        if filename:
            self.controller.load_scan_definition(filename)
            
    # Theme and appearance
    def set_light_theme(self):
        """Set light theme."""
        self.static_style = "color: black;"
        self.setStyleSheet(qdarktheme.load_stylesheet("light"))
        
    def set_dark_theme(self):
        """Set dark theme."""
        self.static_style = "color: white;"
        self.setStyleSheet(qdarktheme.load_stylesheet())
        
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
        
        # Add widgets if needed
        while current_count < requested_count:
            widget = energyDefWidget()
            widget.energyDef.regNum.setText(f"Region {current_count + 1}")
            
            # Set default values for new energy region widgets
            widget.energyDef.energyStart.setText("700")
            widget.energyDef.energyStop.setText("720")
            widget.energyDef.energyStep.setText("1")
            widget.energyDef.nEnergies.setText("21")
            widget.energyDef.dwellTime.setText("1")
            
            self.ui.energyDefWidget.addWidget(widget.widget)
            self.energy_region_widgets.append(widget)
            current_count += 1
            
        # Apply current single energy state to all widgets
        self.toggle_single_energy()
            
        # Remove widgets if needed
        while current_count > requested_count:
            widget = self.energy_region_widgets.pop()
            self.ui.energyDefWidget.removeWidget(widget.widget)
            widget.widget.deleteLater()
            current_count -= 1
            
    def toggle_energy_list(self):
        """Toggle between energy regions and energy list."""
        if self.ui.energyListCheckbox.isChecked():
            # Switch to energy list mode
            self.ui.toggleSingleEnergy.setChecked(False)
            
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
        for energy_widget in self.energy_region_widgets:
            if hasattr(energy_widget, 'energyDef'):
                # Enable/disable controls based on single energy mode
                energy_widget.energyDef.energyStop.setEnabled(not is_single_energy)
                energy_widget.energyDef.energyStep.setEnabled(not is_single_energy)
                energy_widget.energyDef.nEnergies.setEnabled(not is_single_energy)
                
                # When switching to single energy mode, set step and N energies to 1
                if is_single_energy:
                    energy_widget.energyDef.energyStep.setText("1")
                    energy_widget.energyDef.nEnergies.setText("1")
                    # Set stop energy equal to start energy for single energy
                    start_energy = energy_widget.energyDef.energyStart.text()
                    energy_widget.energyDef.energyStop.setText(start_energy)
                    
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
                config_scan_type = self.controller.client.scanConfig.get("scans", {}).get(scan_type, {}).get("type", "image")
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
        
        region_widget = self.scan_region_widgets[-1]
        x_center = float(region_widget.ui.xCenter.text() or 0)
        y_center = float(region_widget.ui.yCenter.text() or 0)
        line_length = float(self.ui.lineLengthEdit.text() or 10)
        line_angle = float(self.ui.lineAngleEdit.text() or 0)

        # Apply coordinate system transformation (y-axis flip)
        # The region widget stores y in "display" coordinates, but ROI needs "motor" coordinates
        y_center_motor = -y_center
        
        # Convert angle from degrees to radians
        angle_rad = np.radians(line_angle)
        
        # Calculate half-length offsets
        half_length = line_length / 2
        dx = half_length * np.cos(angle_rad)
        dy = half_length * np.sin(angle_rad)
        
        # Calculate endpoints based on center position, length, and angle
        x1 = x_center - dx
        y1 = y_center_motor - dy
        x2 = x_center + dx
        y2 = y_center_motor + dy

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
            
            # Apply coordinate system transformation (y-axis flip)
            # The region widget stores y in "display" coordinates, but ROI needs "motor" coordinates
            y_center_motor = -y_center
            
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
            y_min = y_center_motor - y_range / 2
            
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
                        positions=((x_min, y_center_motor), (x_max, y_center_motor)), 
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
                    config_scan_type = self.controller.client.scanConfig.get("scans", {}).get(scan_type, {}).get("type", "image")
                except:
                    pass
            
            # Update region widget based on ROI type
            if isinstance(sender_roi, pg.RectROI):
                # Get ROI position and size
                roi_pos = sender_roi.pos()
                roi_size = sender_roi.size()
                
                # Calculate center and range in motor coordinates
                x_center = roi_pos.x() + roi_size.x() / 2
                y_center_motor = roi_pos.y() + roi_size.y() / 2
                x_range = roi_size.x()
                y_range = roi_size.y()
                
                # Convert y-coordinate back to display coordinates (flip y-axis)
                y_center = -y_center_motor
                
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
                    pos1 = sender_roi.mapSceneToParent(handles[0].scenePos())
                    pos2 = sender_roi.mapSceneToParent(handles[1].scenePos())
                    
                    # Calculate line center and length
                    x_center = (pos1.x() + pos2.x()) / 2
                    y_center_motor = (pos1.y() + pos2.y()) / 2
                    y_center = -y_center_motor  # Convert to display coordinates
                    
                    line_length = ((pos2.x() - pos1.x())**2 + (pos2.y() - pos1.y())**2)**0.5
                    
                    # Update the region widget
                    region_widget.regionChanged.disconnect()
                    
                    region_widget.ui.xCenter.setText(f"{x_center:.3f}")
                    region_widget.ui.yCenter.setText(f"{y_center:.3f}")
                    region_widget.ui.xRange.setText(f"{line_length:.3f}")
                    
                    # For line spectrum, update the line length edit as well
                    if hasattr(self.ui, 'lineLengthEdit'):
                        self.ui.lineLengthEdit.setText(f"{line_length:.3f}")
                        self.update_line_step_size()
                    
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
        self.ui.mainImage.clear()
        self.controller.get_image_model().clear_image_stack()
        
    def remove_last_image(self):
        """Remove the last image."""
        # This would need to be implemented based on the image stack
        pass
        
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
                # Activate GUI but warn about data access
                self._activate_gui()
                self._set_warning_banner("Users cannot access this data!")
                self.ui.experimentersLineEdit.setText("")
                
            elif selected_index > 0 and selected_index <= len(self.esaf_list):
                # Valid proposal selected
                try:
                    # Get participant list for this proposal
                    participants = self.participants_list[selected_index - 1]  # -1 because index 0 is "Select a Proposal"
                    
                    # Create comma-separated string of participants
                    if participants:
                        participant_string = participants[0]
                        for i in range(1, len(participants)):
                            participant_string += ',' + participants[i]
                        self.ui.experimentersLineEdit.setText(participant_string)
                    else:
                        self.ui.experimentersLineEdit.setText("")
                    
                    # Activate GUI and clear warning
                    self._activate_gui()
                    self._set_warning_banner(None)
                    
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
                
        except Exception as e:
            print(f"Error handling proposal change: {e}")
            
    def _activate_gui(self):
        """Activate GUI elements when a valid proposal is selected."""
        # Enable main scan controls
        self.ui.beginScanButton.setEnabled(True)
        self.ui.scanType.setEnabled(True)
        self.ui.scanRegSpinbox.setEnabled(True)
        self.ui.energyRegSpinbox.setEnabled(True)
        
        # Enable motor controls (these might be disabled by scan type)
        scan_type = self.ui.scanType.currentText()
        if scan_type in ("Image", "Spiral Image", "Double Motor"):
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setEnabled(True)
            
        # Enable other controls based on scan type
        self.on_scan_type_changed()
        
    def _deactivate_gui(self):
        """Deactivate GUI elements when no valid proposal is selected."""
        # Disable main scan controls
        self.ui.beginScanButton.setEnabled(False)
        self.ui.scanType.setEnabled(False)
        self.ui.scanRegSpinbox.setEnabled(False)
        self.ui.energyRegSpinbox.setEnabled(False)
        self.ui.roiCheckbox.setEnabled(False)
        self.ui.toggleSingleEnergy.setEnabled(False)
        
        # Hide ROIs
        self._hide_rois()
        self.ui.roiCheckbox.setChecked(False)
        
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