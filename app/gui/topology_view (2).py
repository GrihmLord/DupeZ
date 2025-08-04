# app/gui/topology_view.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, 
                              QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
                              QGraphicsTextItem, QGraphicsLineItem, QGraphicsRectItem,
                              QPushButton, QLabel, QComboBox, QSlider, QGroupBox,
                              QFormLayout, QSpinBox, QCheckBox, QMenu,
                              QToolTip, QMessageBox, QFileDialog)
from PyQt6.QtGui import QPen, QBrush, QColor, QFont, QPainter, QPainterPath, QRadialGradient, QAction, QPixmap
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QPropertyAnimation, QEasingCurve, QObject
from typing import Dict, List, Optional, Tuple, Any
import math
import json
import time
from datetime import datetime
from app.logs.logger import log_info, log_error
from app.core.state import Device

class NetworkNode(QGraphicsEllipseItem, QObject):
    """Network device node in the topology view"""
    
    # Signals
    device_selected = pyqtSignal(str)  # Emit device IP when selected
    device_blocked = pyqtSignal(str)   # Emit device IP when blocked
    device_unblocked = pyqtSignal(str) # Emit device IP when unblocked
    
    def __init__(self, device: Device, x: float, y: float, radius: float = 30):
        QGraphicsEllipseItem.__init__(self, x - radius, y - radius, radius * 2, radius * 2)
        QObject.__init__(self)
        self.device = device
        self.radius = radius
        self.is_selected = False
        self.is_hovered = False
        self.connections = []
        self.traffic_flow = 0.0
        self.risk_score = 0.0
        
        # Set up appearance
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setAcceptHoverEvents(True)
        
        # Create gradient
        self.gradient = QRadialGradient(0, 0, radius)
        self.update_appearance()
        
        # Add device info text
        self.text_item = QGraphicsTextItem(self)
        self.text_item.setPlainText(device.ip)
        self.text_item.setDefaultTextColor(QColor(255, 255, 255))
        self.text_item.setFont(QFont("Consolas", 8))
        self.text_item.setPos(-radius + 5, -radius + 5)
        
        # Add hostname if available
        if hasattr(device, 'hostname') and device.hostname and device.hostname != "Unknown":
            self.hostname_item = QGraphicsTextItem(self)
            self.hostname_item.setPlainText(device.hostname)
            self.hostname_item.setDefaultTextColor(QColor(200, 200, 200))
            self.hostname_item.setFont(QFont("Consolas", 6))
            self.hostname_item.setPos(-radius + 5, -radius + 15)
    
    def update_appearance(self):
        """Update node appearance based on device state"""
        # Determine base color based on device type
        if hasattr(self.device, 'is_gaming_device') and self.device.is_gaming_device:
            base_color = QColor(255, 165, 0)  # Orange for gaming
        elif hasattr(self.device, 'is_router') and self.device.is_router:
            base_color = QColor(0, 255, 255)  # Cyan for router
        elif hasattr(self.device, 'is_mobile') and self.device.is_mobile:
            base_color = QColor(255, 192, 203)  # Pink for mobile
        else:
            base_color = QColor(100, 150, 255)  # Blue for regular devices
        
        # Color based on device type only (risk score removed)
        
        # Create gradient
        self.gradient.setColorAt(0, base_color.lighter(150))
        self.gradient.setColorAt(0.7, base_color)
        self.gradient.setColorAt(1, base_color.darker(150))
        
        # Set brush and pen
        self.setBrush(QBrush(self.gradient))
        
        if self.is_selected:
            self.setPen(QPen(QColor(255, 255, 0), 3))  # Yellow border for selected
        elif self.is_hovered:
            self.setPen(QPen(QColor(255, 255, 255), 2))  # White border for hovered
        else:
            self.setPen(QPen(QColor(0, 0, 0), 1))  # Black border for normal
        
        # Add traffic flow indicator
        if self.traffic_flow > 0:
            self._add_traffic_indicator()
    
    def _add_traffic_indicator(self):
        """Add visual indicator for traffic flow"""
        # Create a smaller circle inside to show traffic
        traffic_radius = self.radius * 0.6
        traffic_color = QColor(0, 255, 0) if self.traffic_flow < 100 else QColor(255, 165, 0)
        
        # Remove existing traffic indicator
        for child in self.childItems():
            if isinstance(child, QGraphicsEllipseItem) and child != self.text_item:
                self.scene().removeItem(child)
        
        # Add new traffic indicator
        traffic_indicator = QGraphicsEllipseItem(
            -traffic_radius, -traffic_radius, 
            traffic_radius * 2, traffic_radius * 2, 
            self
        )
        traffic_indicator.setBrush(QBrush(traffic_color))
        traffic_indicator.setPen(QPen(QColor(0, 0, 0), 1))
    
    def hoverEnterEvent(self, event):
        """Handle hover enter event"""
        self.is_hovered = True
        self.update_appearance()
        
        # Show tooltip with device info
        hostname = getattr(self.device, 'hostname', 'Unknown')
        mac = getattr(self.device, 'mac', 'Unknown')
        vendor = getattr(self.device, 'vendor', 'Unknown')
        blocked = getattr(self.device, 'blocked', False)
        
        tooltip_text = f"""
Device: {self.device.ip}
Hostname: {hostname}
MAC: {mac}
Vendor: {vendor}
Traffic: {self.traffic_flow:.1f} KB/s
Status: {'Blocked' if blocked else 'Active'}
        """.strip()
        
        QToolTip.showText(event.screenPos(), tooltip_text)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Handle hover leave event"""
        self.is_hovered = False
        self.update_appearance()
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """Handle mouse press events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.device_selected.emit(self.device.ip)
        super().mousePressEvent(event)
    
    def contextMenuEvent(self, event):
        """Show context menu for device actions"""
        try:
            menu = QMenu()
            
            # Device info
            info_action = QAction(f"📱 {self.device.ip}", menu)
            info_action.setEnabled(False)
            menu.addAction(info_action)
            
            if hasattr(self.device, 'hostname') and self.device.hostname and self.device.hostname != "Unknown":
                hostname_action = QAction(f"🏷️ {self.device.hostname}", menu)
                hostname_action.setEnabled(False)
                menu.addAction(hostname_action)
            
            menu.addSeparator()
            
            # Block/Unblock action
            if hasattr(self.device, 'blocked') and self.device.blocked:
                unblock_action = QAction("🔓 Unblock Device", menu)
                unblock_action.triggered.connect(self._unblock_device)
                menu.addAction(unblock_action)
            else:
                block_action = QAction("🔒 Block Device", menu)
                block_action.triggered.connect(self._block_device)
                menu.addAction(block_action)
            
            # Traffic analysis
            analyze_action = QAction("📊 Analyze Traffic", menu)
            analyze_action.triggered.connect(self._analyze_traffic)
            menu.addAction(analyze_action)
            
            # Device details
            details_action = QAction("ℹ️ Device Details", menu)
            details_action.triggered.connect(self._show_details)
            menu.addAction(details_action)
            
            # Show menu
            menu.exec(event.screenPos())
            
        except Exception as e:
            log_error(f"Error showing device context menu: {e}")
    
    def _block_device(self):
        """Block this device"""
        try:
            self.device_blocked.emit(self.device.ip)
            log_info(f"🔒 Blocking device: {self.device.ip}")
        except Exception as e:
            log_error(f"Error blocking device {self.device.ip}: {e}")
    
    def _unblock_device(self):
        """Unblock this device"""
        try:
            self.device_unblocked.emit(self.device.ip)
            log_info(f"🔓 Unblocking device: {self.device.ip}")
        except Exception as e:
            log_error(f"Error unblocking device {self.device.ip}: {e}")
    
    def _analyze_traffic(self):
        """Analyze traffic for this device"""
        try:
            log_info(f"Analyzing traffic for device: {self.device.ip}")
            # This would trigger traffic analysis for the device
        except Exception as e:
            log_error(f"Error analyzing traffic for device {self.device.ip}: {e}")
    
    def _show_details(self):
        """Show device details"""
        try:
            hostname = getattr(self.device, 'hostname', 'Unknown')
            mac = getattr(self.device, 'mac', 'Unknown')
            status = getattr(self.device, 'status', 'Unknown')
            blocked = getattr(self.device, 'blocked', False)
            
            details = f"""
Device Details:
IP: {self.device.ip}
MAC: {mac}
Hostname: {hostname}
Status: {status}
Traffic: {self.traffic_flow:.2f} KB/s
Blocked: {blocked}
            """
            log_info(f"ℹ️ Device details for {self.device.ip}: {details}")
        except Exception as e:
            log_error(f"Error showing details for device {self.device.ip}: {e}")
    
    def _get_device_type(self) -> str:
        """Get device type string"""
        try:
            # Check if device has the expected attributes, with fallbacks
            if hasattr(self.device, 'is_gaming_device') and self.device.is_gaming_device:
                return "Gaming"
            elif hasattr(self.device, 'is_router') and self.device.is_router:
                return "Router"
            elif hasattr(self.device, 'is_mobile') and self.device.is_mobile:
                return "Mobile"
            elif hasattr(self.device, 'device_type') and self.device.device_type:
                return self.device.device_type
            else:
                return "Device"
        except Exception as e:
            log_error(f"Error getting device type for {self.device.ip}: {e}")
            return "Unknown"

