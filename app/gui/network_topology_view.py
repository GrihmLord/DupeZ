# app/gui/network_topology_view.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView,
                              QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
                              QGraphicsTextItem, QGraphicsLineItem, QGraphicsRectItem,
                              QPushButton, QLabel, QComboBox, QSlider, QCheckBox,
                              QGroupBox, QFormLayout, QSpinBox, QTabWidget,
                              QScrollArea, QFrame, QSizePolicy, QMenu, QAction,
                              QInputDialog, QMessageBox, QColorDialog, QFontDialog)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import (QPen, QBrush, QColor, QFont, QPainter, QPainterPath,
                         QLinearGradient, QRadialGradient, QPixmap, QIcon,
                         QDragEnterEvent, QDropEvent, QMouseEvent, QWheelEvent)
import math
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from app.logs.logger import log_info, log_error, log_warning
from app.core.advanced_traffic_analyzer import advanced_traffic_analyzer

@dataclass
class NetworkNode:
    """Represents a network device node"""
    device_id: str
    ip_address: str
    mac_address: str
    hostname: str
    device_type: str
    status: str  # online, offline, blocked, suspicious
    x: float = 0.0
    y: float = 0.0
    traffic_in: int = 0
    traffic_out: int = 0
    connections: List[str] = None
    last_seen: datetime = None
    
    def __post_init__(self):
        if self.connections is None:
            self.connections = []
        if self.last_seen is None:
            self.last_seen = datetime.now()

@dataclass
class NetworkConnection:
    """Represents a network connection between devices"""
    connection_id: str
    source_device: str
    dest_device: str
    protocol: str
    port: int
    bandwidth: int
    status: str  # active, idle, blocked, suspicious
    last_activity: datetime = None
    
    def __post_init__(self):
        if self.last_activity is None:
            self.last_activity = datetime.now()

