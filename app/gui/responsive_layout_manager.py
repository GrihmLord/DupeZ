#!/usr/bin/env python3
"""
Responsive Layout Manager for DupeZ GUI
Ensures all components fit properly on different screen sizes
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QPushButton, QTableWidget, QTabWidget,
                             QGroupBox, QSplitter, QScrollArea, QFrame,
                             QSizePolicy, QApplication)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor
from typing import Dict, List, Optional, Tuple
import sys

class ResponsiveLayoutManager:
    """Manages responsive layouts for different screen sizes"""
    
    def __init__(self):
        self.screen_sizes = {
            'small': (1024, 768),      # Small laptop
            'medium': (1366, 768),     # Standard laptop
            'large': (1920, 1080),     # Full HD
            'ultra': (2560, 1440),     # 2K
            '4k': (3840, 2160)         # 4K
        }
        
        self.current_screen_size = self._detect_screen_size()
        self.scale_factors = self._calculate_scale_factors()
        
    def _detect_screen_size(self) -> str:
        """Detect current screen size category"""
        try:
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                geometry = screen.availableGeometry()
                width, height = geometry.width(), geometry.height()
                
                # Determine screen size category
                if width <= 1024:
                    return 'small'
                elif width <= 1366:
                    return 'medium'
                elif width <= 1920:
                    return 'large'
                elif width <= 2560:
                    return 'ultra'
                else:
                    return '4k'
        except Exception:
            pass
        
        return 'medium'  # Default fallback
    
    def _calculate_scale_factors(self) -> Dict[str, float]:
        """Calculate scale factors for different screen sizes"""
        base_size = self.screen_sizes['medium']
        base_width, base_height = base_size
        
        factors = {}
        for size_name, (width, height) in self.screen_sizes.items():
            width_factor = width / base_width
            height_factor = height / base_height
            factors[size_name] = min(width_factor, height_factor)
        
        return factors
    
    def get_scale_factor(self) -> float:
        """Get current scale factor"""
        return self.scale_factors.get(self.current_screen_size, 1.0)
    
    def get_responsive_font_size(self, base_size: int) -> int:
        """Get responsive font size based on screen size"""
        scale_factor = self.get_scale_factor()
        return max(8, int(base_size * scale_factor))
    
    def get_responsive_spacing(self, base_spacing: int) -> int:
        """Get responsive spacing based on screen size"""
        scale_factor = self.get_scale_factor()
        return max(2, int(base_spacing * scale_factor))
    
    def get_responsive_margins(self, base_margins: int) -> int:
        """Get responsive margins based on screen size"""
        scale_factor = self.get_scale_factor()
        return max(4, int(base_margins * scale_factor))

class ResponsiveWidget(QWidget):
    """Base class for responsive widgets"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_manager = None
        self.setup_responsive_layout()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_layout(self):
        """Setup responsive layout - override in subclasses"""
        pass
    
    def resizeEvent(self, event):
        """Handle resize events for responsive design"""
        super().resizeEvent(event)
        self.update_responsive_layout()
    
    def update_responsive_layout(self):
        """Update layout for current screen size - override in subclasses"""
        pass

class ResponsiveTableWidget(QTableWidget):
    """Responsive table widget with automatic column sizing"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_manager = None
        self.column_ratios = {}
        self.setup_responsive_table()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_table(self):
        """Setup responsive table properties"""
        # Enable automatic column sizing
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(
            self.horizontalHeader().ResizeMode.Interactive
        )
        
        # Set responsive font
        font = self.font()
        font.setPointSize(self.layout_manager.get_responsive_font_size(9))
        self.setFont(font)
    
    def set_column_ratios(self, ratios: Dict[int, float]):
        """Set column width ratios for responsive sizing"""
        self.column_ratios = ratios
    
    def resizeEvent(self, event):
        """Handle resize events with responsive column sizing"""
        super().resizeEvent(event)
        self.update_column_widths()
    
    def update_column_widths(self):
        """Update column widths based on current table width"""
        if not self.column_ratios:
            return
        
        total_width = self.width()
        if total_width <= 0:
            return
        
        # Calculate column widths based on ratios
        for col, ratio in self.column_ratios.items():
            if col < self.columnCount():
                width = int(total_width * ratio)
                self.setColumnWidth(col, width)

class ResponsiveTabWidget(QTabWidget):
    """Responsive tab widget with proper sizing"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_manager = None
        self.setup_responsive_tabs()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_tabs(self):
        """Setup responsive tab properties"""
        # Set tab position
        self.setTabPosition(QTabWidget.TabPosition.North)
        
        # Set responsive font for tab labels
        font = self.font()
        font.setPointSize(self.layout_manager.get_responsive_font_size(10))
        self.setFont(font)
        
        # Enable tab scrolling for small screens
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)

