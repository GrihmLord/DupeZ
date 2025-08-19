#!/usr/bin/env python3
"""
DayZ Tips and Tricks Dashboard
Comprehensive guide for DayZ gameplay optimization
"""

import sys
import os
import json
import webbrowser
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget,
    QGroupBox, QLabel, QPushButton, QLineEdit, QTextEdit, QTableWidget, 
    QTableWidgetItem, QProgressBar, QCheckBox, QSlider, QMessageBox,
    QInputDialog, QSplitter, QScrollArea, QFrame, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QThread, QUrl
from PyQt6.QtGui import QFont, QPalette, QColor, QPixmap, QIcon, QDesktopServices

from app.logs.logger import log_info, log_error, log_warning

class TipsTricksManager:
    """Manager for DayZ tips and tricks data"""
    
    def __init__(self):
        self.tips_data = self._load_tips_data()
        self.categories = self._get_categories()
        
    def _load_tips_data(self):
        """Load tips and tricks data from JSON file"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config", "dayz_tips_tricks.json")
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('tips_categories', {})
            else:
                # Fallback to hardcoded data if file not found
                return self._get_fallback_tips_data()
        except Exception as e:
            print(f"Error loading tips data: {e}")
            return self._get_fallback_tips_data()
    
    def _get_fallback_tips_data(self):
        """Fallback tips data if JSON file cannot be loaded"""
        return {
            "performance_optimization": {
                "title": "Performance Optimization",
                "description": "Optimize your system and DayZ for maximum performance",
                "tips": [
                    {
                        "title": "Graphics Settings Optimization",
                        "description": "Configure DayZ graphics for optimal performance",
                        "content": "🎮 **DayZ Graphics Settings for Maximum FPS:**\n\n**Essential Settings:**\n• Object Detail: Low/Medium (reduces CPU load)\n• Terrain Detail: Low (major FPS impact)\n• Shadow Quality: Low/Off (significant FPS boost)\n• Anti-Aliasing: Off (use GPU scaling instead)\n• Texture Quality: High (minimal FPS impact)\n• View Distance: 1500-2000m (balance performance/visibility)",
                        "difficulty": "Beginner",
                        "fps_boost": "40-60",
                        "category": "Graphics"
                    }
                ]
            },
            "game_mechanics": {
                "title": "Game Mechanics & Exploits",
                "description": "Understanding DayZ game mechanics and useful exploits",
                "tips": [
                    {
                        "title": "Inventory Exploits",
                        "description": "Useful inventory manipulation techniques",
                        "content": "🎒 **Inventory Exploitation Techniques:**\n\n**Quick Transfer Exploit:**\n• Hold Shift + Click to transfer items instantly\n• Use this to quickly move items between containers\n• Works with any inventory slot\n• Bypasses normal transfer animations",
                        "difficulty": "Intermediate",
                        "fps_boost": "0",
                        "category": "Inventory"
                    }
                ]
            }
        }
    
    def _get_categories(self):
        """Get all available categories"""
        return list(self.tips_data.keys())
    
    def get_category_tips(self, category):
        """Get tips for a specific category"""
        if category in self.tips_data:
            return self.tips_data[category]["tips"]
        return []
    
    def get_all_tips(self):
        """Get all tips from all categories"""
        all_tips = []
        for category in self.tips_data.values():
            all_tips.extend(category["tips"])
        return all_tips
    
    def search_tips(self, query):
        """Search tips by query"""
        query = query.lower()
        results = []
        
        for category in self.tips_data.values():
            for tip in category["tips"]:
                if (query in tip["title"].lower() or 
                    query in tip["description"].lower() or
                    query in tip["content"].lower() or
                    query in tip.get("category", "").lower() or
                    query in " ".join(tip.get("tags", [])).lower()):
                    results.append(tip)
        
        return results

class TipsTricksDashboard(QWidget):
    """DayZ Tips and Tricks Dashboard"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tips_manager = TipsTricksManager()
        
        self.setup_ui()
        self.setup_connections()
        self.apply_styling()
        
        # Load initial data
        self.load_category_tips("performance_optimization")
        
        log_info("DayZ Tips and Tricks Dashboard initialized")
    
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("💡 DayZ Tips & Tricks - Gameplay Optimization")
        self.setMinimumSize(1400, 900)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Header
        header_layout = self.create_header()
        main_layout.addLayout(header_layout)
        
        # Search bar
        search_layout = self.create_search_bar()
        main_layout.addLayout(search_layout)
        
        # Main content area
        content_layout = QHBoxLayout()
        
        # Left sidebar - Categories
        sidebar_layout = self.create_sidebar()
        content_layout.addLayout(sidebar_layout, 1)
        
        # Right content area
        content_area_layout = self.create_content_area()
        content_layout.addLayout(content_area_layout, 3)
        
        main_layout.addLayout(content_layout)
        
        # Status bar
        status_layout = self.create_status_bar()
        main_layout.addLayout(status_layout)
        
        self.setLayout(main_layout)
    
    def create_header(self):
        """Create the header section"""
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("💡 DayZ Tips & Tricks - Ultimate Gameplay Optimization Guide")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #FF6B35; margin: 10px;")
        
        # Quick actions
        quick_actions_layout = QHBoxLayout()
        
        self.export_tips_btn = QPushButton("📤 Export Tips")
        self.export_tips_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        self.help_btn = QPushButton("❓ Help")
        self.help_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        
        quick_actions_layout.addWidget(self.export_tips_btn)
        quick_actions_layout.addWidget(self.refresh_btn)
        quick_actions_layout.addWidget(self.help_btn)
        quick_actions_layout.addStretch()
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addLayout(quick_actions_layout)
        
        return header_layout
    
    def create_search_bar(self):
        """Create the search bar"""
        search_layout = QHBoxLayout()
        
        search_label = QLabel("🔍 Search Tips:")
        search_label.setStyleSheet("font-weight: bold; color: #333;")
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter keywords (e.g., 'FPS', 'Graphics', 'Network')...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 2px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #FF6B35;
            }
        """)
        
        self.search_btn = QPushButton("Search")
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B35;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E55A2B;
            }
        """)
        
        self.clear_search_btn = QPushButton("Clear")
        self.clear_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        search_layout.addWidget(self.clear_search_btn)
        search_layout.addStretch()
        
        return search_layout
    
    def create_sidebar(self):
        """Create the left sidebar with categories"""
        sidebar_layout = QVBoxLayout()
        
        # Categories header
        categories_label = QLabel("📚 Categories")
        categories_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #333;
            padding: 10px;
            background-color: #f0f0f0;
            border-radius: 4px;
        """)
        sidebar_layout.addWidget(categories_label)
        
        # Categories list
        self.categories_list = QListWidget()
        self.categories_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 2px solid #ddd;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #eee;
                font-weight: bold;
            }
            QListWidget::item:selected {
                background-color: #FF6B35;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #f0f0f0;
            }
        """)
        
        # Add categories
        for category_key, category_data in self.tips_manager.tips_data.items():
            item = QListWidgetItem(f"📁 {category_data['title']}")
            item.setData(Qt.ItemDataRole.UserRole, category_key)
            self.categories_list.addItem(item)
        
        sidebar_layout.addWidget(self.categories_list)
        
        # Category info
        self.category_info = QLabel()
        self.category_info.setStyleSheet("""
            padding: 10px;
            background-color: #f9f9f9;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-top: 10px;
        """)
        self.category_info.setWordWrap(True)
        sidebar_layout.addWidget(self.category_info)
        
        return sidebar_layout
    
    def create_content_area(self):
        """Create the main content area"""
        content_layout = QVBoxLayout()
        
        # Content header
        self.content_header = QLabel("Select a category to view tips")
        self.content_header.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #333;
            padding: 15px;
            background-color: #f0f0f0;
            border-radius: 4px;
            margin-bottom: 10px;
        """)
        content_layout.addWidget(self.content_header)
        
        # Tips display area
        self.tips_display = QTextEdit()
        self.tips_display.setReadOnly(True)
        self.tips_display.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 2px solid #ddd;
                border-radius: 4px;
                padding: 15px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                line-height: 1.4;
            }
        """)
        content_layout.addWidget(self.tips_display)
        
        # Tips navigation
        nav_layout = QHBoxLayout()
        
        self.prev_tip_btn = QPushButton("⬅️ Previous Tip")
        self.prev_tip_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        self.tip_counter = QLabel("Tip 0 of 0")
        self.tip_counter.setStyleSheet("""
            padding: 8px 16px;
            background-color: #f0f0f0;
            border-radius: 4px;
            font-weight: bold;
        """)
        
        self.next_tip_btn = QPushButton("Next Tip ➡️")
        self.next_tip_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        nav_layout.addWidget(self.prev_tip_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.tip_counter)
        nav_layout.addStretch()
        nav_layout.addWidget(self.next_tip_btn)
        
        content_layout.addLayout(nav_layout)
        
        return content_layout
    
    def create_status_bar(self):
        """Create the status bar"""
        status_layout = QHBoxLayout()
        
        # Status label
        self.status_label = QLabel("Ready - Select a category to view optimization tips")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        
        # Tips count
        self.total_tips_label = QLabel("Total Tips: 0")
        self.total_tips_label.setStyleSheet("color: #666; font-weight: bold;")
        
        # Last update
        self.last_update_label = QLabel("Last update: Never")
        self.last_update_label.setStyleSheet("color: #666; font-size: 10px;")
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.total_tips_label)
        status_layout.addWidget(self.last_update_label)
        
        return status_layout
    
    def setup_connections(self):
        """Setup signal connections"""
        # Category selection
        self.categories_list.currentItemChanged.connect(self.on_category_changed)
        
        # Search functionality
        self.search_btn.clicked.connect(self.search_tips)
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.search_input.returnPressed.connect(self.search_tips)
        
        # Navigation
        self.prev_tip_btn.clicked.connect(self.previous_tip)
        self.next_tip_btn.clicked.connect(self.next_tip)
        
        # Other buttons
        self.export_tips_btn.clicked.connect(self.export_tips)
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.help_btn.clicked.connect(self.show_help)
        
        # Initialize tip navigation
        self.current_category = None
        self.current_tips = []
        self.current_tip_index = 0
    
    def apply_styling(self):
        """Apply custom styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #ddd;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
    
    def on_category_changed(self, current, previous):
        """Handle category selection change"""
        if current:
            category_key = current.data(Qt.ItemDataRole.UserRole)
            self.load_category_tips(category_key)
    
    def load_category_tips(self, category_key):
        """Load tips for a specific category"""
        try:
            if category_key in self.tips_manager.tips_data:
                category_data = self.tips_manager.tips_data[category_key]
                self.current_category = category_key
                self.current_tips = category_data["tips"]
                self.current_tip_index = 0
                
                # Update UI
                self.content_header.setText(f"📚 {category_data['title']}")
                self.category_info.setText(category_data['description'])
                self.status_label.setText(f"Loaded {len(self.current_tips)} tips for {category_data['title']}")
                self.total_tips_label.setText(f"Total Tips: {len(self.current_tips)}")
                
                # Display first tip
                if self.current_tips:
                    self.display_current_tip()
                
                # Update navigation
                self.update_navigation_buttons()
                
        except Exception as e:
            log_error(f"Failed to load category tips: {e}")
            self.status_label.setText("Error loading tips")
    
    def display_current_tip(self):
        """Display the current tip"""
        if not self.current_tips or self.current_tip_index >= len(self.current_tips):
            return
        
        tip = self.current_tips[self.current_tip_index]
        
        # Format tip content with enhanced metadata
        content = f"""🎯 **{tip['title']}**