class NetworkTopologyScene(QGraphicsScene):
    """Custom graphics scene for network topology visualization"""
    
    def __init__(self):
        super().__init__()
        self.nodes: Dict[str, NetworkNode] = {}
        self.connections: Dict[str, NetworkConnection] = {}
        self.node_items: Dict[str, QGraphicsItem] = {}
        self.connection_items: Dict[str, QGraphicsItem] = {}
        self.selected_node: Optional[str] = None
        self.dragging = False
        self.drag_start = QPointF()
        
        # Visual settings
        self.node_radius = 30
        self.connection_width = 3
        self.animation_speed = 1.0
        self.show_traffic_flows = True
        self.show_device_details = True
        
        # Color schemes
        self.colors = {
            'online': QColor(0, 255, 0),      # Green
            'offline': QColor(128, 128, 128),  # Gray
            'blocked': QColor(255, 0, 0),      # Red
            'suspicious': QColor(255, 165, 0), # Orange
            'connection_active': QColor(0, 255, 0),
            'connection_idle': QColor(128, 128, 128),
            'connection_blocked': QColor(255, 0, 0),
            'connection_suspicious': QColor(255, 165, 0)
        }
        
        self.setup_scene()
    
    def setup_scene(self):
        """Setup the scene with background and grid"""
        # Set scene size
        self.setSceneRect(-1000, -1000, 2000, 2000)
        
        # Add background grid
        self.add_grid()
    
    def add_grid(self):
        """Add a background grid to the scene"""
        grid_pen = QPen(QColor(50, 50, 50), 1, Qt.PenStyle.DotLine)
        
        for x in range(-1000, 1001, 50):
            self.addLine(x, -1000, x, 1000, grid_pen)
        
        for y in range(-1000, 1001, 50):
            self.addLine(-1000, y, 1000, y, grid_pen)
    
    def add_node(self, node: NetworkNode):
        """Add a network node to the scene"""
        try:
            # Create node visual item
            node_item = self.create_node_item(node)
            self.node_items[node.device_id] = node_item
            self.nodes[node.device_id] = node
            
            # Position node if not already positioned
            if node.x == 0 and node.y == 0:
                self.auto_position_node(node)
            
            node_item.setPos(node.x, node.y)
            self.addItem(node_item)
            
            log_info(f"Added node: {node.hostname} ({node.ip_address})")
            
        except Exception as e:
            log_error(f"Error adding node: {e}")
    
    def create_node_item(self, node: NetworkNode) -> QGraphicsItem:
        """Create a visual item for a network node"""
        # Create group item to hold all node elements
        group = self.createItemGroup([])
        
        # Create main node circle
        circle = QGraphicsEllipseItem(-self.node_radius, -self.node_radius, 
                                    self.node_radius * 2, self.node_radius * 2)
        
        # Set color based on status
        status_color = self.colors.get(node.status, self.colors['offline'])
        circle.setBrush(QBrush(status_color))
        circle.setPen(QPen(QColor(255, 255, 255), 2))
        
        # Add to group
        group.addToGroup(circle)
        
        # Add device type icon
        icon_item = self.create_device_icon(node.device_type)
        if icon_item:
            group.addToGroup(icon_item)
        
        # Add hostname text
        text_item = QGraphicsTextItem(node.hostname)
        text_item.setDefaultTextColor(QColor(255, 255, 255))
        text_item.setFont(QFont("Arial", 8))
        text_item.setPos(-text_item.boundingRect().width() / 2, 
                        self.node_radius + 5)
        group.addToGroup(text_item)
        
        # Add IP address text
        ip_text = QGraphicsTextItem(node.ip_address)
        ip_text.setDefaultTextColor(QColor(200, 200, 200))
        ip_text.setFont(QFont("Arial", 6))
        ip_text.setPos(-ip_text.boundingRect().width() / 2, 
                      self.node_radius + 20)
        group.addToGroup(ip_text)
        
        # Add traffic indicator if enabled
        if self.show_traffic_flows and (node.traffic_in > 0 or node.traffic_out > 0):
            traffic_item = self.create_traffic_indicator(node)
            group.addToGroup(traffic_item)
        
        # Make node selectable and movable
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        
        # Store node data
        group.setData(0, node.device_id)
        
        return group
    
    def create_device_icon(self, device_type: str) -> Optional[QGraphicsItem]:
        """Create an icon for the device type"""
        try:
            # Simple text-based icons for now
            icon_text = {
                'router': '🌐',
                'switch': '🔌',
                'computer': '💻',
                'mobile': '📱',
                'gaming': '🎮',
                'ps5': '🎮',
                'unknown': '❓'
            }.get(device_type.lower(), '❓')
            
            icon_item = QGraphicsTextItem(icon_text)
            icon_item.setDefaultTextColor(QColor(255, 255, 255))
            icon_item.setFont(QFont("Arial", 12))
            icon_item.setPos(-icon_item.boundingRect().width() / 2, 
                           -icon_item.boundingRect().height() / 2)
            
            return icon_item
            
        except Exception as e:
            log_error(f"Error creating device icon: {e}")
            return None
    
    def create_traffic_indicator(self, node: NetworkNode) -> QGraphicsItem:
        """Create a traffic flow indicator"""
        try:
            # Create animated traffic flow
            total_traffic = node.traffic_in + node.traffic_out
            
            # Create gradient for traffic visualization
            gradient = QRadialGradient(0, 0, self.node_radius + 10)
            gradient.setColorAt(0, QColor(255, 255, 0, 100))
            gradient.setColorAt(1, QColor(255, 255, 0, 0))
            
            # Create traffic circle
            traffic_circle = QGraphicsEllipseItem(-self.node_radius - 10, 
                                                -self.node_radius - 10,
                                                (self.node_radius + 10) * 2,
                                                (self.node_radius + 10) * 2)
            traffic_circle.setBrush(QBrush(gradient))
            traffic_circle.setPen(QPen(QColor(255, 255, 0, 150), 2))
            
            return traffic_circle
            
        except Exception as e:
            log_error(f"Error creating traffic indicator: {e}")
            return None
    
    def auto_position_node(self, node: NetworkNode):
        """Automatically position a node in the topology"""
        try:
            # Simple circular layout
            existing_nodes = len(self.nodes)
            angle = (existing_nodes * 137.5) * (math.pi / 180)  # Golden angle
            radius = 200 + (existing_nodes * 50)
            
            node.x = math.cos(angle) * radius
            node.y = math.sin(angle) * radius
            
        except Exception as e:
            log_error(f"Error auto-positioning node: {e}")
    
    def add_connection(self, connection: NetworkConnection):
        """Add a network connection to the scene"""
        try:
            if connection.source_device not in self.nodes or connection.dest_device not in self.nodes:
                return
            
            # Create connection visual item
            connection_item = self.create_connection_item(connection)
            self.connection_items[connection.connection_id] = connection_item
            self.connections[connection.connection_id] = connection
            
            self.addItem(connection_item)
            
            log_info(f"Added connection: {connection.source_device} -> {connection.dest_device}")
            
        except Exception as e:
            log_error(f"Error adding connection: {e}")
    
    def create_connection_item(self, connection: NetworkConnection) -> QGraphicsItem:
        """Create a visual item for a network connection"""
        try:
            source_node = self.nodes[connection.source_device]
            dest_node = self.nodes[connection.dest_device]
            
            # Create line between nodes
            line = QGraphicsLineItem(source_node.x, source_node.y, 
                                   dest_node.x, dest_node.y)
            
            # Set line style based on connection status
            status_color = self.colors.get(f"connection_{connection.status}", 
                                         self.colors['connection_idle'])
            line.setPen(QPen(status_color, self.connection_width))
            
            # Add arrow head for direction
            arrow = self.create_arrow_head(source_node.x, source_node.y,
                                         dest_node.x, dest_node.y)
            
            # Create group for line and arrow
            group = self.createItemGroup([line, arrow])
            
            # Add connection label
            label_text = f"{connection.protocol}:{connection.port}"
            label = QGraphicsTextItem(label_text)
            label.setDefaultTextColor(QColor(255, 255, 255))
            label.setFont(QFont("Arial", 6))
            
            # Position label at midpoint
            mid_x = (source_node.x + dest_node.x) / 2
            mid_y = (source_node.y + dest_node.y) / 2
            label.setPos(mid_x - label.boundingRect().width() / 2,
                        mid_y - label.boundingRect().height() / 2)
            
            group.addToGroup(label)
            
            # Store connection data
            group.setData(0, connection.connection_id)
            
            return group
            
        except Exception as e:
            log_error(f"Error creating connection item: {e}")
            return QGraphicsLineItem()
    
    def create_arrow_head(self, x1: float, y1: float, x2: float, y2: float) -> QGraphicsItem:
        """Create an arrow head for connection direction"""
        try:
            # Calculate arrow direction
            dx = x2 - x1
            dy = y2 - y1
            length = math.sqrt(dx * dx + dy * dy)
            
            if length == 0:
                return QGraphicsLineItem()
            
            # Normalize direction
            dx /= length
            dy /= length
            
            # Arrow head size
            arrow_size = 10
            
            # Calculate arrow head points
            arrow_x = x2 - dx * arrow_size
            arrow_y = y2 - dy * arrow_size
            
            # Create arrow head path
            arrow_path = QPainterPath()
            arrow_path.moveTo(x2, y2)
            arrow_path.lineTo(arrow_x - dy * arrow_size/2, arrow_y + dx * arrow_size/2)
            arrow_path.lineTo(arrow_x + dy * arrow_size/2, arrow_y - dx * arrow_size/2)
            arrow_path.closeSubpath()
            
            arrow_item = QGraphicsPathItem(arrow_path)
            arrow_item.setBrush(QBrush(QColor(255, 255, 255)))
            arrow_item.setPen(QPen(QColor(255, 255, 255), 1))
            
            return arrow_item
            
        except Exception as e:
            log_error(f"Error creating arrow head: {e}")
            return QGraphicsLineItem()
    
    def update_node_traffic(self, device_id: str, traffic_in: int, traffic_out: int):
        """Update traffic data for a node"""
        try:
            if device_id in self.nodes:
                node = self.nodes[device_id]
                node.traffic_in = traffic_in
                node.traffic_out = traffic_out
                node.last_seen = datetime.now()
                
                # Update visual representation
                if device_id in self.node_items:
                    self.update_node_visual(device_id)
                    
        except Exception as e:
            log_error(f"Error updating node traffic: {e}")
    
    def update_node_visual(self, device_id: str):
        """Update the visual representation of a node"""
        try:
            if device_id not in self.node_items:
                return
            
            node = self.nodes[device_id]
            node_item = self.node_items[device_id]
            
            # Remove old item
            self.removeItem(node_item)
            
            # Create new item with updated data
            new_item = self.create_node_item(node)
            new_item.setPos(node.x, node.y)
            
            # Replace in collections
            self.node_items[device_id] = new_item
            self.addItem(new_item)
            
        except Exception as e:
            log_error(f"Error updating node visual: {e}")
    
    def remove_node(self, device_id: str):
        """Remove a node from the scene"""
        try:
            if device_id in self.node_items:
                self.removeItem(self.node_items[device_id])
                del self.node_items[device_id]
            
            if device_id in self.nodes:
                del self.nodes[device_id]
            
            # Remove related connections
            connections_to_remove = []
            for conn_id, connection in self.connections.items():
                if (connection.source_device == device_id or 
                    connection.dest_device == device_id):
                    connections_to_remove.append(conn_id)
            
            for conn_id in connections_to_remove:
                self.remove_connection(conn_id)
                
        except Exception as e:
            log_error(f"Error removing node: {e}")
    
    def remove_connection(self, connection_id: str):
        """Remove a connection from the scene"""
        try:
            if connection_id in self.connection_items:
                self.removeItem(self.connection_items[connection_id])
                del self.connection_items[connection_id]
            
            if connection_id in self.connections:
                del self.connections[connection_id]
                
        except Exception as e:
            log_error(f"Error removing connection: {e}")
    
    def clear_scene(self):
        """Clear all items from the scene"""
        try:
            self.clear()
            self.nodes.clear()
            self.connections.clear()
            self.node_items.clear()
            self.connection_items.clear()
            self.add_grid()
            
        except Exception as e:
            log_error(f"Error clearing scene: {e}")
    
    def get_node_at_position(self, pos: QPointF) -> Optional[str]:
        """Get the node at a specific position"""
        try:
            for device_id, node in self.nodes.items():
                distance = math.sqrt((pos.x() - node.x) ** 2 + (pos.y() - node.y) ** 2)
                if distance <= self.node_radius:
                    return device_id
            return None
            
        except Exception as e:
            log_error(f"Error getting node at position: {e}")
            return None