class NetworkConnection(QGraphicsLineItem, QObject):
    """Connection between network nodes"""
    
    def __init__(self, source_node: NetworkNode, target_node: NetworkNode):
        QGraphicsLineItem.__init__(self)
        QObject.__init__(self)
        self.source_node = source_node
        self.target_node = target_node
        self.traffic_flow = 0.0
        self.connection_type = "ethernet"  # ethernet, wifi, etc.
        
        # Add connection to nodes
        source_node.connections.append(self)
        target_node.connections.append(self)
        
        # Set up appearance
        self.setPen(QPen(QColor(100, 100, 100), 2))
        self.update_position()
        self.update_appearance()
    
    def update_position(self):
        """Update connection line position"""
        source_pos = self.source_node.pos()
        target_pos = self.target_node.pos()
        
        # Calculate line between node centers
        line = QPointF(target_pos.x() - source_pos.x(), target_pos.y() - source_pos.y())
        length = math.sqrt(line.x() ** 2 + line.y() ** 2)
        
        if length > 0:
            # Normalize and scale to node radius
            normalized = line / length
            start_point = source_pos + normalized * self.source_node.radius
            end_point = target_pos - normalized * self.target_node.radius
            
            self.setLine(start_point.x(), start_point.y(), end_point.x(), end_point.y())
    
    def update_appearance(self):
        """Update connection appearance based on traffic and type"""
        if self.connection_type == "blocked":
            color = QColor(255, 0, 0)  # Red for blocked
            width = 3
        elif self.connection_type == "suspicious":
            color = QColor(255, 255, 0)  # Yellow for suspicious
            width = 2
        else:
            # Color based on traffic flow
            if self.traffic_flow > 100:
                color = QColor(0, 255, 0)  # Green for high traffic
                width = 3
            elif self.traffic_flow > 10:
                color = QColor(255, 165, 0)  # Orange for medium traffic
                width = 2
            else:
                color = QColor(128, 128, 128)  # Gray for low traffic
                width = 1
        
        self.setPen(QPen(color, width))
    
    def set_traffic_flow(self, flow: float):
        """Set traffic flow for this connection"""
        self.traffic_flow = flow
        self.update_appearance()

