#!/usr/bin/env python3
"""
Error Log Viewer for DupeZ
View and analyze comprehensive error logs
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path
from collections import Counter

def view_error_logs():
    """View and analyze error logs"""
    try:
        logs_dir = Path("logs")
        if not logs_dir.exists():
            print("❌ Logs directory not found!")
            return False
        
        print("📊 DupeZ Error Log Analysis")
        print("=" * 60)
        
        # List available log files
        log_files = list(logs_dir.glob("*.log"))
        if not log_files:
            print("❌ No log files found!")
            return False
        
        print(f"\n📁 Found {len(log_files)} log files:")
        for i, log_file in enumerate(log_files, 1):
            size_mb = log_file.stat().st_size / (1024 * 1024)
            print(f"{i}. {log_file.name} ({size_mb:.2f} MB)")
        
        # Analyze comprehensive errors log
        comprehensive_log = logs_dir / "comprehensive_errors.log"
        if comprehensive_log.exists():
            print(f"\n🔍 Analyzing {comprehensive_log.name}...")
            analyze_comprehensive_errors(comprehensive_log)
        
        # Analyze error summary
        summary_log = logs_dir / "error_summary.log"
        if summary_log.exists():
            print(f"\n📋 Analyzing {summary_log.name}...")
            analyze_error_summary(summary_log)
        
        # Analyze category-specific logs
        category_logs = list(logs_dir.glob("errors_*.log"))
        if category_logs:
            print(f"\n🏷️ Analyzing category-specific logs...")
            analyze_category_logs(category_logs)
        
        # Analyze critical errors
        critical_log = logs_dir / "critical_errors.log"
        if critical_log.exists():
            print(f"\n🚨 Analyzing {critical_log.name}...")
            analyze_critical_errors(critical_log)
        
        # Show recent errors from main log
        main_log = logs_dir / "dupez.log"
        if main_log.exists():
            print(f"\n📝 Recent errors from main log...")
            show_recent_errors(main_log)
        
        return True
        
    except Exception as e:
        print(f"❌ Error analyzing logs: {e}")
        return False

def analyze_comprehensive_errors(log_file: Path):
    """Analyze comprehensive errors log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count error records
        error_records = content.split("=" * 80)
        error_count = len([record for record in error_records if "ERROR RECORD" in record])
        
        print(f"   Total error records: {error_count}")
        
        # Parse JSON records
        json_records = []
        for record in error_records:
            if "ERROR RECORD" in record:
                try:
                    # Extract JSON part
                    lines = record.strip().split('\n')
                    for line in lines:
                        if line.strip().startswith('{'):
                            json_data = json.loads(line)
                            json_records.append(json_data)
                            break
                except:
                    continue
        
        if json_records:
            # Analyze categories
            categories = Counter([record.get('category', 'Unknown') for record in json_records])
            print(f"   Error categories:")
            for category, count in categories.most_common():
                print(f"     - {category}: {count}")
            
            # Analyze severities
            severities = Counter([record.get('severity', 'Unknown') for record in json_records])
            print(f"   Error severities:")
            for severity, count in severities.most_common():
                print(f"     - {severity}: {count}")
            
            # Show recent errors
            recent_errors = sorted(json_records, key=lambda x: x.get('timestamp', ''), reverse=True)[:5]
            print(f"   Recent errors:")
            for i, error in enumerate(recent_errors, 1):
                print(f"     {i}. {error.get('error_message', 'Unknown error')}")
                print(f"        Category: {error.get('category', 'Unknown')}")
                print(f"        Severity: {error.get('severity', 'Unknown')}")
        
    except Exception as e:
        print(f"   ❌ Error analyzing comprehensive errors: {e}")

def analyze_error_summary(log_file: Path):
    """Analyze error summary log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"   Summary content:")
        lines = content.strip().split('\n')
        for line in lines[:10]:  # Show first 10 lines
            if line.strip():
                print(f"     {line}")
        
        if len(lines) > 10:
            print(f"     ... and {len(lines) - 10} more lines")
        
    except Exception as e:
        print(f"   ❌ Error analyzing summary: {e}")

def analyze_category_logs(log_files: list):
    """Analyze category-specific log files"""
    for log_file in log_files:
        try:
            category = log_file.stem.replace('errors_', '')
            print(f"   📁 {category.upper()} errors:")
            
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            error_count = len([line for line in lines if 'ERROR' in line.upper()])
            print(f"     Total errors: {error_count}")
            
            # Show recent errors
            recent_errors = [line.strip() for line in lines if 'ERROR' in line.upper()][-3:]
            for error in recent_errors:
                print(f"     - {error}")
                
        except Exception as e:
            print(f"   ❌ Error analyzing {log_file.name}: {e}")

def analyze_critical_errors(log_file: Path):
    """Analyze critical errors log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count critical errors
        critical_count = content.count('CRITICAL')
        print(f"   Critical errors: {critical_count}")
        
        # Show recent critical errors
        lines = content.strip().split('\n')
        critical_lines = [line for line in lines if 'CRITICAL' in line.upper()]
        
        print(f"   Recent critical errors:")
        for line in critical_lines[-5:]:
            print(f"     - {line}")
        
    except Exception as e:
        print(f"   ❌ Error analyzing critical errors: {e}")

def show_recent_errors(log_file: Path):
    """Show recent errors from main log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Get recent error lines
        error_lines = [line.strip() for line in lines if 'ERROR' in line.upper()]
        
        print(f"   Recent errors from main log:")
        for line in error_lines[-10:]:  # Last 10 errors
            print(f"     - {line}")
        
    except Exception as e:
        print(f"   ❌ Error reading main log: {e}")

def show_error_statistics():
    """Show error statistics"""
    try:
        logs_dir = Path("logs")
        if not logs_dir.exists():
            print("❌ Logs directory not found!")
            return
        
        print("📊 Error Statistics")
        print("=" * 40)
        
        # Count total log files
        log_files = list(logs_dir.glob("*.log"))
        total_size = sum(f.stat().st_size for f in log_files)
        total_size_mb = total_size / (1024 * 1024)
        
        print(f"📁 Total log files: {len(log_files)}")
        print(f"📊 Total log size: {total_size_mb:.2f} MB")
        
        # Analyze by file type
        file_types = {}
        for log_file in log_files:
            file_type = log_file.stem
            if file_type not in file_types:
                file_types[file_type] = 0
            file_types[file_type] += 1
        
        print(f"📋 Log file types:")
        for file_type, count in file_types.items():
            print(f"   - {file_type}: {count} files")
        
    except Exception as e:
        print(f"❌ Error showing statistics: {e}")

def main():
    """Main function"""
    print("📊 DupeZ Error Log Viewer")
    print("=" * 40)
    print(f"📅 Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Show error statistics
    show_error_statistics()
    print()
    
    # View error logs
    if view_error_logs():
        print(f"\n✅ Error log analysis completed")
    else:
        print(f"\n❌ Error log analysis failed")
    
    print(f"\n📊 Error log viewer completed")

if __name__ == "__main__":
    main() 