📝 {tip['description']}
⭐ Difficulty: {tip['difficulty']}
🚀 FPS Boost: {tip['fps_boost']}%
🏷️ Category: {tip.get('category', 'General')}"""
        
        # Add tags if available
        if tip.get('tags'):
            content += f"\n🏷️ Tags: {', '.join(tip['tags'])}"
        
        # Add estimated time if available
        if tip.get('estimated_time'):
            content += f"\n⏱️ Estimated Time: {tip['estimated_time']}"
        
        # Add risk level if available
        if tip.get('risk_level'):
            content += f"\n⚠️ Risk Level: {tip['risk_level']}"
        
        content += f"""

{tip['content']}

---
💡 Tip {self.current_tip_index + 1} of {len(self.current_tips)}
        """
        
        self.tips_display.setPlainText(content)
        self.tip_counter.setText(f"Tip {self.current_tip_index + 1} of {len(self.current_tips)}")
        
        # Update status
        self.status_label.setText(f"Displaying tip: {tip['title']}")
    
    def update_navigation_buttons(self):
        """Update navigation button states"""
        has_tips = len(self.current_tips) > 0
        
        self.prev_tip_btn.setEnabled(has_tips and self.current_tip_index > 0)
        self.next_tip_btn.setEnabled(has_tips and self.current_tip_index < len(self.current_tips) - 1)
    
    def previous_tip(self):
        """Go to previous tip"""
        if self.current_tip_index > 0:
            self.current_tip_index -= 1
            self.display_current_tip()
            self.update_navigation_buttons()
    
    def next_tip(self):
        """Go to next tip"""
        if self.current_tip_index < len(self.current_tips) - 1:
            self.current_tip_index += 1
            self.display_current_tip()
            self.update_navigation_buttons()
    
    def search_tips(self):
        """Search tips by query"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.information(self, "Search", "Please enter a search term")
            return
        
        try:
            results = self.tips_manager.search_tips(query)
            
            if results:
                # Display search results
                self.current_tips = results
                self.current_tip_index = 0
                self.current_category = "search_results"
                
                # Update UI
                self.content_header.setText(f"🔍 Search Results for: '{query}'")
                self.category_info.setText(f"Found {len(results)} matching tips")
                self.status_label.setText(f"Search results: {len(results)} tips found")
                self.total_tips_label.setText(f"Search Results: {len(results)}")
                
                # Display first result
                self.display_current_tip()
                self.update_navigation_buttons()
                
            else:
                QMessageBox.information(self, "Search Results", f"No tips found for: '{query}'")
                
        except Exception as e:
            log_error(f"Search failed: {e}")
            QMessageBox.critical(self, "Error", f"Search failed: {e}")
    
    def clear_search(self):
        """Clear search and return to category view"""
        self.search_input.clear()
        
        if self.current_category and self.current_category != "search_results":
            self.load_category_tips(self.current_category)
        else:
            # Return to first category
            first_category = list(self.tips_manager.tips_data.keys())[0]
            self.load_category_tips(first_category)
            self.categories_list.setCurrentRow(0)
    
    def export_tips(self):
        """Export tips to a file"""
        try:
            # Get current tips
            if not self.current_tips:
                QMessageBox.information(self, "Export", "No tips to export")
                return
            
            # Create export content
            export_content = f"DayZ Tips & Tricks Export\n"
            export_content += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            export_content += f"Category: {self.current_category}\n"
            export_content += f"Total Tips: {len(self.current_tips)}\n\n"
            
            for i, tip in enumerate(self.current_tips, 1):
                export_content += f"=== Tip {i}: {tip['title']} ===\n"
                export_content += f"Description: {tip['description']}\n"
                export_content += f"Difficulty: {tip['difficulty']}\n"
                export_content += f"FPS Boost: {tip['fps_boost']}%\n"
                export_content += f"Category: {tip.get('category', 'General')}\n"
                
                # Add new metadata fields
                if tip.get('tags'):
                    export_content += f"Tags: {', '.join(tip['tags'])}\n"
                if tip.get('estimated_time'):
                    export_content += f"Estimated Time: {tip['estimated_time']}\n"
                if tip.get('risk_level'):
                    export_content += f"Risk Level: {tip['risk_level']}\n"
                
                export_content += f"\n{tip['content']}\n\n"
                export_content += "-" * 50 + "\n\n"
            
            # Save to file
            filename = f"dayz_tips_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(export_content)
            
            QMessageBox.information(self, "Export Success", f"Tips exported to: {filename}")
            self.status_label.setText(f"Tips exported to: {filename}")
            
        except Exception as e:
            log_error(f"Export failed: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export tips: {e}")
    
    def refresh_data(self):
        """Refresh the tips data"""
        try:
            # Reload tips manager
            self.tips_manager = TipsTricksManager()
            
            # Refresh current view
            if self.current_category:
                self.load_category_tips(self.current_category)
            
            self.status_label.setText("Tips data refreshed")
            self.last_update_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            log_error(f"Refresh failed: {e}")
            self.status_label.setText("Refresh failed")
    
    def show_help(self):
        """Show help information"""
        help_text = """
💡 **DayZ Tips & Tricks Dashboard Help**

**How to Use:**
1. Select a category from the left sidebar
2. Browse through tips using Previous/Next buttons
3. Use the search bar to find specific tips
4. Export tips for offline reference

**Categories:**
• Performance Optimization - System and graphics settings
• Gameplay Strategies - Combat and survival techniques
• Advanced Techniques - Expert-level optimizations
• Server Optimization - Connection and server settings

**Tips Include:**
• Detailed step-by-step instructions
• Expected performance improvements
• Difficulty levels and requirements
• Category classifications

**Navigation:**
• Use Previous/Next buttons to browse tips
• Search for specific keywords
• Export tips for offline use
• Refresh data for updates

For more help, visit the DayZ community forums!
        """
        
        QMessageBox.information(self, "Help - DayZ Tips & Tricks", help_text)
    
    def closeEvent(self, event):
        """Handle application close event"""
        try:
            log_info("DayZ Tips and Tricks Dashboard closed")
            event.accept()
        except Exception as e:
            log_error(f"Error during close: {e}")
            event.accept()
