# app/gui/graph.py

import random
import time
import psutil
from typing import List, Dict, Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPixmap, QLinearGradient
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
        
        # Real-time traffic monitoring
        self.last_net_io = None
        self.last_time = time.time()
        
        self.init_ui()
        self.start_updates()
    
    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header with improved styling
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        
        self.title_label = QLabel("📊 Enterprise Network Traffic Monitor")
        self.title_label.setObjectName("graph_title")
        self.title_label.setStyleSheet("""
            QLabel#graph_title {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                padding: 4px 8px;
                background-color: #2d5aa0;
                border-radius: 6px;
            }
        """)
        header_layout.addWidget(self.title_label)
        
        # Stats display
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("stats_frame")
        self.stats_frame.setStyleSheet("""
            QFrame#stats_frame {
                background-color: #2d2d2d;
                border: 1px solid #404040;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        stats_layout = QHBoxLayout(self.stats_frame)
        stats_layout.setSpacing(16)
        
        self.sent_label = QLabel("📤 Sent: 0 B")
        self.sent_label.setObjectName("stat_label")
        self.received_label = QLabel("📥 Received: 0 B")
        self.received_label.setObjectName("stat_label")
        self.total_label = QLabel("📊 Total: 0 B")
        self.total_label.setObjectName("stat_label")
        self.bandwidth_label = QLabel("⚡ Bandwidth: 0 KB/s")
        self.bandwidth_label.setObjectName("stat_label")
        
        for label in [self.sent_label, self.received_label, self.total_label, self.bandwidth_label]:
            label.setStyleSheet("""
                QLabel#stat_label {
                    color: #e0e0e0;
                    font-size: 12px;
                    font-weight: 500;
                    padding: 2px 6px;
                    background-color: #353535;
                    border-radius: 4px;
                }
            """)
            stats_layout.addWidget(label)
        
        header_layout.addWidget(self.stats_frame)
        header_layout.addStretch()
        
        self.status_label = QLabel("🟢 Ready")
        self.status_label.setObjectName("status_label")
        self.status_label.setStyleSheet("""
            QLabel#status_label {
                color: #4caf50;
                font-size: 12px;
                font-weight: 500;
                padding: 4px 8px;
                background-color: #1b5e20;
                border-radius: 4px;
            }
        """)
        header_layout.addWidget(self.status_label)
        
        layout.addLayout(header_layout)
        
        # Graph widget
        self.graph_widget = GraphWidget(self)
        layout.addWidget(self.graph_widget)
        
        self.setLayout(layout)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
            }
        """)
    
    def start_updates(self):
        """Start real-time graph updates"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_graph)
        self.update_timer.start(self.update_interval)
        log_info("[STATS] Enterprise traffic graph updates started")
    
    def stop_updates(self):
        """Stop real-time graph updates"""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        log_info("[STATS] Enterprise traffic graph updates stopped")
    
    def update_graph(self):
        """Update the graph with REAL network data"""
        try:
            current_time = time.time()
            
            # Get REAL network I/O data using psutil
            net_io = psutil.net_io_counters()
            
            # Calculate REAL bandwidth
            if self.last_net_io:
                time_diff = current_time - self.last_time
                if time_diff > 0:  # Prevent division by zero
                    bytes_sent_diff = net_io.bytes_sent - self.last_net_io.bytes_sent
                    bytes_recv_diff = net_io.bytes_recv - self.last_net_io.bytes_recv
                    
                    # Calculate bandwidth in KB/s
                    bandwidth_sent = (bytes_sent_diff / 1024) / time_diff
                    bandwidth_recv = (bytes_recv_diff / 1024) / time_diff
                    total_bandwidth = bandwidth_sent + bandwidth_recv
                    
                    # Add REAL data point
                    self.add_data_point(current_time, bandwidth_sent, bandwidth_recv)
                    
                    # Update stats with REAL data
                    self.update_stats(bandwidth_sent, bandwidth_recv, total_bandwidth)
                    
                    # Update status
                    self.status_label.setText("🟢 Live")
                    self.status_label.setStyleSheet("""
                        QLabel#status_label {
                            color: #4caf50;
                            font-size: 12px;
                            font-weight: 500;
                            padding: 4px 8px;
                            background-color: #1b5e20;
                            border-radius: 4px;
                        }
                    """)
                else:
                    # Time difference too small, skip update
                    return
            else:
                # First run - initialize
                self.add_data_point(current_time, 0, 0)
                self.update_stats(0, 0, 0)
                self.status_label.setText("🟡 Initializing")
                self.status_label.setStyleSheet("""
                    QLabel#status_label {
                        color: #ff9800;
                        font-size: 12px;
                        font-weight: 500;
                        padding: 4px 8px;
                        background-color: #e65100;
                        border-radius: 4px;
                    }
                """)
            
            # Store for next calculation
            self.last_net_io = net_io
            self.last_time = current_time
            
            # Update the graph widget
            if self.isVisible():
                self.graph_widget.update()
            
        except Exception as e:
            log_error(f"Enterprise graph update error: {e}")
            self.status_label.setText("🔴 Error")
            self.status_label.setStyleSheet("""
                QLabel#status_label {
                    color: #f44336;
                    font-size: 12px;
                    font-weight: 500;
                    padding: 4px 8px;
                    background-color: #b71c1c;
                    border-radius: 4px;
                }
            """)
    
    def update_stats(self, bandwidth_sent: float, bandwidth_recv: float, total_bandwidth: float):
        """Update the statistics display with REAL bandwidth data"""
        self.sent_label.setText(f"📤 Sent: {self.format_bytes(bandwidth_sent * 1024)}/s")
        self.received_label.setText(f"📥 Received: {self.format_bytes(bandwidth_recv * 1024)}/s")
        self.total_label.setText(f"📊 Total: {self.format_bytes(total_bandwidth * 1024)}/s")
        self.bandwidth_label.setText(f"⚡ Bandwidth: {total_bandwidth:.1f} KB/s")
    
    def add_data_point(self, timestamp: float, bandwidth_sent: float, bandwidth_recv: float):
        """Add a new REAL data point to the graph"""
        self.data_points.append((timestamp, bandwidth_sent, bandwidth_recv))
        
        # Keep only the last max_points
        if len(self.data_points) > self.max_points:
            self.data_points.pop(0)
    
    def set_device_data(self, device_ip: str, data: Dict):
        """Set data for a specific device"""
        self.device_data[device_ip] = data
        self.selected_device = device_ip
    
    def format_bytes(self, bytes_value: float) -> str:
        """Format bytes with appropriate units"""
        if bytes_value < 1024:
            return f"{bytes_value:.1f} B"
        elif bytes_value < 1024 * 1024:
            return f"{bytes_value / 1024:.1f} KB"
        elif bytes_value < 1024 * 1024 * 1024:
            return f"{bytes_value / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_value / (1024 * 1024 * 1024):.1f} GB"
    
    def get_graph_data(self) -> List[tuple]:
        """Get current graph data"""
        return self.data_points.copy()
    
    def clear_data(self):
        """Clear all graph data"""
        self.data_points.clear()
        self.last_net_io = None
        self.last_time = time.time()
        if self.isVisible():
            self.graph_widget.update()
    
    def set_update_interval(self, interval_ms: int):
        """Set the update interval"""
        self.update_interval = interval_ms
        if hasattr(self, 'update_timer'):
            self.update_timer.setInterval(interval_ms)
    
    def set_controller(self, controller):
        """Set the controller for additional data access"""
        self.controller = controller

class GraphWidget(QWidget):
    """Custom graph drawing widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                border: 1px solid #404040;
                border-radius: 6px;
            }
        """)
    
    def paintEvent(self, event):
        """Custom paint event for graph drawing"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Draw background
        self.draw_background(painter, width, height)
        
        # Get data from parent
        if hasattr(self.parent(), 'data_points') and self.parent().data_points:
            data_points = self.parent().data_points
            
            # Calculate max value for scaling
            max_value = 0
            for _, sent, received in data_points:
                max_value = max(max_value, sent, received)
            
            # Add some padding to max value
            max_value = max(max_value * 1.1, 1)
            
            # Draw grid
            self.draw_grid(painter, width, height, max_value)
            
            # Draw axes
            self.draw_axes(painter, width, height)
            
            # Draw data lines
            self.draw_data_lines(painter, width, height, data_points, max_value)
            
            # Draw data points
            self.draw_data_points(painter, width, height, data_points, max_value)
            
            # Draw axes labels
            self.draw_axes_labels(painter, width, height, max_value)
        else:
            # Draw placeholder when no data
            self.draw_placeholder(painter, width, height)
    
    def draw_background(self, painter: QPainter, width: int, height: int):
        """Draw graph background"""
        painter.fillRect(0, 0, width, height, QColor("#1e1e1e"))
    
    def draw_placeholder(self, painter: QPainter, width: int, height: int):
        """Draw placeholder when no data is available"""
        painter.setPen(QPen(QColor("#666666"), 1))
        painter.setFont(QFont("Arial", 12))
        
        text = "📊 Waiting for network data..."
        text_rect = painter.fontMetrics().boundingRect(text)
        x = (width - text_rect.width()) // 2
        y = (height + text_rect.height()) // 2
        
        painter.drawText(x, y, text)
    
    def draw_grid(self, painter: QPainter, width: int, height: int, max_value: int):
        """Draw grid lines"""
        painter.setPen(QPen(QColor("#333333"), 1))
        
        # Horizontal grid lines
        for i in range(1, 5):
            y = height - (i * height // 5)
            painter.drawLine(50, y, width - 20, y)
        
        # Vertical grid lines
        for i in range(1, 10):
            x = 50 + (i * (width - 70) // 10)
            painter.drawLine(x, 20, x, height - 20)
    
    def draw_axes(self, painter: QPainter, width: int, height: int):
        """Draw X and Y axes"""
        painter.setPen(QPen(QColor("#ffffff"), 2))
        
        # Y-axis
        painter.drawLine(50, 20, 50, height - 20)
        
        # X-axis
        painter.drawLine(50, height - 20, width - 20, height - 20)
    
    def draw_data_lines(self, painter: QPainter, width: int, height: int, 
                       data_points: List[tuple], max_value: int):
        """Draw data lines for sent and received traffic"""
        if len(data_points) < 2:
            return
        
        # Draw sent traffic line (blue)
        self.draw_line(painter, width, height, data_points, max_value, 1)
        
        # Draw received traffic line (green)
        self.draw_line(painter, width, height, data_points, max_value, 2)
    
    def draw_line(self, painter: QPainter, width: int, height: int, 
                 data_points: List[tuple], max_value: int, data_index: int):
        """Draw a single data line"""
        # Set color based on data type
        if data_index == 1:  # Sent
            color = QColor("#2196F3")  # Blue
        else:  # Received
            color = QColor("#4CAF50")  # Green
        
        painter.setPen(QPen(color, 2))
        
        # Calculate points
        points = []
        for i, (timestamp, sent, received) in enumerate(data_points):
            x = 50 + (i * (width - 70) // (len(data_points) - 1))
            value = sent if data_index == 1 else received
            y = height - 20 - (value / max_value) * (height - 40)
            points.append((x, y))
        
        # Draw line
        for i in range(len(points) - 1):
            painter.drawLine(int(points[i][0]), int(points[i][1]), 
                           int(points[i + 1][0]), int(points[i + 1][1]))
    
    def draw_data_points(self, painter: QPainter, width: int, height: int,
                        data_points: List[tuple], max_value: int):
        """Draw data points"""
        # Draw sent points (blue)
        painter.setPen(QPen(QColor("#2196F3"), 1))
        painter.setBrush(QColor("#2196F3"))
        
        for i, (timestamp, sent, received) in enumerate(data_points):
            x = 50 + (i * (width - 70) // (len(data_points) - 1))
            y = height - 20 - (sent / max_value) * (height - 40)
            painter.drawEllipse(int(x - 2), int(y - 2), 4, 4)
        
        # Draw received points (green)
        painter.setPen(QPen(QColor("#4CAF50"), 1))
        painter.setBrush(QColor("#4CAF50"))
        
        for i, (timestamp, sent, received) in enumerate(data_points):
            x = 50 + (i * (width - 70) // (len(data_points) - 1))
            y = height - 20 - (received / max_value) * (height - 40)
            painter.drawEllipse(int(x - 2), int(y - 2), 4, 4)
    
    def draw_axes_labels(self, painter: QPainter, width: int, height: int, max_value: int):
        """Draw axis labels"""
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Arial", 8))
        
        # Y-axis labels (bandwidth)
        for i in range(6):
            y = height - 20 - (i * (height - 40) // 5)
            value = (i * max_value) // 5
            text = self.format_value(value)
            painter.drawText(5, y + 3, text)
        
        # X-axis label
        painter.drawText(width // 2 - 30, height - 5, "Time")
        
        # Legend
        painter.setFont(QFont("Arial", 9))
        painter.setPen(QColor("#2196F3"))
        painter.drawText(width - 80, 25, "📤 Sent")
        painter.setPen(QColor("#4CAF50"))
        painter.drawText(width - 80, 40, "📥 Received")
    
    def format_value(self, value: float) -> str:
        """Format value for display"""
        if value < 1024:
            return f"{value:.0f} B"
        elif value < 1024 * 1024:
            return f"{value / 1024:.0f} KB"
        else:
            return f"{value / (1024 * 1024):.1f} MB"
    
    def mousePressEvent(self, event):
        """Handle mouse press events"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Emit signal for graph interaction
            if hasattr(self.parent(), 'graph_clicked'):
                self.parent().graph_clicked.emit("graph_clicked")
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for tooltips"""
        # Could implement tooltip showing exact values at cursor position
        pass
