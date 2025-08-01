# app/gui/topology_view.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, 
                              QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
                              QGraphicsTextItem, QGraphicsLineItem, QGraphicsRectItem,
                              QPushButton, QLabel, QComboBox, QSlider, QGroupBox,
                              QFormLayout, QSpinBox, QCheckBox, QMenu, QAction,
                              QToolTip, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPen, QBrush, QColor, QFont, QPainter, QPainterPath, QRadialGradient
from typing import Dict, List, Optional, Tuple, Any
import math
import json
from datetime import datetime
from app.logs.logger import log_info, log_error
from app.core.state import Device

class NetworkNode(QGraphicsEllipseItem):
    """Network device node in the topology view"""
    
    def __init__(self, device: Device, x: float, y: float, radius: float = 30):
        super().__init__(x - radius, y - radius, radius * 2, radius * 2)
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
        if device.hostname and device.hostname != "Unknown":
            self.hostname_item = QGraphicsTextItem(self)
            self.hostname_item.setPlainText(device.hostname)
            self.hostname_item.setDefaultTextColor(QColor(200, 200, 200))
            self.hostname_item.setFont(QFont("Consolas", 6))
            self.hostname_item.setPos(-radius + 5, -radius + 15)
    
    def update_appearance(self):
        """Update node appearance based on device state"""
        # Determine base color based on device type
        if self.device.is_gaming_device:
            base_color = QColor(255, 165, 0)  # Orange for gaming
        elif self.device.is_router:
            base_color = QColor(0, 255, 255)  # Cyan for router
        elif self.device.is_mobile:
            base_color = QColor(255, 192, 203)  # Pink for mobile
        else:
            base_color = QColor(100, 150, 255)  # Blue for regular devices
        
        # Adjust color based on risk score
        if self.risk_score > 70:
            base_color = QColor(255, 0, 0)  # Red for high risk
        elif self.risk_score > 40:
            base_color = QColor(255, 255, 0)  # Yellow for medium risk
        
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
        tooltip_text = f"""
Device: {self.device.ip}
Hostname: {self.device.hostname or 'Unknown'}
MAC: {self.device.mac or 'Unknown'}
Vendor: {self.device.vendor or 'Unknown'}
Traffic: {self.traffic_flow:.1f} KB/s
Risk Score: {self.risk_score:.1f}
Status: {'Blocked' if self.device.is_blocked else 'Active'}
        """.strip()
        
        QToolTip.showText(event.screenPos(), tooltip_text)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Handle hover leave event"""
        self.is_hovered = False
        self.update_appearance()
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """Handle mouse press event"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_selected = True
            self.update_appearance()
        super().mousePressEvent(event)
    
    def contextMenuEvent(self, event):
        """Handle right-click context menu"""
        menu = QMenu()
        
        # Device actions
        block_action = QAction("🚫 Block Device", menu)
        block_action.triggered.connect(lambda: self._block_device())
        menu.addAction(block_action)
        
        unblock_action = QAction("✅ Unblock Device", menu)
        unblock_action.triggered.connect(lambda: self._unblock_device())
        menu.addAction(unblock_action)
        
        menu.addSeparator()
        
        # Traffic analysis
        analyze_action = QAction("📊 Analyze Traffic", menu)
        analyze_action.triggered.connect(lambda: self._analyze_traffic())
        menu.addAction(analyze_action)
        
        # Device details
        details_action = QAction("ℹ️ Device Details", menu)
        details_action.triggered.connect(lambda: self._show_details())
        menu.addAction(details_action)
        
        menu.exec(event.screenPos())
    
    def _block_device(self):
        """Block the device"""
        # This will be connected to the controller
        pass
    
    def _unblock_device(self):
        """Unblock the device"""
        # This will be connected to the controller
        pass
    
    def _analyze_traffic(self):
        """Show traffic analysis for the device"""
        # This will be connected to the traffic analyzer
        pass
    
    def _show_details(self):
        """Show detailed device information"""
        details = f"""
Device Details:
IP Address: {self.device.ip}
Hostname: {self.device.hostname or 'Unknown'}
MAC Address: {self.device.mac or 'Unknown'}
Vendor: {self.device.vendor or 'Unknown'}
Device Type: {self._get_device_type()}
Traffic Flow: {self.traffic_flow:.1f} KB/s
Risk Score: {self.risk_score:.1f}
Status: {'Blocked' if self.device.is_blocked else 'Active'}
Last Seen: {self.device.last_seen}
        """.strip()
        
        QMessageBox.information(None, f"Device Details - {self.device.ip}", details)
    
    def _get_device_type(self) -> str:
        """Get human-readable device type"""
        if self.device.is_gaming_device:
            return "Gaming Console"
        elif self.device.is_router:
            return "Router/Gateway"
        elif self.device.is_mobile:
            return "Mobile Device"
        else:
            return "Computer/Device"