class ResponsiveGroupBox(QGroupBox):
    """Responsive group box with proper spacing"""
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self._layout_manager = None
        self.setup_responsive_group()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_group(self):
        """Setup responsive group box properties"""
        # Set responsive font
        font = self.font()
        font.setPointSize(self.layout_manager.get_responsive_font_size(10))
        font.setBold(True)
        self.setFont(font)
        
        # Set responsive margins
        margins = self.layout_manager.get_responsive_margins(8)
        self.setContentsMargins(margins, margins, margins, margins)

class ResponsiveButton(QPushButton):
    """Responsive button with proper sizing"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._layout_manager = None
        self.setup_responsive_button()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_button(self):
        """Setup responsive button properties"""
        # Set responsive font
        font = self.font()
        font.setPointSize(self.layout_manager.get_responsive_font_size(9))
        self.setFont(font)
        
        # Set minimum size
        min_height = max(20, int(25 * self.layout_manager.get_scale_factor()))
        self.setMinimumHeight(min_height)
        
        # Set size policy
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

class ResponsiveLabel(QLabel):
    """Responsive label with proper font sizing"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._layout_manager = None
        self.setup_responsive_label()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_label(self):
        """Setup responsive label properties"""
        # Set responsive font
        font = self.font()
        font.setPointSize(self.layout_manager.get_responsive_font_size(9))
        self.setFont(font)
        
        # Enable word wrapping
        self.setWordWrap(True)

class ResponsiveSplitter(QSplitter):
    """Responsive splitter with proper sizing"""
    
    def __init__(self, orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._layout_manager = None
        self.setup_responsive_splitter()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_splitter(self):
        """Setup responsive splitter properties"""
        # Set handle width
        handle_width = max(4, int(6 * self.layout_manager.get_scale_factor()))
        self.setHandleWidth(handle_width)
        
        # Enable children collapsible
        self.setChildrenCollapsible(True)

class ResponsiveScrollArea(QScrollArea):
    """Responsive scroll area with proper sizing"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_manager = None
        self.setup_responsive_scroll()
    
    @property
    def layout_manager(self):
        """Lazy initialization of layout manager"""
        if self._layout_manager is None:
            self._layout_manager = ResponsiveLayoutManager()
        return self._layout_manager
    
    def setup_responsive_scroll(self):
        """Setup responsive scroll area properties"""
        # Set scroll bar policy
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Set widget resize mode
        self.setWidgetResizable(True)
        
        # Set frame style
        self.setFrameStyle(QFrame.Shape.StyledPanel)

def create_responsive_layout(layout_type: str = "vertical", parent=None) -> QVBoxLayout | QHBoxLayout | QGridLayout:
    """Create a responsive layout with proper spacing"""
    layout_manager = ResponsiveLayoutManager()
    
    if layout_type == "vertical":
        layout = QVBoxLayout()
    elif layout_type == "horizontal":
        layout = QHBoxLayout()
    elif layout_type == "grid":
        layout = QGridLayout()
    else:
        layout = QVBoxLayout()
    
    # Set responsive spacing and margins
    spacing = layout_manager.get_responsive_spacing(8)
    margins = layout_manager.get_responsive_margins(8)
    
    layout.setSpacing(spacing)
    layout.setContentsMargins(margins, margins, margins, margins)
    
    return layout

def apply_responsive_styling(widget: QWidget, style_type: str = "default"):
    """Apply responsive styling to a widget"""
    layout_manager = ResponsiveLayoutManager()
    scale_factor = layout_manager.get_scale_factor()
    
    if style_type == "compact":
        # Compact styling for small screens
        widget.setStyleSheet(f"""
            QWidget {{
                font-size: {max(8, int(9 * scale_factor))}px;
                padding: {max(2, int(4 * scale_factor))}px;
                margin: {max(1, int(2 * scale_factor))}px;
            }}
        """)
    elif style_type == "comfortable":
        # Comfortable styling for large screens
        widget.setStyleSheet(f"""
            QWidget {{
                font-size: {max(10, int(11 * scale_factor))}px;
                padding: {max(4, int(6 * scale_factor))}px;
                margin: {max(2, int(4 * scale_factor))}px;
            }}
        """)
    else:
        # Default responsive styling
        widget.setStyleSheet(f"""
            QWidget {{
                font-size: {max(9, int(10 * scale_factor))}px;
                padding: {max(3, int(5 * scale_factor))}px;
                margin: {max(1, int(3 * scale_factor))}px;
            }}
        """)

def get_screen_info() -> Dict[str, any]:
    """Get current screen information"""
    try:
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            geometry = screen.availableGeometry()
            physical_size = screen.physicalSize()
            
            return {
                'width': geometry.width(),
                'height': geometry.height(),
                'physical_width': physical_size.width(),
                'physical_height': physical_size.height(),
                'dpi': screen.logicalDotsPerInch(),
                'device_pixel_ratio': screen.devicePixelRatio()
            }
    except Exception:
        pass
    
    return {
        'width': 1366,
        'height': 768,
        'physical_width': 0,
        'physical_height': 0,
        'dpi': 96,
        'device_pixel_ratio': 1.0
    } 