class NetworkTopologyView(QWidget):
    """Network topology visualization widget"""
    
    # Signals
    device_selected = pyqtSignal(str)  # Emit device IP when selected
    device_blocked = pyqtSignal(str)   # Emit device IP when blocked
    device_unblocked = pyqtSignal(str) # Emit device IP when unblocked
    
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.nodes: Dict[str, NetworkNode] = {}
        self.connections: List[NetworkConnection] = []
        self.layout_mode = "circular"  # circular, grid, force_directed
        self.auto_layout = True
        self.show_traffic = True
        self.show_connections = True
        self.animation_enabled = True
        
        self.init_ui()
        self.setup_animation_timer()
    
    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Graphics view
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        
        # Set scene size
        self.scene.setSceneRect(-500, -500, 1000, 1000)
        
        layout.addWidget(self.view)
        self.setLayout(layout)
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel"""
        panel = QWidget()
        layout = QHBoxLayout()
        
        # Layout controls
        layout_group = QGroupBox("🗺️ Layout")
        layout_form = QFormLayout()
        
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Circular", "Grid", "Force Directed"])
        self.layout_combo.currentTextChanged.connect(self.change_layout)
        layout_form.addRow("Layout Mode:", self.layout_combo)
        
        self.auto_layout_checkbox = QCheckBox("Auto Layout")
        self.auto_layout_checkbox.setChecked(self.auto_layout)
        self.auto_layout_checkbox.toggled.connect(self.toggle_auto_layout)
        layout_form.addRow("Auto Layout:", self.auto_layout_checkbox)
        
        layout_group.setLayout(layout_form)
        layout.addWidget(layout_group)
        
        # Display controls
        display_group = QGroupBox("👁️ Display")
        display_form = QFormLayout()
        
        self.show_traffic_checkbox = QCheckBox("Show Traffic")
        self.show_traffic_checkbox.setChecked(self.show_traffic)
        self.show_traffic_checkbox.toggled.connect(self.toggle_traffic_display)
        display_form.addRow("Traffic:", self.show_traffic_checkbox)
        
        self.show_connections_checkbox = QCheckBox("Show Connections")
        self.show_connections_checkbox.setChecked(self.show_connections)
        self.show_connections_checkbox.toggled.connect(self.toggle_connections_display)
        display_form.addRow("Connections:", self.show_connections_checkbox)
        
        self.animation_checkbox = QCheckBox("Animations")
        self.animation_checkbox.setChecked(self.animation_enabled)
        self.animation_checkbox.toggled.connect(self.toggle_animations)
        display_form.addRow("Animations:", self.animation_checkbox)
        
        display_group.setLayout(display_form)
        layout.addWidget(display_group)
        
        # Action buttons
        action_group = QGroupBox("⚡ Actions")
        action_layout = QVBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_topology)
        action_layout.addWidget(self.refresh_btn)
        
        self.export_btn = QPushButton("💾 Export")
        self.export_btn.clicked.connect(self.export_topology)
        action_layout.addWidget(self.export_btn)
        
        self.fit_view_btn = QPushButton("🔍 Fit View")
        self.fit_view_btn.clicked.connect(self.fit_view)
        action_layout.addWidget(self.fit_view_btn)
        
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)
        
        panel.setLayout(layout)
        return panel
    
    def setup_animation_timer(self):
        """Setup timer for animations"""
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animations)
        # self.animation_timer.start(100)  # DISABLED - causes performance issues
        
        # Setup auto-update timer for topology (disabled to prevent loops)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.auto_update_topology)
        # self.update_timer.start(5000)  # DISABLED - causes loops with dashboard timer
    
    def update_animations(self):
        """Update animations"""
        if not self.animation_enabled:
            return
        
        # Animate traffic flow
        for connection in self.connections:
            if connection.traffic_flow > 0:
                # Create pulsing effect
                current_pen = connection.pen()
                color = current_pen.color()
                alpha = int(128 + 127 * math.sin(time.time() * 2))
                color.setAlpha(alpha)
                connection.setPen(QPen(color, current_pen.width()))
    
    def auto_update_topology(self):
        """Automatically update topology with current devices"""
        # Loop prevention - don't auto-update if already updating
        if hasattr(self, '_auto_updating') and self._auto_updating:
            return
            
        try:
            self._auto_updating = True
            if self.controller:
                devices = self.controller.get_devices()
                if devices:
                    self.update_topology(devices)
        except Exception as e:
            log_error(f"Auto topology update failed: {e}")
        finally:
            self._auto_updating = False
    
    def update_topology(self, devices: List[Device], traffic_data: Dict[str, float] = None):
        """Update the topology with new device data"""
        # Loop prevention - don't update if already updating
        if hasattr(self, '_updating') and self._updating:
            log_info("Topology update skipped - already in progress")
            return
            
        try:
            self._updating = True
            log_info(f"Updating topology with {len(devices) if devices else 0} devices")
            
            # Clear existing topology
            self.scene.clear()
            self.nodes.clear()
            self.connections.clear()
            
            if not devices:
                # Show placeholder when no devices
                log_info("No devices found, showing placeholder")
                self._show_placeholder()
                return
            
            # Add devices to topology
            for device in devices:
                self.add_device(device)
            
            # Create connections between devices
            self.create_connections()
            
            # Apply layout
            self.apply_layout()
            
            # Update traffic data if provided
            if traffic_data:
                self.update_traffic_data(traffic_data)
            
            # Fit view to show all devices
            self.fit_view()
            
            log_info(f"Topology updated with {len(devices)} devices")
            
        except Exception as e:
            log_error(f"Error updating topology: {e}")
            self._show_placeholder()
        finally:
            # Always reset the flag
            self._updating = False
    
    def _show_placeholder(self):
        """Show placeholder when no devices are available"""
        try:
            # Get the view size for proper centering
            view_rect = self.view.viewport().rect()
            center_x = view_rect.width() / 2
            center_y = view_rect.height() / 2
            
            # Create placeholder text
            placeholder = QGraphicsTextItem("📊 Network Topology")
            placeholder.setDefaultTextColor(QColor(100, 100, 100))
            placeholder.setFont(QFont("Arial", 18, QFont.Weight.Bold))
            
            # Center the placeholder
            text_rect = placeholder.boundingRect()
            placeholder.setPos(center_x - text_rect.width() / 2, center_y - text_rect.height() / 2 - 30)
            
            self.scene.addItem(placeholder)
            
            # Add subtitle
            subtitle = QGraphicsTextItem("No devices found. Run a network scan to discover devices.")
            subtitle.setDefaultTextColor(QColor(150, 150, 150))
            subtitle.setFont(QFont("Arial", 12))
            
            subtitle_rect = subtitle.boundingRect()
            subtitle.setPos(center_x - subtitle_rect.width() / 2, center_y + 20)
            
            self.scene.addItem(subtitle)
            
            # Add instruction text
            instruction = QGraphicsTextItem("Click 'Scan Network' in the Network Scanner tab to discover devices")
            instruction.setDefaultTextColor(QColor(120, 120, 120))
            instruction.setFont(QFont("Arial", 10))
            
            instruction_rect = instruction.boundingRect()
            instruction.setPos(center_x - instruction_rect.width() / 2, center_y + 60)
            
            self.scene.addItem(instruction)
            
            log_info("Topology placeholder displayed")
            
        except Exception as e:
            log_error(f"Error showing topology placeholder: {e}")
    
    def add_device(self, device: Device):
        """Add a device to the topology"""
        try:
            # Calculate position (simple grid layout for now)
            x = (len(self.nodes) % 5) * 150
            y = (len(self.nodes) // 5) * 150
            
            # Create network node
            node = NetworkNode(device, x, y)
            self.nodes[device.ip] = node
            self.scene.addItem(node)
            
            # Connect signals
            node.device_selected.connect(self.device_selected.emit)
            node.device_blocked.connect(self.device_blocked.emit)
            node.device_unblocked.connect(self.device_unblocked.emit)
            
        except Exception as e:
            log_error(f"Error adding device {device.ip} to topology: {e}")
    
    def create_connections(self):
        """Create connections between devices"""
        try:
            device_ips = list(self.nodes.keys())
            
            # Create connections to gateway/router (first device)
            if len(device_ips) > 1:
                gateway_ip = device_ips[0]  # Assume first device is gateway
                
                for device_ip in device_ips[1:]:
                    if device_ip in self.nodes and gateway_ip in self.nodes:
                        source_node = self.nodes[gateway_ip]
                        target_node = self.nodes[device_ip]
                        
                        connection = NetworkConnection(source_node, target_node)
                        self.connections.append(connection)
                        self.scene.addItem(connection)
            
            log_info(f"Created {len(self.connections)} connections in topology")
            
        except Exception as e:
            log_error(f"Error creating topology connections: {e}")
    
    def apply_layout(self):
        """Apply layout algorithm to arrange devices"""
        try:
            if not self.nodes:
                return
            
            # Use circular layout for better visualization
            self.apply_circular_layout()
            
        except Exception as e:
            log_error(f"Error applying topology layout: {e}")
    
    def apply_circular_layout(self):
        """Apply circular layout to arrange devices in a circle"""
        try:
            if not self.nodes:
                return
            
            # Calculate center and radius
            center_x = 0
            center_y = 0
            radius = 200
            
            # Position devices in a circle
            device_ips = list(self.nodes.keys())
            angle_step = 2 * math.pi / len(device_ips)
            
            for i, device_ip in enumerate(device_ips):
                if device_ip in self.nodes:
                    angle = i * angle_step
                    x = center_x + radius * math.cos(angle)
                    y = center_y + radius * math.sin(angle)
                    
                    # Animate node movement
                    node = self.nodes[device_ip]
                    self.animate_node_movement(node, x, y)
            
        except Exception as e:
            log_error(f"Error applying circular layout: {e}")
    
    def apply_grid_layout(self):
        """Apply grid layout"""
        if not self.nodes:
            return
        
        cols = int(math.ceil(math.sqrt(len(self.nodes))))
        spacing = 150
        
        for i, (ip, node) in enumerate(self.nodes.items()):
            row = i // cols
            col = i % cols
            
            x = (col - cols // 2) * spacing
            y = (row - len(self.nodes) // cols // 2) * spacing
            
            if self.animation_enabled:
                self.animate_node_movement(node, x, y)
            else:
                node.setPos(x, y)
            
            # Update connections
            for connection in node.connections:
                connection.update_position()
    
    def apply_force_directed_layout(self):
        """Apply force-directed layout (simplified)"""
        # This is a simplified version - in a real implementation,
        # you'd use a proper force-directed algorithm
        self.apply_circular_layout()
    
    def animate_node_movement(self, node: NetworkNode, target_x: float, target_y: float):
        """Animate node movement to target position"""
        try:
            # Use a timer-based animation instead of QPropertyAnimation to avoid crashes
            current_pos = node.pos()
            target_pos = QPointF(target_x, target_y)
            
            # Calculate distance and steps
            distance = math.sqrt((target_x - current_pos.x())**2 + (target_y - current_pos.y())**2)
            if distance < 1:  # Already at target
                return
                
            # Create a simple timer-based animation
            animation_timer = QTimer()
            animation_timer.setSingleShot(False)
            animation_timer.setInterval(16)  # ~60 FPS
            
            start_x, start_y = current_pos.x(), current_pos.y()
            steps = max(10, int(distance / 5))  # At least 10 steps
            current_step = 0
            
            def animate_step():
                nonlocal current_step
                if current_step >= steps:
                    animation_timer.stop()
                    node.setPos(target_pos)
                    return
                    
                # Linear interpolation
                progress = current_step / steps
                # Apply easing curve (ease-out)
                eased_progress = 1 - (1 - progress) ** 3
                
                new_x = start_x + (target_x - start_x) * eased_progress
                new_y = start_y + (target_y - start_y) * eased_progress
                
                node.setPos(new_x, new_y)
                current_step += 1
            
            animation_timer.timeout.connect(animate_step)
            animation_timer.start()
            
        except Exception as e:
            log_error(f"Error animating node movement: {e}")
            # Fallback: move node directly without animation
            try:
                node.setPos(target_x, target_y)
            except Exception as fallback_error:
                log_error(f"Fallback movement also failed: {fallback_error}")
    
    def update_traffic_data(self, traffic_data: Dict[str, float]):
        """Update traffic data for devices"""
        try:
            for device_ip, traffic_flow in traffic_data.items():
                if device_ip in self.nodes:
                    node = self.nodes[device_ip]
                    node.traffic_flow = traffic_flow
                    node.update_appearance()
            
            # Update connections with traffic flow
            for connection in self.connections:
                connection.update_appearance()
                
        except Exception as e:
            log_error(f"Error updating topology traffic data: {e}")
    
    def clear_topology(self):
        """Clear the topology view"""
        self.scene.clear()
        self.nodes.clear()
        self.connections.clear()
    
    def change_layout(self, layout_name: str):
        """Change the layout mode"""
        self.layout_mode = layout_name.lower().replace(" ", "_")
        if self.auto_layout:
            self.apply_layout()
    
    def toggle_auto_layout(self, enabled: bool):
        """Toggle auto layout"""
        self.auto_layout = enabled
        if enabled:
            self.apply_layout()
    
    def toggle_traffic_display(self, enabled: bool):
        """Toggle traffic display"""
        self.show_traffic = enabled
        for node in self.nodes.values():
            node.update_appearance()
    
    def toggle_connections_display(self, enabled: bool):
        """Toggle connections display"""
        self.show_connections = enabled
        for connection in self.connections:
            connection.setVisible(enabled)
    
    def toggle_animations(self, enabled: bool):
        """Toggle animations"""
        self.animation_enabled = enabled
        if enabled:
            self.animation_timer.start(100)
        else:
            self.animation_timer.stop()
    
    def refresh_topology(self):
        """Refresh the topology display"""
        try:
            # Trigger a repaint
            self.view.viewport().update()
            log_info("Topology refreshed")
            
        except Exception as e:
            log_error(f"Error refreshing topology: {e}")
    
    def export_topology(self):
        """Export topology to image"""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Topology", 
                f"topology_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
            )
            
            if filename:
                # Create a pixmap of the scene
                rect = self.scene.sceneRect()
                pixmap = QPixmap(int(rect.width()), int(rect.height()))
                pixmap.fill(QColor(255, 255, 255))
                
                painter = QPainter(pixmap)
                self.scene.render(painter)
                painter.end()
                
                pixmap.save(filename)
                log_info(f"Topology exported to {filename}")
                QMessageBox.information(self, "Success", f"Topology exported to {filename}")
        
        except Exception as e:
            log_error(f"Error exporting topology: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export topology: {e}")
    
    def fit_view(self):
        """Fit the view to show all devices"""
        try:
            if self.nodes:
                # Calculate bounding rectangle
                rect = self.scene.itemsBoundingRect()
                self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                self.view.centerOn(0, 0)
            
        except Exception as e:
            log_error(f"Error fitting topology view: {e}")
    
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        self.fit_view()
    
    def get_selected_devices(self) -> List[str]:
        """Get list of selected device IPs"""
        try:
            selected = []
            for node in self.nodes.values():
                if node.is_selected:
                    selected.append(node.device.ip)
            return selected
            
        except Exception as e:
            log_error(f"Error getting selected devices: {e}")
            return []
    
    def select_device(self, ip: str):
        """Select a device by IP"""
        try:
            if ip in self.nodes:
                # Deselect all other nodes
                for node in self.nodes.values():
                    node.is_selected = False
                    node.update_appearance()
                
                # Select the specified node
                node = self.nodes[ip]
                node.is_selected = True
                node.update_appearance()
                
                # Center view on selected node
                self.view.centerOn(node)
                
        except Exception as e:
            log_error(f"Error selecting device {ip}: {e}") 