class NetworkTopologyView(QGraphicsView):
    """Custom graphics view for network topology visualization"""
    
    # Signals
    node_selected = pyqtSignal(str)  # device_id
    node_double_clicked = pyqtSignal(str)  # device_id
    connection_selected = pyqtSignal(str)  # connection_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = NetworkTopologyScene()
        self.setScene(self.scene)
        
        # View settings
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        
        # Zoom settings
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        
        # Interaction settings
        self.panning = False
        self.last_pan_point = QPointF()
        
        self.setup_view()
    
    def setup_view(self):
        """Setup the view with proper scaling and centering"""
        # Set initial transform
        self.resetTransform()
        self.scale(1.0, 1.0)
        
        # Center the view
        self.centerOn(0, 0)
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel events for zooming"""
        try:
            # Get zoom factor
            zoom_in_factor = 1.25
            zoom_out_factor = 1 / zoom_in_factor
            
            # Determine zoom direction
            if event.angleDelta().y() > 0:
                factor = zoom_in_factor
            else:
                factor = zoom_out_factor
            
            # Apply zoom
            new_zoom = self.zoom_factor * factor
            if self.min_zoom <= new_zoom <= self.max_zoom:
                self.zoom_factor = new_zoom
                self.scale(factor, factor)
                
        except Exception as e:
            log_error(f"Error in wheel event: {e}")
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events"""
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                # Check for node selection
                pos = self.mapToScene(event.pos())
                node_id = self.scene.get_node_at_position(pos)
                
                if node_id:
                    self.scene.selected_node = node_id
                    self.node_selected.emit(node_id)
                else:
                    self.scene.selected_node = None
                    
                # Start panning if middle button
                if event.button() == Qt.MouseButton.MiddleButton:
                    self.panning = True
                    self.last_pan_point = event.pos()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            
            super().mousePressEvent(event)
            
        except Exception as e:
            log_error(f"Error in mouse press event: {e}")
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events"""
        try:
            if self.panning:
                # Calculate pan delta
                delta = event.pos() - self.last_pan_point
                self.last_pan_point = event.pos()
                
                # Move the view
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x())
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y())
            
            super().mouseMoveEvent(event)
            
        except Exception as e:
            log_error(f"Error in mouse move event: {e}")
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release events"""
        try:
            if event.button() == Qt.MouseButton.MiddleButton:
                self.panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
            
            super().mouseReleaseEvent(event)
            
        except Exception as e:
            log_error(f"Error in mouse release event: {e}")
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle mouse double click events"""
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = self.mapToScene(event.pos())
                node_id = self.scene.get_node_at_position(pos)
                
                if node_id:
                    self.node_double_clicked.emit(node_id)
            
            super().mouseDoubleClickEvent(event)
            
        except Exception as e:
            log_error(f"Error in mouse double click event: {e}")
    
    def fit_to_view(self):
        """Fit all items to the view"""
        try:
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            
        except Exception as e:
            log_error(f"Error fitting to view: {e}")
    
    def reset_view(self):
        """Reset the view to default position and zoom"""
        try:
            self.resetTransform()
            self.zoom_factor = 1.0
            self.centerOn(0, 0)
            
        except Exception as e:
            log_error(f"Error resetting view: {e}")

class NetworkTopologyWidget(QWidget):
    """Main widget for network topology visualization"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.topology_view = NetworkTopologyView()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_topology)
        
        self.setup_ui()
        self.setup_connections()
        self.start_updates()
    
    def setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout()
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Topology view
        layout.addWidget(self.topology_view)
        
        self.setLayout(layout)
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel"""
        panel = QWidget()
        layout = QHBoxLayout()
        
        # View controls
        view_group = QGroupBox("View Controls")
        view_layout = QVBoxLayout()
        
        # Zoom controls
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Zoom:"))
        
        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(zoom_out_btn)
        
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_layout.addWidget(zoom_in_btn)
        
        fit_view_btn = QPushButton("Fit View")
        fit_view_btn.clicked.connect(self.topology_view.fit_to_view)
        zoom_layout.addWidget(fit_view_btn)
        
        reset_view_btn = QPushButton("Reset")
        reset_view_btn.clicked.connect(self.topology_view.reset_view)
        zoom_layout.addWidget(reset_view_btn)
        
        view_layout.addLayout(zoom_layout)
        
        # Display options
        display_layout = QHBoxLayout()
        
        self.show_traffic_checkbox = QCheckBox("Show Traffic")
        self.show_traffic_checkbox.setChecked(True)
        self.show_traffic_checkbox.toggled.connect(self.toggle_traffic_display)
        display_layout.addWidget(self.show_traffic_checkbox)
        
        self.show_details_checkbox = QCheckBox("Show Details")
        self.show_details_checkbox.setChecked(True)
        self.show_details_checkbox.toggled.connect(self.toggle_details_display)
        display_layout.addWidget(self.show_details_checkbox)
        
        view_layout.addLayout(display_layout)
        
        view_group.setLayout(view_layout)
        layout.addWidget(view_group)
        
        # Layout controls
        layout_group = QGroupBox("Layout")
        layout_layout = QVBoxLayout()
        
        auto_layout_btn = QPushButton("Auto Layout")
        auto_layout_btn.clicked.connect(self.auto_layout)
        layout_layout.addWidget(auto_layout_btn)
        
        circular_layout_btn = QPushButton("Circular Layout")
        circular_layout_btn.clicked.connect(self.circular_layout)
        layout_layout.addWidget(circular_layout_btn)
        
        layout_group.setLayout(layout_layout)
        layout.addWidget(layout_group)
        
        # Update controls
        update_group = QGroupBox("Updates")
        update_layout = QVBoxLayout()
        
        self.auto_update_checkbox = QCheckBox("Auto Update")
        self.auto_update_checkbox.setChecked(True)
        self.auto_update_checkbox.toggled.connect(self.toggle_auto_update)
        update_layout.addWidget(self.auto_update_checkbox)
        
        update_interval_layout = QHBoxLayout()
        update_interval_layout.addWidget(QLabel("Interval:"))
        
        self.update_interval_spinbox = QSpinBox()
        self.update_interval_spinbox.setRange(1, 60)
        self.update_interval_spinbox.setValue(5)
        self.update_interval_spinbox.setSuffix(" sec")
        self.update_interval_spinbox.valueChanged.connect(self.update_interval_changed)
        update_interval_layout.addWidget(self.update_interval_spinbox)
        
        update_layout.addLayout(update_interval_layout)
        
        update_group.setLayout(update_layout)
        layout.addWidget(update_group)
        
        layout.addStretch()
        panel.setLayout(layout)
        return panel
    
    def setup_connections(self):
        """Setup signal connections"""
        self.topology_view.node_selected.connect(self.on_node_selected)
        self.topology_view.node_double_clicked.connect(self.on_node_double_clicked)
    
    def start_updates(self):
        """Start automatic updates"""
        interval = self.update_interval_spinbox.value() * 1000
        self.update_timer.start(interval)
    
    def stop_updates(self):
        """Stop automatic updates"""
        self.update_timer.stop()
    
    def toggle_auto_update(self, enabled: bool):
        """Toggle automatic updates"""
        if enabled:
            self.start_updates()
        else:
            self.stop_updates()
    
    def update_interval_changed(self, value: int):
        """Handle update interval change"""
        if self.auto_update_checkbox.isChecked():
            self.update_timer.setInterval(value * 1000)
    
    def toggle_traffic_display(self, enabled: bool):
        """Toggle traffic flow display"""
        self.topology_view.scene.show_traffic_flows = enabled
        self.update_topology()
    
    def toggle_details_display(self, enabled: bool):
        """Toggle device details display"""
        self.topology_view.scene.show_device_details = enabled
        self.update_topology()
    
    def zoom_in(self):
        """Zoom in"""
        self.topology_view.scale(1.25, 1.25)
        self.topology_view.zoom_factor *= 1.25
    
    def zoom_out(self):
        """Zoom out"""
        self.topology_view.scale(0.8, 0.8)
        self.topology_view.zoom_factor *= 0.8
    
    def auto_layout(self):
        """Apply automatic layout to nodes"""
        try:
            # Simple force-directed layout
            nodes = list(self.topology_view.scene.nodes.values())
            
            for i, node in enumerate(nodes):
                angle = (i * 137.5) * (math.pi / 180)
                radius = 200 + (i * 50)
                node.x = math.cos(angle) * radius
                node.y = math.sin(angle) * radius
                
                if node.device_id in self.topology_view.scene.node_items:
                    item = self.topology_view.scene.node_items[node.device_id]
                    item.setPos(node.x, node.y)
            
            log_info("Applied auto layout to topology")
            
        except Exception as e:
            log_error(f"Error applying auto layout: {e}")
    
    def circular_layout(self):
        """Apply circular layout to nodes"""
        try:
            nodes = list(self.topology_view.scene.nodes.values())
            center_x, center_y = 0, 0
            radius = 300
            
            for i, node in enumerate(nodes):
                angle = (i * 2 * math.pi) / len(nodes)
                node.x = center_x + math.cos(angle) * radius
                node.y = center_y + math.sin(angle) * radius
                
                if node.device_id in self.topology_view.scene.node_items:
                    item = self.topology_view.scene.node_items[node.device_id]
                    item.setPos(node.x, node.y)
            
            log_info("Applied circular layout to topology")
            
        except Exception as e:
            log_error(f"Error applying circular layout: {e}")
    
    def update_topology(self):
        """Update the topology with current network data"""
        try:
            # Get current network devices from traffic analyzer
            summary = advanced_traffic_analyzer.get_analysis_summary()
            
            # Update existing nodes with traffic data
            for device_id, node in self.topology_view.scene.nodes.items():
                # Simulate traffic data (in real implementation, get from actual network)
                traffic_in = random.randint(0, 1000)
                traffic_out = random.randint(0, 1000)
                
                self.topology_view.scene.update_node_traffic(device_id, traffic_in, traffic_out)
            
            # Add new nodes if needed (simulate device discovery)
            if random.random() < 0.1:  # 10% chance to add new device
                self.add_sample_device()
            
        except Exception as e:
            log_error(f"Error updating topology: {e}")
    
    def add_sample_device(self):
        """Add a sample device to the topology"""
        try:
            device_types = ['computer', 'mobile', 'gaming', 'ps5', 'router', 'switch']
            device_type = random.choice(device_types)
            
            node = NetworkNode(
                device_id=f"device_{len(self.topology_view.scene.nodes)}",
                ip_address=f"192.168.1.{random.randint(100, 254)}",
                mac_address=f"00:1B:44:11:3A:B{random.randint(0, 9)}",
                hostname=f"Device-{random.randint(1, 999)}",
                device_type=device_type,
                status=random.choice(['online', 'offline', 'blocked', 'suspicious'])
            )
            
            self.topology_view.scene.add_node(node)
            
        except Exception as e:
            log_error(f"Error adding sample device: {e}")
    
    def on_node_selected(self, device_id: str):
        """Handle node selection"""
        try:
            if device_id in self.topology_view.scene.nodes:
                node = self.topology_view.scene.nodes[device_id]
                log_info(f"Selected node: {node.hostname} ({node.ip_address})")
                
        except Exception as e:
            log_error(f"Error handling node selection: {e}")
    
    def on_node_double_clicked(self, device_id: str):
        """Handle node double click"""
        try:
            if device_id in self.topology_view.scene.nodes:
                node = self.topology_view.scene.nodes[device_id]
                
                # Show device details dialog
                self.show_device_details(node)
                
        except Exception as e:
            log_error(f"Error handling node double click: {e}")
    
    def show_device_details(self, node: NetworkNode):
        """Show detailed information about a device"""
        try:
            details = f"""
