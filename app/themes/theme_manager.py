#!/usr/bin/env python3
"""
Theme Manager for DupeZ
Handles light, dark, and rainbow themes with dynamic color generation
"""

import os
import sys
import json
import time
import math
from typing import Dict, List, Optional, Tuple
from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QWidget

from app.logs.logger import log_info, log_error

class ThemeManager(QObject):
    """Manages application themes with support for light, dark, and rainbow modes"""
    
    # Signals
    theme_changed = pyqtSignal(str)  # Emit theme name when changed
    color_updated = pyqtSignal(str, str)  # Emit color name and value when updated
    
    def __init__(self):
        super().__init__()
        self.current_theme = "dark"
        self.themes_dir = "app/themes"
        self.theme_files = {
            "light": "light.qss",
            "dark": "dark.qss", 
            "hacker": "hacker.qss",
            "rainbow": "rainbow.qss",
            "responsive_dark": "responsive_dark.qss"
        }
        self.rainbow_timer = None
        self.rainbow_hue = 0.0
        self.rainbow_speed = 2.0  # Degrees per frame
        
        # Rainbow color cache
        self.rainbow_colors = {}
        self.last_rainbow_update = 0
        
        # Load theme files
        self.load_theme_files()
        
    def load_theme_files(self):
        """Load all theme files into memory"""
        self.theme_styles = {}
        
        # Resolve base path to support PyInstaller (sys._MEIPASS) and dev runs
        base_path = getattr(sys, '_MEIPASS', os.getcwd())
        themes_base_dir = os.path.join(base_path, self.themes_dir)
        
        for theme_name, filename in self.theme_files.items():
            filepath = os.path.join(themes_base_dir, filename)
            try:
                if os.path.exists(filepath):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.theme_styles[theme_name] = f.read()
                    log_info(f"Loaded theme: {theme_name}")
                else:
                    # Fallback to relative path in case of unusual working dirs
                    alt_path = os.path.join(self.themes_dir, filename)
                    if os.path.exists(alt_path):
                        with open(alt_path, 'r', encoding='utf-8') as f:
                            self.theme_styles[theme_name] = f.read()
                        log_info(f"Loaded theme (alt path): {theme_name}")
                    else:
                        log_error(f"Theme file not found: {filepath}")
            except Exception as e:
                log_error(f"Error loading theme {theme_name}: {e}")
    
    def get_available_themes(self) -> List[str]:
        """Get list of available themes"""
        return list(self.theme_styles.keys())
    
    def get_current_theme(self) -> str:
        """Get current theme name"""
        return self.current_theme
    
    def apply_theme(self, theme_name: str) -> bool:
        """Apply a theme to the application"""
        try:
            if theme_name not in self.theme_styles:
                log_error(f"Theme not found: {theme_name}")
                return False
            
            # Prevent infinite loops by checking if theme is already applied
            if self.current_theme == theme_name:
                log_info(f"Theme {theme_name} is already applied")
                return True
            
            # Stop rainbow timer if switching from rainbow mode
            if self.current_theme == "rainbow" and theme_name != "rainbow":
                self.stop_rainbow_mode()
            
            # Apply the theme
            app = QApplication.instance()
            if app:
                app.setStyleSheet(self.theme_styles[theme_name])
                self.current_theme = theme_name
                log_info(f"Applied theme: {theme_name}")
                self.theme_changed.emit(theme_name)
                return True
            else:
                log_error("No QApplication instance found")
                return False
                
        except Exception as e:
            log_error(f"Error applying theme {theme_name}: {e}")
            return False
    
    def start_rainbow_mode(self):
        """Start rainbow mode with dynamic color changes"""
        try:
            if self.current_theme != "rainbow":
                self.apply_theme("rainbow")
            
            # Start rainbow animation timer
            if not self.rainbow_timer:
                self.rainbow_timer = QTimer()
                self.rainbow_timer.timeout.connect(self.update_rainbow_colors)
                self.rainbow_timer.start(50)  # Update every 50ms (20 FPS)
            
            log_info("Rainbow mode started")
            
        except Exception as e:
            log_error(f"Error starting rainbow mode: {e}")
    
    def stop_rainbow_mode(self):
        """Stop rainbow mode"""
        try:
            if self.rainbow_timer:
                self.rainbow_timer.stop()
                self.rainbow_timer = None
            
            # Reset to dark theme
            self.apply_theme("dark")
            log_info("Rainbow mode stopped")
            
        except Exception as e:
            log_error(f"Error stopping rainbow mode: {e}")
    
    def update_rainbow_colors(self):
        """Update rainbow colors for animation"""
        try:
            current_time = time.time()
            
            # Update hue
            self.rainbow_hue += self.rainbow_speed
            if self.rainbow_hue >= 360:
                self.rainbow_hue = 0
            
            # Generate rainbow colors
            colors = self.generate_rainbow_colors()
            
            # Apply dynamic colors to the application
            self.apply_rainbow_colors(colors)
            
            # Emit color update signal
            for color_name, color_value in colors.items():
                self.color_updated.emit(color_name, color_value)
                
        except Exception as e:
            log_error(f"Error updating rainbow colors: {e}")
    
    def generate_rainbow_colors(self) -> Dict[str, str]:
        """Generate rainbow color palette"""
        try:
            colors = {}
            
            # Primary colors with different hues
            base_hue = self.rainbow_hue
            hue_step = 30  # 30 degrees between colors
            
            # Background colors
            colors['background'] = self.hsv_to_hex(base_hue, 0.1, 0.05)
            colors['background_alt'] = self.hsv_to_hex(base_hue + hue_step, 0.15, 0.08)
            colors['surface'] = self.hsv_to_hex(base_hue + hue_step * 2, 0.2, 0.12)
            
            # Text colors
            colors['text_primary'] = self.hsv_to_hex(base_hue + hue_step * 3, 0.8, 0.9)
            colors['text_secondary'] = self.hsv_to_hex(base_hue + hue_step * 4, 0.6, 0.7)
            
            # Accent colors
            colors['accent_primary'] = self.hsv_to_hex(base_hue + hue_step * 5, 0.9, 0.8)
            colors['accent_secondary'] = self.hsv_to_hex(base_hue + hue_step * 6, 0.8, 0.7)
            colors['accent_tertiary'] = self.hsv_to_hex(base_hue + hue_step * 7, 0.7, 0.6)
            
            # Button colors
            colors['button_normal'] = self.hsv_to_hex(base_hue + hue_step * 8, 0.3, 0.2)
            colors['button_hover'] = self.hsv_to_hex(base_hue + hue_step * 9, 0.4, 0.3)
            colors['button_pressed'] = self.hsv_to_hex(base_hue + hue_step * 10, 0.5, 0.4)
            
            # Border colors
            colors['border'] = self.hsv_to_hex(base_hue + hue_step * 11, 0.6, 0.5)
            colors['border_highlight'] = self.hsv_to_hex(base_hue + hue_step * 12, 0.8, 0.7)
            
            return colors
            
        except Exception as e:
            log_error(f"Error generating rainbow colors: {e}")
            return {}
    
    def hsv_to_hex(self, h: float, s: float, v: float) -> str:
        """Convert HSV to hex color string"""
        try:
            # Convert HSV to RGB
            h = h / 360.0
            i = int(h * 6)
            f = h * 6 - i
            p = v * (1 - s)
            q = v * (1 - f * s)
            t = v * (1 - (1 - f) * s)
            
            if i % 6 == 0:
                r, g, b = v, t, p
            elif i % 6 == 1:
                r, g, b = q, v, p
            elif i % 6 == 2:
                r, g, b = p, v, t
            elif i % 6 == 3:
                r, g, b = p, q, v
            elif i % 6 == 4:
                r, g, b = t, p, v
            else:
                r, g, b = v, p, q
            
            # Convert to hex
            r_hex = int(r * 255)
            g_hex = int(g * 255)
            b_hex = int(b * 255)
            
            return f"#{r_hex:02x}{g_hex:02x}{b_hex:02x}"
            
        except Exception as e:
            log_error(f"Error converting HSV to hex: {e}")
            return "#000000"
    
    def apply_rainbow_colors(self, colors: Dict[str, str]):
        """Apply rainbow colors to the application"""
        try:
            app = QApplication.instance()
            if not app:
                return
            
            # Create dynamic stylesheet with rainbow colors
            stylesheet = self.create_rainbow_stylesheet(colors)
            app.setStyleSheet(stylesheet)
            
        except Exception as e:
            log_error(f"Error applying rainbow colors: {e}")
    
    def create_rainbow_stylesheet(self, colors: Dict[str, str]) -> str:
        """Create dynamic stylesheet with rainbow colors"""
        try:
            stylesheet = f"""
/* Rainbow Theme - Dynamic Colors */
QMainWindow {{
    background-color: {colors.get('background', '#0a0a0a')};
    color: {colors.get('text_primary', '#ffffff')};
}}

QWidget {{
    background-color: {colors.get('background', '#0a0a0a')};
    color: {colors.get('text_primary', '#ffffff')};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 9pt;
}}

/* Menu Bar */
QMenuBar {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border-bottom: 2px solid {colors.get('border', '#404040')};
}}

QMenuBar::item {{
    background-color: transparent;
    padding: 4px 8px;
}}

QMenuBar::item:selected {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QMenu {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
}}

QMenu::item {{
    padding: 6px 20px;
}}

QMenu::item:selected {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    color: {colors.get('background', '#0a0a0a')};
}}

/* Buttons */
QPushButton {{
    background-color: {colors.get('button_normal', '#404040')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {colors.get('button_hover', '#505050')};
    border-color: {colors.get('border_highlight', '#606060')};
}}

QPushButton:pressed {{
    background-color: {colors.get('button_pressed', '#303030')};
}}

QPushButton:disabled {{
    background-color: {colors.get('background_alt', '#1a1a1a')};
    color: {colors.get('text_secondary', '#808080')};
    border-color: {colors.get('border', '#404040')};
}}

/* Special Button Styles */
QPushButton#refresh_btn {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border-color: {colors.get('accent_secondary', '#00cc00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QPushButton#refresh_btn:hover {{
    background-color: {colors.get('accent_secondary', '#00cc00')};
}}

QPushButton#block_btn {{
    background-color: {colors.get('accent_tertiary', '#ff0000')};
    border-color: {colors.get('accent_secondary', '#cc0000')};
    color: {colors.get('background', '#0a0a0a')};
}}

QPushButton#block_btn:hover {{
    background-color: {colors.get('accent_secondary', '#cc0000')};
}}

QPushButton#smart_mode_btn {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border-color: {colors.get('accent_secondary', '#00cc00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QPushButton#smart_mode_btn:hover {{
    background-color: {colors.get('accent_secondary', '#00cc00')};
}}

/* List Widgets */
QListWidget {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 4px;
}}

QListWidget::item {{
    padding: 6px 8px;
    border-radius: 2px;
}}

QListWidget::item:selected {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QListWidget::item:hover {{
    background-color: {colors.get('button_hover', '#505050')};
}}

/* Scroll Bars */
QScrollBar:vertical {{
    background-color: {colors.get('surface', '#1a1a1a')};
    width: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:vertical {{
    background-color: {colors.get('border', '#404040')};
    border-radius: 6px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {colors.get('border_highlight', '#606060')};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {colors.get('surface', '#1a1a1a')};
    height: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:horizontal {{
    background-color: {colors.get('border', '#404040')};
    border-radius: 6px;
    min-width: 20px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {colors.get('border_highlight', '#606060')};
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Labels */
QLabel {{
    color: {colors.get('text_primary', '#ffffff')};
    background-color: transparent;
}}

QLabel#title {{
    font-size: 14pt;
    font-weight: bold;
    color: {colors.get('accent_primary', '#00ff00')};
}}

QLabel#subtitle {{
    font-size: 11pt;
    color: {colors.get('text_secondary', '#cccccc')};
}}

QLabel#status {{
    color: {colors.get('text_secondary', '#888888')};
    font-style: italic;
}}

/* Line Edits */
QLineEdit {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 6px 8px;
}}

QLineEdit:focus {{
    border-color: {colors.get('accent_primary', '#00ff00')};
}}

QLineEdit:disabled {{
    background-color: {colors.get('background_alt', '#1a1a1a')};
    color: {colors.get('text_secondary', '#808080')};
}}

/* Combo Boxes */
QComboBox {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 6px 8px;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid {colors.get('text_primary', '#ffffff')};
}}

QComboBox QAbstractItemView {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    selection-background-color: {colors.get('accent_primary', '#00ff00')};
}}

/* Check Boxes */
QCheckBox {{
    color: {colors.get('text_primary', '#ffffff')};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 2px;
    background-color: {colors.get('surface', '#1a1a1a')};
}}

QCheckBox::indicator:checked {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border-color: {colors.get('accent_primary', '#00ff00')};
}}

QCheckBox::indicator:unchecked:hover {{
    border-color: {colors.get('border_highlight', '#606060')};
}}

/* Radio Buttons */
QRadioButton {{
    color: {colors.get('text_primary', '#ffffff')};
    spacing: 8px;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 8px;
    background-color: {colors.get('surface', '#1a1a1a')};
}}

QRadioButton::indicator:checked {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border-color: {colors.get('accent_primary', '#00ff00')};
}}

QRadioButton::indicator:unchecked:hover {{
    border-color: {colors.get('border_highlight', '#606060')};
}}

/* Sliders */
QSlider::groove:horizontal {{
    border: 1px solid {colors.get('border', '#404040')};
    height: 8px;
    background-color: {colors.get('surface', '#1a1a1a')};
    border-radius: 4px;
}}

QSlider::handle:horizontal {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border: 1px solid {colors.get('accent_primary', '#00ff00')};
    width: 18px;
    margin: -2px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {colors.get('accent_secondary', '#00cc00')};
}}

/* Progress Bars */
QProgressBar {{
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    text-align: center;
    background-color: {colors.get('surface', '#1a1a1a')};
}}

QProgressBar::chunk {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    border-radius: 2px;
}}

/* Group Boxes */
QGroupBox {{
    font-weight: bold;
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    margin-top: 1ex;
    padding-top: 10px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px 0 5px;
    color: {colors.get('accent_primary', '#00ff00')};
}}

/* Tab Widgets */
QTabWidget::pane {{
    border: 2px solid {colors.get('border', '#404040')};
    background-color: {colors.get('surface', '#1a1a1a')};
}}

QTabBar::tab {{
    background-color: {colors.get('button_normal', '#404040')};
    color: {colors.get('text_primary', '#ffffff')};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}

QTabBar::tab:selected {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QTabBar::tab:hover {{
    background-color: {colors.get('button_hover', '#505050')};
}}

/* Table Widgets */
QTableWidget {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    gridline-color: {colors.get('border', '#404040')};
}}

QTableWidget::item {{
    padding: 4px;
}}

QTableWidget::item:selected {{
    background-color: {colors.get('accent_primary', '#00ff00')};
    color: {colors.get('background', '#0a0a0a')};
}}

QHeaderView::section {{
    background-color: {colors.get('button_normal', '#404040')};
    color: {colors.get('text_primary', '#ffffff')};
    padding: 4px;
    border: 1px solid {colors.get('border', '#404040')};
}}

QHeaderView::section:hover {{
    background-color: {colors.get('button_hover', '#505050')};
}}

/* Text Edits */
QTextEdit {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 4px;
}}

/* Tool Tips */
QToolTip {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
    padding: 4px;
}}

/* Status Bar */
QStatusBar {{
    background-color: {colors.get('surface', '#1a1a1a')};
    color: {colors.get('text_primary', '#ffffff')};
    border-top: 2px solid {colors.get('border', '#404040')};
}}

/* Custom Widgets */
QWidget#sidebar {{
    background-color: {colors.get('surface', '#1a1a1a')};
    border-right: 2px solid {colors.get('border', '#404040')};
}}

QWidget#content {{
    background-color: {colors.get('background', '#0a0a0a')};
}}

QWidget#device_list {{
    background-color: {colors.get('surface', '#1a1a1a')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
}}

QWidget#graph {{
    background-color: {colors.get('surface', '#1a1a1a')};
    border: 2px solid {colors.get('border', '#404040')};
    border-radius: 4px;
}}

/* Message Boxes */
QMessageBox {{
    background-color: {colors.get('background', '#0a0a0a')};
    color: {colors.get('text_primary', '#ffffff')};
}}

QMessageBox QPushButton {{
    min-width: 80px;
    min-height: 24px;
}}
"""
            return stylesheet
            
        except Exception as e:
            log_error(f"Error creating rainbow stylesheet: {e}")
            return ""
    
    def set_rainbow_speed(self, speed: float):
        """Set rainbow animation speed (degrees per frame)"""
        self.rainbow_speed = max(0.1, min(10.0, speed))
        log_info(f"Rainbow speed set to: {self.rainbow_speed}")
    
    def get_rainbow_speed(self) -> float:
        """Get current rainbow animation speed"""
        return self.rainbow_speed
    
    def is_rainbow_active(self) -> bool:
        """Check if rainbow mode is active"""
        return self.rainbow_timer is not None and self.rainbow_timer.isActive()
    
    def get_theme_info(self) -> Dict[str, str]:
        """Get information about the current theme"""
        return {
            "current_theme": self.current_theme,
            "available_themes": ", ".join(self.get_available_themes()),
            "rainbow_active": str(self.is_rainbow_active()),
            "rainbow_speed": str(self.get_rainbow_speed())
        }

# Global theme manager instance
theme_manager = ThemeManager() 
