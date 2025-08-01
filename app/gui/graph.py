# app/gui/graph.py

import random
import time
from typing import List, Dict, Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPixmap
from app.logs.logger import log_info, log_error

class PacketGraph(QWidget):
    """Real-time packet graph widget with traffic visualization"""
    
    # Signals
    graph_clicked = pyqtSignal(str)  # Emit device IP when graph is clicked
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.data_points = []  # List of (timestamp, bytes_sent, bytes_received)
        self.max_points = 100
        self.update_interval = 1000  # 1 second
        self.device_data = {}  # Device-specific data
        self.selected_device = None
        
        self.init_ui()
        self.start_updates()
    
    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        
        # Header
        header_layout = QHBoxLayout()
        self.title_label = QLabel("📊 Network Traffic Monitor")
        self.title_label.setObjectName("title")
        header_layout.addWidget(self.title_label)
        
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        
        layout.addLayout(header_layout)
        
        # Graph area
        self.graph_widget = GraphWidget(self)
        layout.addWidget(self.graph_widget)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend:"))
        
        # Sent traffic indicator
        sent_indicator = QFrame()
        sent_indicator.setFixedSize(16, 16)
        sent_indicator.setStyleSheet("background-color: #2d5aa0; border-radius: 2px;")
        legend_layout.addWidget(sent_indicator)
        legend_layout.addWidget(QLabel("Sent"))
        
        # Received traffic indicator
        received_indicator = QFrame()
        received_indicator.setFixedSize(16, 16)
        received_indicator.setStyleSheet("background-color: #2da02d; border-radius: 2px;")
        legend_layout.addWidget(received_indicator)
        legend_layout.addWidget(QLabel("Received"))
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        self.setLayout(layout)
        self.setMinimumHeight(200)
    
    def start_updates(self):
        """Start the update timer with optimized frequency"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_graph)
        self.update_timer.start(3000)  # Update every 3 seconds (optimized from default)
    
    def stop_updates(self):
        """Stop the update timer"""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
    
    def update_graph(self):
        """Update the graph with new data (optimized)"""
        try:
            current_time = time.time()
            
            # Generate sample data (replace with real data from controller)
            if self.controller:
                devices = self.controller.get_devices()
                if devices:
                    # Use first device for demo
                    device = devices[0]
                    bytes_sent = random.randint(100, 1000)
                    bytes_received = random.randint(50, 500)
                    
                    self.add_data_point(current_time, bytes_sent, bytes_received)
                    
                    # Update status with better formatting
                    total_traffic = bytes_sent + bytes_received
                    self.status_label.setText(f"📊 Total Traffic: {self.format_bytes(total_traffic)}")
                else:
                    self.status_label.setText("📊 No devices found")
            else:
                # Demo data when no controller
                bytes_sent = random.randint(100, 1000)
                bytes_received = random.randint(50, 500)
                self.add_data_point(current_time, bytes_sent, bytes_received)
                self.status_label.setText(f"📊 Demo: {self.format_bytes(bytes_sent + bytes_received)}")
            
            # Update the graph widget (only if visible)
            if self.isVisible():
                self.graph_widget.update()
            
        except Exception as e:
            log_error(f"Graph update error: {e}")
    
    def add_data_point(self, timestamp: float, bytes_sent: int, bytes_received: int):
        """Add a new data point to the graph"""
        self.data_points.append((timestamp, bytes_sent, bytes_received))
        
        # Keep only the last max_points
        if len(self.data_points) > self.max_points:
            self.data_points.pop(0)
    
    def set_device_data(self, device_ip: str, data: Dict):
        """Set data for a specific device"""
        self.device_data[device_ip] = data
        self.selected_device = device_ip
    
    def format_bytes(self, bytes_value: int) -> str:
        """Format bytes into human readable string"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} TB"
    
    def get_graph_data(self) -> List[tuple]:
        """Get current graph data"""
        return self.data_points.copy()
    
    def clear_data(self):
        """Clear all graph data"""
        self.data_points.clear()
        self.device_data.clear()
        self.selected_device = None
        self.graph_widget.update()
    
    def set_update_interval(self, interval_ms: int):
        """Set the update interval in milliseconds"""
        self.update_interval = interval_ms
        if hasattr(self, 'update_timer'):
            self.update_timer.setInterval(interval_ms)
    
    def set_controller(self, controller):
        """Set the controller for this graph"""
        self.controller = controller


class GraphWidget(QWidget):
    """Custom widget for drawing the graph"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
    
    def paintEvent(self, event):
        """Custom paint event for drawing the graph"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        if width <= 0 or height <= 0:
            return
        
        # Clear background
        painter.fillRect(self.rect(), QColor(45, 45, 45))
        
        # Get data
        data_points = self.parent.get_graph_data() if self.parent else []
        
        if not data_points:
            # Draw placeholder text
            painter.setPen(QColor(128, 128, 128))
            painter.setFont(QFont("Arial", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data available")
            return
        
        # Calculate scales
        max_value = max(max(sent, received) for _, sent, received in data_points) if data_points else 1
        if max_value == 0:
            max_value = 1
        
        # Draw grid
        self.draw_grid(painter, width, height, max_value)
        
        # Draw data lines
        self.draw_data_lines(painter, width, height, data_points, max_value)
        
        # Draw axes labels
        self.draw_axes_labels(painter, width, height, max_value)
    
    def draw_grid(self, painter: QPainter, width: int, height: int, max_value: int):
        """Draw the grid lines"""
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        
        # Vertical grid lines (time)
        for i in range(0, width, 50):
            painter.drawLine(i, 0, i, height)
        
        # Horizontal grid lines (value)
        for i in range(0, height, 30):
            painter.drawLine(0, i, width, i)
    
    def draw_data_lines(self, painter: QPainter, width: int, height: int, 
                       data_points: List[tuple], max_value: int):
        """Draw the data lines"""
        if len(data_points) < 2:
            return
        
        # Draw sent data line (blue)
        sent_pen = QPen(QColor(45, 90, 160), 2)
        painter.setPen(sent_pen)
        self.draw_line(painter, width, height, data_points, max_value, 1)
        
        # Draw received data line (green)
        received_pen = QPen(QColor(45, 160, 45), 2)
        painter.setPen(received_pen)
        self.draw_line(painter, width, height, data_points, max_value, 2)
    
    def draw_line(self, painter: QPainter, width: int, height: int, 
                  data_points: List[tuple], max_value: int, data_index: int):
        """Draw a single data line"""
        points = []
        
        for i, (timestamp, sent, received) in enumerate(data_points):
            x = int((i / len(data_points)) * width)
            value = sent if data_index == 1 else received
            y = height - int((value / max_value) * height)
            points.append((x, y))
        
        # Draw the line
        for i in range(len(points) - 1):
            painter.drawLine(points[i][0], points[i][1], 
                           points[i + 1][0], points[i + 1][1])
    
    def draw_axes_labels(self, painter: QPainter, width: int, height: int, max_value: int):
        """Draw axis labels"""
        painter.setPen(QColor(200, 200, 200))
        painter.setFont(QFont("Arial", 8))
        
        # Y-axis labels (traffic values)
        for i in range(0, height, 30):
            value = max_value * (height - i) / height
            label = f"{value:.0f}"
            painter.drawText(5, i + 10, label)
        
        # X-axis label
        painter.drawText(width // 2, height - 5, "Time")
    
    def mousePressEvent(self, event):
        """Handle mouse press events"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Emit signal for graph interaction
            if self.parent:
                self.parent.graph_clicked.emit("graph_clicked")
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for tooltips"""
        # Could implement tooltip showing data values
        pass