class NetworkConnection(QGraphicsLineItem):
    """Connection line between network devices"""
    
    def __init__(self, source_node: NetworkNode, target_node: NetworkNode):
        super().__init__()
        self.source_node = source_node
        self.target_node = target_node
        self.traffic_flow = 0.0
        self.connection_type = "normal"  # normal, blocked, suspicious
        
        # Add connection to nodes
        source_node.connections.append(self)
        target_node.connections.append(self)
        
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices: Dict[str, NetworkNode] = {}
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
        self.animation_timer.start(100)  # 10 FPS
    
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
    
    def update_topology(self, devices: List[Device], traffic_data: Dict[str, float] = None):
        """Update the network topology with new device data"""
        try:
            # Clear existing topology
            self.clear_topology()
            
            # Add devices
            for device in devices:
                self.add_device(device)
            
            # Create connections (simplified - connect to router)
            self.create_connections()
            
            # Apply layout
            if self.auto_layout:
                self.apply_layout()
            
            # Update traffic data
            if traffic_data:
                self.update_traffic_data(traffic_data)
            
            # Fit view to show all devices
            self.fit_view()
            
            log_info(f"Topology updated with {len(devices)} devices")
            
        except Exception as e:
            log_error(f"Error updating topology: {e}")
    
    def add_device(self, device: Device):
        """Add a device to the topology"""
        if device.ip in self.devices:
            return
        
        # Create node at random position (will be adjusted by layout)
        x = (hash(device.ip) % 200) - 100
        y = (hash(device.ip) % 200) - 100
        
        node = NetworkNode(device, x, y)
        self.devices[device.ip] = node
        self.scene.addItem(node)
    
    def create_connections(self):
        """Create connections between devices"""
        # Simple star topology - connect all devices to the first one (assumed router)
        if not self.devices:
            return
        
        # Find router (usually the first device or one with specific IP)
        router_ip = None
        for ip, node in self.devices.items():
            if node.device.is_router or ip.endswith('.1'):
                router_ip = ip
                break
        
        if not router_ip:
            router_ip = list(self.devices.keys())[0]
        
        # Create connections to router
        for ip, node in self.devices.items():
            if ip != router_ip:
                connection = NetworkConnection(self.devices[router_ip], node)
                self.connections.append(connection)
                self.scene.addItem(connection)
    
    def apply_layout(self):
        """Apply the selected layout algorithm"""
        if self.layout_mode == "circular":
            self.apply_circular_layout()
        elif self.layout_mode == "grid":
            self.apply_grid_layout()
        elif self.layout_mode == "force_directed":
            self.apply_force_directed_layout()
    
    def apply_circular_layout(self):
        """Apply circular layout"""
        if not self.devices:
            return
        
        center_x, center_y = 0, 0
        radius = 200
        angle_step = 2 * math.pi / len(self.devices)
        
        for i, (ip, node) in enumerate(self.devices.items()):
            angle = i * angle_step
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            
            if self.animation_enabled:
                self.animate_node_movement(node, x, y)
            else:
                node.setPos(x, y)
            
            # Update connections
            for connection in node.connections:
                connection.update_position()
    
    def apply_grid_layout(self):
        """Apply grid layout"""
        if not self.devices:
            return
        
        cols = int(math.ceil(math.sqrt(len(self.devices))))
        spacing = 150
        
        for i, (ip, node) in enumerate(self.devices.items()):
            row = i // cols
            col = i % cols
            
            x = (col - cols // 2) * spacing
            y = (row - len(self.devices) // cols // 2) * spacing
            
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
        animation = QPropertyAnimation(node, b"pos")
        animation.setDuration(500)
        animation.setStartValue(node.pos())
        animation.setEndValue(QPointF(target_x, target_y))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
    
    def update_traffic_data(self, traffic_data: Dict[str, float]):
        """Update traffic data for devices and connections"""
        for ip, flow in traffic_data.items():
            if ip in self.devices:
                node = self.devices[ip]
                node.traffic_flow = flow
                node.update_appearance()
                
                # Update connections
                for connection in node.connections:
                    connection.set_traffic_flow(flow)
    
    def clear_topology(self):
        """Clear the topology view"""
        self.scene.clear()
        self.devices.clear()
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
        for node in self.devices.values():
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
        """Refresh the topology view"""
        self.apply_layout()
        self.fit_view()
    
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
        if self.devices:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        self.fit_view()
    
    def get_selected_devices(self) -> List[str]:
        """Get list of selected device IPs"""
        return [ip for ip, node in self.devices.items() if node.is_selected]
    
    def select_device(self, ip: str):
        """Select a specific device"""
        if ip in self.devices:
            # Clear other selections
            for node in self.devices.values():
                node.is_selected = False
                node.update_appearance()
            
            # Select the specified device
            self.devices[ip].is_selected = True
            self.devices[ip].update_appearance()
            
            # Center view on selected device
            self.view.centerOn(self.devices[ip]) 