#!/usr/bin/env python3
"""
Theme Selector GUI Component
Provides a user interface for switching between different themes
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QSlider, QGroupBox,
                             QMessageBox, QFrame, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette

from app.themes.theme_manager import theme_manager
from app.logs.logger import log_info, log_error

class ThemeSelector(QWidget):
    """Theme selector widget for switching between themes"""
    
    # Signals
    theme_changed = pyqtSignal(str)  # Emit theme name when changed
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.connect_signals()
        self.update_ui()
        
    def setup_ui(self):
        """Setup the theme selector UI"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title
        title = QLabel("🎨 Theme Selector")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Theme selection group
        theme_group = QGroupBox("Select Theme")
        theme_layout = QVBoxLayout()
        theme_group.setLayout(theme_layout)
        
        # Theme combo box
        theme_layout.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(theme_manager.get_available_themes())
        theme_layout.addWidget(self.theme_combo)
        
        # Apply theme button
        self.apply_theme_btn = QPushButton("Apply Theme")
        self.apply_theme_btn.setObjectName("refresh_btn")
        theme_layout.addWidget(self.apply_theme_btn)
        
        layout.addWidget(theme_group)
        
        # Rainbow controls group
        rainbow_group = QGroupBox("🌈 Rainbow Mode")
        rainbow_layout = QVBoxLayout()
        rainbow_group.setLayout(rainbow_layout)
        
        # Rainbow speed slider
        rainbow_layout.addWidget(QLabel("Animation Speed:"))
        self.rainbow_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.rainbow_speed_slider.setRange(1, 100)
        self.rainbow_speed_slider.setValue(20)  # Default speed
        self.rainbow_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.rainbow_speed_slider.setTickInterval(10)
        rainbow_layout.addWidget(self.rainbow_speed_slider)
        
        # Speed label
        self.speed_label = QLabel("Speed: 2.0°/frame")
        rainbow_layout.addWidget(self.speed_label)
        
        # Rainbow control buttons
        rainbow_btn_layout = QHBoxLayout()
        
        self.start_rainbow_btn = QPushButton("Start Rainbow")
        self.start_rainbow_btn.setObjectName("smart_mode_btn")
        rainbow_btn_layout.addWidget(self.start_rainbow_btn)
        
        self.stop_rainbow_btn = QPushButton("Stop Rainbow")
        self.stop_rainbow_btn.setObjectName("block_btn")
        rainbow_btn_layout.addWidget(self.stop_rainbow_btn)
        
        rainbow_layout.addLayout(rainbow_btn_layout)
        
        layout.addWidget(rainbow_group)
        
        # Theme info group
        info_group = QGroupBox("ℹ️ Theme Information")
        info_layout = QVBoxLayout()
        info_group.setLayout(info_layout)
        
        self.theme_info_label = QLabel("Current theme: Dark")
        self.theme_info_label.setWordWrap(True)
        info_layout.addWidget(self.theme_info_label)
        
        layout.addWidget(info_group)
        
        # Quick theme buttons
        quick_group = QGroupBox("⚡ Quick Themes")
        quick_layout = QHBoxLayout()
        quick_group.setLayout(quick_layout)
        
        self.light_btn = QPushButton("☀️ Light")
        self.light_btn.setObjectName("refresh_btn")
        quick_layout.addWidget(self.light_btn)
        
        self.dark_btn = QPushButton("🌙 Dark")
        self.dark_btn.setObjectName("block_btn")
        quick_layout.addWidget(self.dark_btn)
        
        self.hacker_btn = QPushButton("💻 Hacker")
        self.hacker_btn.setObjectName("smart_mode_btn")
        quick_layout.addWidget(self.hacker_btn)
        
        self.rainbow_btn = QPushButton("🌈 Rainbow")
        self.rainbow_btn.setObjectName("refresh_btn")
        quick_layout.addWidget(self.rainbow_btn)
        
        layout.addWidget(quick_group)
        
        # Status frame
        self.status_frame = QFrame()
        self.status_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        self.status_frame.setMaximumHeight(60)
        status_layout = QVBoxLayout()
        self.status_frame.setLayout(status_layout)
        
        self.status_label = QLabel("Ready to change themes")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.status_label)
        
        layout.addWidget(self.status_frame)
        
    def connect_signals(self):
        """Connect UI signals"""
        # Theme combo
        self.theme_combo.currentTextChanged.connect(self.on_theme_selected)
        self.apply_theme_btn.clicked.connect(self.apply_selected_theme)
        
        # Rainbow controls
        self.rainbow_speed_slider.valueChanged.connect(self.on_speed_changed)
        self.start_rainbow_btn.clicked.connect(self.start_rainbow_mode)
        self.stop_rainbow_btn.clicked.connect(self.stop_rainbow_mode)
        
        # Quick theme buttons
        self.light_btn.clicked.connect(lambda: self.apply_theme("light"))
        self.dark_btn.clicked.connect(lambda: self.apply_theme("dark"))
        self.hacker_btn.clicked.connect(lambda: self.apply_theme("hacker"))
        self.rainbow_btn.clicked.connect(self.start_rainbow_mode)
        
        # Theme manager signals
        theme_manager.theme_changed.connect(self.on_theme_manager_changed)
        theme_manager.color_updated.connect(self.on_color_updated)
        
    def update_ui(self):
        """Update UI elements based on current state"""
        try:
            # Update theme combo
            current_theme = theme_manager.get_current_theme()
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
            
            # Update rainbow controls
            rainbow_active = theme_manager.is_rainbow_active()
            self.start_rainbow_btn.setEnabled(not rainbow_active)
            self.stop_rainbow_btn.setEnabled(rainbow_active)
            
            # Update speed slider
            speed = theme_manager.get_rainbow_speed()
            slider_value = int(speed * 10)  # Convert to slider range
            self.rainbow_speed_slider.setValue(slider_value)
            
            # Update theme info
            self.update_theme_info()
            
            # Update status
            if rainbow_active:
                self.status_label.setText("🌈 Rainbow mode active")
                self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
            else:
                self.status_label.setText(f"Current theme: {current_theme.title()}")
                self.status_label.setStyleSheet("color: #ffffff;")
                
        except Exception as e:
            log_error(f"Error updating theme selector UI: {e}")
    
    def on_theme_selected(self, theme_name: str):
        """Handle theme selection from combo box"""
        try:
            log_info(f"Theme selected: {theme_name}")
            self.status_label.setText(f"Theme selected: {theme_name}")
            
        except Exception as e:
            log_error(f"Error handling theme selection: {e}")
    
    def apply_selected_theme(self):
        """Apply the currently selected theme"""
        try:
            theme_name = self.theme_combo.currentText()
            success = self.apply_theme(theme_name)
            
            if success:
                self.status_label.setText(f"✅ Applied theme: {theme_name}")
                self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
            else:
                self.status_label.setText(f"❌ Failed to apply theme: {theme_name}")
                self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error applying selected theme: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;")
    
    def apply_theme(self, theme_name: str) -> bool:
        """Apply a specific theme"""
        try:
            success = theme_manager.apply_theme(theme_name)
            if success:
                self.theme_changed.emit(theme_name)
                log_info(f"Applied theme: {theme_name}")
            return success
            
        except Exception as e:
            log_error(f"Error applying theme {theme_name}: {e}")
            return False
    
    def on_speed_changed(self, value: int):
        """Handle rainbow speed slider change"""
        try:
            speed = value / 10.0  # Convert slider value to speed
            theme_manager.set_rainbow_speed(speed)
            self.speed_label.setText(f"Speed: {speed:.1f}°/frame")
            
        except Exception as e:
            log_error(f"Error changing rainbow speed: {e}")
    
    def start_rainbow_mode(self):
        """Start rainbow mode"""
        try:
            # Set speed from slider
            speed = self.rainbow_speed_slider.value() / 10.0
            theme_manager.set_rainbow_speed(speed)
            
            # Start rainbow mode
            theme_manager.start_rainbow_mode()
            
            self.status_label.setText("🌈 Rainbow mode started!")
            self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
            
            log_info("Rainbow mode started")
            
        except Exception as e:
            log_error(f"Error starting rainbow mode: {e}")
            self.status_label.setText(f"❌ Error starting rainbow mode: {e}")
            self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;")
    
    def stop_rainbow_mode(self):
        """Stop rainbow mode"""
        try:
            theme_manager.stop_rainbow_mode()
            
            self.status_label.setText("🛑 Rainbow mode stopped")
            self.status_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
            
            log_info("Rainbow mode stopped")
            
        except Exception as e:
            log_error(f"Error stopping rainbow mode: {e}")
            self.status_label.setText(f"❌ Error stopping rainbow mode: {e}")
            self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;")
    
    def on_theme_manager_changed(self, theme_name: str):
        """Handle theme change from theme manager"""
        try:
            self.update_ui()
            log_info(f"Theme changed to: {theme_name}")
            
        except Exception as e:
            log_error(f"Error handling theme manager change: {e}")
    
    def on_color_updated(self, color_name: str, color_value: str):
        """Handle color updates from rainbow mode"""
        try:
            # Update status with color info (optional)
            if theme_manager.is_rainbow_active():
                self.status_label.setText(f"🌈 Rainbow: {color_name} = {color_value}")
                
        except Exception as e:
            log_error(f"Error handling color update: {e}")
    
    def update_theme_info(self):
        """Update theme information display"""
        try:
            info = theme_manager.get_theme_info()
            info_text = f"""
Current Theme: {info['current_theme'].title()}
Available Themes: {info['available_themes']}
Rainbow Active: {info['rainbow_active']}
Rainbow Speed: {info['rainbow_speed']}°/frame
            """.strip()
            
            self.theme_info_label.setText(info_text)
            
        except Exception as e:
            log_error(f"Error updating theme info: {e}")
    
    def show_theme_preview(self, theme_name: str):
        """Show a preview of the selected theme"""
        try:
            # Create a preview dialog
            preview_text = f"""
Theme Preview: {theme_name.title()}

This theme will apply:
• Background colors
• Text colors  
• Button styles
• Border colors
• Accent colors

Click "Apply Theme" to activate.
            """.strip()
            
            QMessageBox.information(
                self, 
                f"Theme Preview - {theme_name.title()}", 
                preview_text
            )
            
        except Exception as e:
            log_error(f"Error showing theme preview: {e}")
    
    def get_current_theme_info(self) -> dict:
        """Get current theme information"""
        try:
            return theme_manager.get_theme_info()
        except Exception as e:
            log_error(f"Error getting theme info: {e}")
            return {}
    
    def reset_to_default(self):
        """Reset to default dark theme"""
        try:
            success = self.apply_theme("dark")
            if success:
                self.status_label.setText("✅ Reset to default dark theme")
                self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to reset theme")
                self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error resetting theme: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #ff0000; font-weight: bold;") 