Device Details:
Hostname: {node.hostname}
IP Address: {node.ip_address}
MAC Address: {node.mac_address}
Device Type: {node.device_type}
Status: {node.status}
Traffic In: {node.traffic_in} bytes
Traffic Out: {node.traffic_out} bytes
Last Seen: {node.last_seen}
Connections: {len(node.connections)}
            """
            
            QMessageBox.information(self, f"Device Details - {node.hostname}", details)
            
        except Exception as e:
            log_error(f"Error showing device details: {e}")
    
    def load_network_data(self, devices: List[Dict], connections: List[Dict]):
        """Load network data into the topology view"""
        try:
            # Clear existing topology
            self.topology_view.scene.clear_scene()
            
            # Add devices
            for device_data in devices:
                node = NetworkNode(
                    device_id=device_data.get('id', ''),
                    ip_address=device_data.get('ip', ''),
                    mac_address=device_data.get('mac', ''),
                    hostname=device_data.get('hostname', ''),
                    device_type=device_data.get('type', 'unknown'),
                    status=device_data.get('status', 'offline')
                )
                self.topology_view.scene.add_node(node)
            
            # Add connections
            for conn_data in connections:
                connection = NetworkConnection(
                    connection_id=conn_data.get('id', ''),
                    source_device=conn_data.get('source', ''),
                    dest_device=conn_data.get('dest', ''),
                    protocol=conn_data.get('protocol', 'TCP'),
                    port=conn_data.get('port', 80),
                    bandwidth=conn_data.get('bandwidth', 0),
                    status=conn_data.get('status', 'active')
                )
                self.topology_view.scene.add_connection(connection)
            
            log_info(f"Loaded {len(devices)} devices and {len(connections)} connections")
            
        except Exception as e:
            log_error(f"Error loading network data: {e}")
    
    def export_topology(self, filename: str):
        """Export topology to image file"""
        try:
            # Create a pixmap of the scene
            rect = self.topology_view.scene.sceneRect()
            pixmap = QPixmap(rect.width(), rect.height())
            pixmap.fill(QColor(255, 255, 255))
            
            painter = QPainter(pixmap)
            self.topology_view.scene.render(painter)
            painter.end()
            
            # Save the pixmap
            pixmap.save(filename)
            log_info(f"Topology exported to {filename}")
            
        except Exception as e:
            log_error(f"Error exporting topology: {e}")

# Global instance for easy access
network_topology_widget = NetworkTopologyWidget() 