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
            categories = Counter([record.get('category', 'unknown') for record in json_records])
            print(f"   Errors by category:")
            for category, count in categories.most_common():
                print(f"     {category}: {count}")
            
            # Analyze severity
            severities = Counter([record.get('severity', 'unknown') for record in json_records])
            print(f"   Errors by severity:")
            for severity, count in severities.most_common():
                print(f"     {severity}: {count}")
            
            # Show most recent errors
            print(f"   Most recent errors:")
            recent_records = sorted(json_records, key=lambda x: x.get('timestamp', ''), reverse=True)[:5]
            for i, record in enumerate(recent_records, 1):
                print(f"     {i}. {record.get('error_message', 'Unknown')}")
                print(f"        Category: {record.get('category', 'unknown')}")
                print(f"        Severity: {record.get('severity', 'unknown')}")
                print(f"        Module: {record.get('module', 'unknown')}")
                print(f"        Timestamp: {record.get('timestamp', 'unknown')}")
                print()
        
    except Exception as e:
        print(f"   ❌ Error analyzing comprehensive errors: {e}")

def analyze_error_summary(log_file: Path):
    """Analyze error summary log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find JSON summaries
        summaries = []
        lines = content.split('\n')
        for line in lines:
            if line.strip().startswith('{'):
                try:
                    summary = json.loads(line)
                    summaries.append(summary)
                except:
                    continue
        
        if summaries:
            latest_summary = summaries[-1]
            print(f"   Latest summary:")
            print(f"     Total errors: {latest_summary.get('total_errors', 0)}")
            print(f"     Session duration: {latest_summary.get('session_duration', 'unknown')}")
            
            errors_by_category = latest_summary.get('errors_by_category', {})
            if errors_by_category:
                print(f"     Errors by category:")
                for category, count in errors_by_category.items():
                    print(f"       {category}: {count}")
            
            errors_by_severity = latest_summary.get('errors_by_severity', {})
            if errors_by_severity:
                print(f"     Errors by severity:")
                for severity, count in errors_by_severity.items():
                    print(f"       {severity}: {count}")
        
    except Exception as e:
        print(f"   ❌ Error analyzing error summary: {e}")

def analyze_category_logs(log_files: list):
    """Analyze category-specific log files"""
    try:
        for log_file in log_files:
            category = log_file.stem.replace('errors_', '')
            print(f"   📁 {category}:")
            
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            error_count = len(lines)
            print(f"     Total errors: {error_count}")
            
            if error_count > 0:
                # Show recent errors
                recent_errors = lines[-5:] if len(lines) > 5 else lines
                print(f"     Recent errors:")
                for error in recent_errors:
                    print(f"       {error.strip()}")
                print()
        
    except Exception as e:
        print(f"   ❌ Error analyzing category logs: {e}")

def analyze_critical_errors(log_file: Path):
    """Analyze critical errors log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count critical errors
        error_sections = content.split("=" * 50)
        critical_count = len([section for section in error_sections if section.strip()])
        
        print(f"   Total critical errors: {critical_count}")
        
        if critical_count > 0:
            # Show recent critical errors
            recent_sections = error_sections[-3:] if len(error_sections) > 3 else error_sections
            print(f"   Recent critical errors:")
            for i, section in enumerate(recent_sections, 1):
                if section.strip():
                    lines = section.strip().split('\n')
                    if lines:
                        print(f"     {i}. {lines[0]}")
                        if len(lines) > 1:
                            print(f"        Stack trace available")
                    print()
        
    except Exception as e:
        print(f"   ❌ Error analyzing critical errors: {e}")

def show_recent_errors(log_file: Path):
    """Show recent errors from main log"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Find error lines
        error_lines = [line for line in lines if 'ERROR' in line]
        
        if error_lines:
            print(f"   Recent errors from main log:")
            recent_errors = error_lines[-10:] if len(error_lines) > 10 else error_lines
            for error in recent_errors:
                print(f"     {error.strip()}")
        else:
            print(f"   No errors found in main log")
        
    except Exception as e:
        print(f"   ❌ Error reading main log: {e}")

def show_error_statistics():
    """Show current error statistics"""
    try:
        from app.logs.error_tracker import get_error_stats, get_recent_errors
        
        print("\n📊 Current Error Statistics:")
        print("=" * 60)
        
        stats = get_error_stats()
        print(f"Total errors: {stats.get('total_errors', 0)}")
        print(f"Session duration: {stats.get('session_duration', 'unknown')}")
        
        errors_by_category = stats.get('errors_by_category', {})
        if errors_by_category:
            print(f"Errors by category:")
            for category, count in errors_by_category.items():
                print(f"  {category}: {count}")
        
        errors_by_severity = stats.get('errors_by_severity', {})
        if errors_by_severity:
            print(f"Errors by severity:")
            for severity, count in errors_by_severity.items():
                print(f"  {severity}: {count}")
        
        recent_errors = get_recent_errors(5)
        if recent_errors:
            print(f"\nRecent errors:")
            for i, error in enumerate(recent_errors, 1):
                print(f"  {i}. {error.get('error_message', 'Unknown')}")
                print(f"     Category: {error.get('category', 'unknown')}")
                print(f"     Severity: {error.get('severity', 'unknown')}")
                print(f"     Timestamp: {error.get('timestamp', 'unknown')}")
                print()
        
    except Exception as e:
        print(f"❌ Error getting statistics: {e}")

if __name__ == "__main__":
    print("🔍 DupeZ Error Log Viewer")
    print("=" * 60)
    
    # Show current statistics if available
    try:
        show_error_statistics()
    except:
        pass
    
    # Analyze log files
    success = view_error_logs()
    
    if success:
        print("\n✅ Error log analysis completed!")
    else:
        print("\n❌ Error log analysis failed!")
    
    sys.exit(0 if success else 1) 