#!/usr/bin/env python3
"""
Responsive Layout Manager for DupeZ
Handles dynamic layouts and adaptive sizing for different screen sizes
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from typing import Dict, List, Optional, Tuple
import math

from app.logs.logger import log_info, log_error

class ResponsiveLayoutManager:
    """Manages responsive layouts and adaptive sizing"""
    
    def __init__(self, parent_widget: QWidget):
        self.parent = parent_widget
        self.screen_sizes = {
            'small': {'min_width': 1000, 'min_height': 600},
            'medium': {'min_width': 1200, 'min_height': 700},
            'large': {'min_width': 1600, 'min_height': 900},
            'xlarge': {'min_width': 1920, 'min_height': 1080}
        }
        self.current_size_category = 'medium'
        self.layout_elements = {}
        self.adaptive_timers = {}
        
        # Initialize responsive settings
        self.setup_responsive_settings()
    
    def setup_responsive_settings(self):
        """Setup initial responsive settings"""
        self.responsive_config = {
            'sidebar': {
                'small': {'min_width': 200, 'max_width': 250, 'ratio': 0.25},
                'medium': {'min_width': 250, 'max_width': 350, 'ratio': 0.22},
                'large': {'min_width': 300, 'max_width': 400, 'ratio': 0.18},
                'xlarge': {'min_width': 350, 'max_width': 450, 'ratio': 0.16}
            },
            'tabs': {
                'small': {'min_width': 100, 'padding': '10px 16px', 'font_size': '9pt'},
                'medium': {'min_width': 120, 'padding': '12px 20px', 'font_size': '10pt'},
                'large': {'min_width': 140, 'padding': '14px 24px', 'font_size': '11pt'},
                'xlarge': {'min_width': 160, 'padding': '16px 28px', 'font_size': '12pt'}
            },
            'buttons': {
                'small': {'padding': '6px 12px', 'min_height': 18, 'font_size': '8pt'},
                'medium': {'padding': '8px 16px', 'min_height': 20, 'font_size': '9pt'},
                'large': {'padding': '10px 20px', 'min_height': 24, 'font_size': '10pt'},
                'xlarge': {'padding': '12px 24px', 'min_height': 28, 'font_size': '11pt'}
            },
            'inputs': {
                'small': {'padding': '6px 10px', 'min_height': 18, 'font_size': '8pt'},
                'medium': {'padding': '8px 12px', 'min_height': 20, 'font_size': '9pt'},
                'large': {'padding': '10px 16px', 'min_height': 24, 'font_size': '10pt'},
                'xlarge': {'padding': '12px 20px', 'min_height': 28, 'font_size': '11pt'}
            }
        }
    
    def get_screen_category(self, width: int, height: int) -> str:
        """Determine screen size category"""
        if width >= 1920:
            return 'xlarge'
        elif width >= 1600:
            return 'large'
        elif width >= 1200:
            return 'medium'
        else:
            return 'small'
    
    def calculate_responsive_dimensions(self, width: int, height: int) -> Dict:
        """Calculate responsive dimensions for all elements"""
        category = self.get_screen_category(width, height)
        self.current_size_category = category
        
        dimensions = {
            'window': {
                'min_width': self.screen_sizes[category]['min_width'],
                'min_height': self.screen_sizes[category]['min_height'],
                'target_width': int(width * 0.8 if category == 'medium' else 0.85 if category == 'large' else 0.95),
                'target_height': int(height * 0.8 if category == 'medium' else 0.85 if category == 'large' else 0.95)
            },
            'sidebar': {
                'min_width': self.responsive_config['sidebar'][category]['min_width'],
                'max_width': self.responsive_config['sidebar'][category]['max_width'],
                'target_width': max(
                    self.responsive_config['sidebar'][category]['min_width'],
                    min(
                        self.responsive_config['sidebar'][category]['max_width'],
                        int(width * self.responsive_config['sidebar'][category]['ratio'])
                    )
                )
            },
            'tabs': self.responsive_config['tabs'][category],
            'buttons': self.responsive_config['buttons'][category],
            'inputs': self.responsive_config['inputs'][category]
        }
        
        return dimensions
    
    def apply_responsive_layout(self, dimensions: Dict):
        """Apply responsive layout to all registered elements"""
        try:
            # Apply sidebar sizing
            if 'sidebar' in self.layout_elements:
                sidebar = self.layout_elements['sidebar']
                sidebar.setMinimumWidth(dimensions['sidebar']['min_width'])
                sidebar.setMaximumWidth(dimensions['sidebar']['max_width'])
                sidebar.setFixedWidth(dimensions['sidebar']['target_width'])
            
            # Apply tab styling
            if 'content_tabs' in self.layout_elements:
                tabs = self.layout_elements['content_tabs']
                tab_style = f"""
                    QTabBar::tab {{
                        min-width: {dimensions['tabs']['min_width']}px;
                        padding: {dimensions['tabs']['padding']};
                        font-size: {dimensions['tabs']['font_size']};
                    }}
                """
                tabs.setStyleSheet(tab_style)
            
            # Apply button styling
            if 'buttons' in self.layout_elements:
                for button_id, button in self.layout_elements['buttons'].items():
                    button_style = f"""
                        QPushButton {{
                            padding: {dimensions['buttons']['padding']};
                            min-height: {dimensions['buttons']['min_height']}px;
                            font-size: {dimensions['buttons']['font_size']};
                        }}
                    """
                    button.setStyleSheet(button_style)
            
            # Apply input styling
            if 'inputs' in self.layout_elements:
                for input_id, input_widget in self.layout_elements['inputs'].items():
                    input_style = f"""
                        QLineEdit, QComboBox, QSpinBox {{
                            padding: {dimensions['inputs']['padding']};
                            min-height: {dimensions['inputs']['min_height']}px;
                            font-size: {dimensions['inputs']['font_size']};
                        }}
                    """
                    input_widget.setStyleSheet(input_style)
            
            log_info(f"Applied responsive layout for {self.current_size_category} screen")
            
        except Exception as e:
            log_error(f"Error applying responsive layout: {e}")
    
    def register_layout_element(self, element_type: str, element_id: str, element: QWidget):
        """Register a layout element for responsive management"""
        if element_type not in self.layout_elements:
            self.layout_elements[element_type] = {}
        
        self.layout_elements[element_type][element_id] = element
        log_info(f"Registered {element_type}: {element_id}")
    
    def unregister_layout_element(self, element_type: str, element_id: str):
        """Unregister a layout element"""
        if element_type in self.layout_elements and element_id in self.layout_elements[element_type]:
            del self.layout_elements[element_type][element_id]
            log_info(f"Unregistered {element_type}: {element_id}")
    
    def create_adaptive_splitter(self, orientation: Qt.Orientation = Qt.Orientation.Horizontal) -> QSplitter:
        """Create an adaptive splitter that adjusts to content"""
        splitter = QSplitter(orientation)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(3)
        
        # Store splitter for responsive management
        self.layout_elements['splitters'] = self.layout_elements.get('splitters', {})
        self.layout_elements['splitters'][f'splitter_{len(self.layout_elements["splitters"])}'] = splitter
        
        return splitter
    
    def create_responsive_grid(self, rows: int, cols: int, spacing: int = 8) -> QGridLayout:
        """Create a responsive grid layout"""
        grid = QGridLayout()
        grid.setSpacing(spacing)
        grid.setContentsMargins(spacing, spacing, spacing, spacing)
        
        # Store grid for responsive management
        self.layout_elements['grids'] = self.layout_elements.get('grids', {})
        self.layout_elements['grids'][f'grid_{len(self.layout_elements["grids"])}'] = grid
        
        return grid
    
    def create_adaptive_container(self, layout_type: str = 'vertical') -> Tuple[QWidget, QVBoxLayout]:
        """Create an adaptive container with appropriate layout"""
        container = QWidget()
        
        if layout_type == 'vertical':
            layout = QVBoxLayout()
        elif layout_type == 'horizontal':
            layout = QHBoxLayout()
        else:
            layout = QVBoxLayout()
        
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        container.setLayout(layout)
        
        # Store container for responsive management
        self.layout_elements['containers'] = self.layout_elements.get('containers', {})
        self.layout_elements['containers'][f'container_{len(self.layout_elements["containers"])}'] = container
        
        return container, layout
    
    def optimize_for_screen_size(self, width: int, height: int):
        """Optimize layout for specific screen size"""
        dimensions = self.calculate_responsive_dimensions(width, height)
        self.apply_responsive_layout(dimensions)
        
        # Additional optimizations based on screen size
        if self.current_size_category == 'small':
            self._optimize_small_screen()
        elif self.current_size_category == 'large':
            self._optimize_large_screen()
        elif self.current_size_category == 'xlarge':
            self._optimize_xlarge_screen()
    
    def _optimize_small_screen(self):
        """Optimize layout for small screens"""
        # Reduce margins and spacing
        for container_id, container in self.layout_elements.get('containers', {}).items():
            layout = container.layout()
            if layout:
                layout.setSpacing(4)
                layout.setContentsMargins(4, 4, 4, 4)
        
        # Make tabs more compact
        if 'content_tabs' in self.layout_elements:
            tabs = self.layout_elements['content_tabs']
            tabs.setStyleSheet("""
                QTabBar::tab {
                    margin-right: 1px;
                    padding: 8px 12px;
                }
            """)
    
    def _optimize_large_screen(self):
        """Optimize layout for large screens"""
        # Increase margins and spacing for better readability
        for container_id, container in self.layout_elements.get('containers', {}).items():
            layout = container.layout()
            if layout:
                layout.setSpacing(12)
                layout.setContentsMargins(12, 12, 12, 12)
    
    def _optimize_xlarge_screen(self):
        """Optimize layout for extra large screens"""
        # Maximum spacing and margins for 4K displays
        for container_id, container in self.layout_elements.get('containers', {}).items():
            layout = container.layout()
            if layout:
                layout.setSpacing(16)
                layout.setContentsMargins(16, 16, 16, 16)
        
        # Increase font sizes for better readability
        if 'content_tabs' in self.layout_elements:
            tabs = self.layout_elements['content_tabs']
            tabs.setStyleSheet("""
                QTabBar::tab {
                    font-size: 12pt;
                    padding: 16px 28px;
                }
            """)
    
    def get_responsive_font(self, base_size: int = 9) -> QFont:
        """Get responsive font size based on screen category"""
        font_sizes = {
            'small': base_size - 1,
            'medium': base_size,
            'large': base_size + 1,
            'xlarge': base_size + 2
        }
        
        font = QFont()
        font.setPointSize(font_sizes.get(self.current_size_category, base_size))
        return font
    
    def cleanup(self):
        """Cleanup responsive layout manager"""
        try:
            # Clear all registered elements
            self.layout_elements.clear()
            
            # Stop all adaptive timers
            for timer in self.adaptive_timers.values():
                if timer.isActive():
                    timer.stop()
            
            self.adaptive_timers.clear()
            
            log_info("Responsive layout manager cleaned up")
            
        except Exception as e:
            log_error(f"Error cleaning up responsive layout manager: {e}")


class ResponsiveWidget(QWidget):
    """Base class for responsive widgets"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_manager = None
        self.setup_responsive_layout()
    
    def setup_responsive_layout(self):
        """Setup responsive layout for this widget"""
        if hasattr(self.parent(), 'layout_manager'):
            self.layout_manager = self.parent().layout_manager
        else:
            # Create standalone layout manager
            self.layout_manager = ResponsiveLayoutManager(self)
    
    def resizeEvent(self, event):
        """Handle resize events for responsive behavior"""
        super().resizeEvent(event)
        
        if self.layout_manager:
            self.layout_manager.optimize_for_screen_size(
                event.size().width(),
                event.size().height()
            )
    
    def register_for_responsive_layout(self, element_type: str, element_id: str, element: QWidget):
        """Register this widget's elements for responsive layout management"""
        if self.layout_manager:
            self.layout_manager.register_layout_element(element_type, element_id, element)
    
    def cleanup_responsive_layout(self):
        """Cleanup responsive layout resources"""
        if self.layout_manager:
            self.layout_manager.cleanup() 