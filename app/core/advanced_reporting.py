# app/core/advanced_reporting.py

import json
import csv
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import base64

from app.logs.logger import log_info, log_error, log_warning
from app.core.advanced_traffic_analyzer import advanced_traffic_analyzer

@dataclass
class ReportConfig:
    """Configuration for report generation"""
    report_type: str  # network, security, performance, comprehensive
    time_range: str  # last_hour, last_day, last_week, last_month, custom
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    include_charts: bool = True
    include_details: bool = True
    export_format: str = "html"  # html, pdf, json, csv
    output_path: Optional[str] = None

@dataclass
class ReportData:
    """Data structure for report information"""
    title: str
    generated_at: datetime = field(default_factory=datetime.now)
    time_range: str = ""
    summary: Dict[str, Any] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

class AdvancedReportingSystem:
    """Advanced reporting system for comprehensive network analysis"""
    
    def __init__(self):
        self.reports_dir = Path("app/reports")
        self.reports_dir.mkdir(exist_ok=True)
        self.templates_dir = Path("app/templates/reports")
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database for report storage
        self.db_path = self.reports_dir / "reports.db"
        self._init_report_database()
    
    def _init_report_database(self):
        """Initialize the reports database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    title TEXT,
                    report_type TEXT,
                    generated_at TIMESTAMP,
                    config TEXT,
                    data TEXT,
                    file_path TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS report_metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT,
                    metric_name TEXT,
                    metric_value REAL,
                    timestamp TIMESTAMP,
                    FOREIGN KEY (report_id) REFERENCES reports (report_id)
                )
            ''')
            
            conn.commit()
            conn.close()
            log_info("Reports database initialized")
            
        except Exception as e:
            log_error(f"Failed to initialize reports database: {e}")
    
    def generate_report(self, config: ReportConfig) -> ReportData:
        """Generate a comprehensive report based on configuration"""
        try:
            # Determine time range
            start_time, end_time = self._get_time_range(config)
            
            # Generate report data based on type
            if config.report_type == "network":
                report_data = self._generate_network_report(start_time, end_time)
            elif config.report_type == "security":
                report_data = self._generate_security_report(start_time, end_time)
            elif config.report_type == "performance":
                report_data = self._generate_performance_report(start_time, end_time)
            elif config.report_type == "comprehensive":
                report_data = self._generate_comprehensive_report(start_time, end_time)
            else:
                raise ValueError(f"Unknown report type: {config.report_type}")
            
            # Add charts if requested
            if config.include_charts:
                report_data.charts = self._generate_charts(report_data, start_time, end_time)
            
            # Generate recommendations
            report_data.recommendations = self._generate_recommendations(report_data)
            
            # Save report
            self._save_report(report_data, config)
            
            log_info(f"Generated {config.report_type} report")
            return report_data
            
        except Exception as e:
            log_error(f"Error generating report: {e}")
            return ReportData(title="Error Report")
    
    def _get_time_range(self, config: ReportConfig) -> tuple[datetime, datetime]:
        """Get the time range for the report"""
        end_time = datetime.now()
        
        if config.start_time and config.end_time:
            return config.start_time, config.end_time
        
        if config.time_range == "last_hour":
            start_time = end_time - timedelta(hours=1)
        elif config.time_range == "last_day":
            start_time = end_time - timedelta(days=1)
        elif config.time_range == "last_week":
            start_time = end_time - timedelta(weeks=1)
        elif config.time_range == "last_month":
            start_time = end_time - timedelta(days=30)
        else:
            start_time = end_time - timedelta(days=1)  # Default to last day
        
        return start_time, end_time
    
    def _generate_network_report(self, start_time: datetime, end_time: datetime) -> ReportData:
        """Generate network analysis report"""
        try:
            # Get traffic analysis data
            summary = advanced_traffic_analyzer.get_analysis_summary()
            recent_events = advanced_traffic_analyzer.get_recent_events(100)
            
            # Filter events by time range
            filtered_events = [
                event for event in recent_events
                if start_time <= event['timestamp'] <= end_time
            ]
            
            # Calculate network metrics
            total_flows = summary.get('total_flows', 0)
            active_flows = summary.get('active_flows', 0)
            total_bytes = summary.get('total_bytes_analyzed', 0)
            total_packets = summary.get('total_packets_analyzed', 0)
            
            # Analyze event types
            event_types = {}
            for event in filtered_events:
                event_type = event.get('event_type', 'unknown')
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            # Create report data
            report_data = ReportData(
                title="Network Analysis Report",
                time_range=f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}",
                summary={
                    'total_flows': total_flows,
                    'active_flows': active_flows,
                    'total_bytes_analyzed': total_bytes,
                    'total_packets_analyzed': total_packets,
                    'events_analyzed': len(filtered_events),
                    'event_types': event_types,
                    'analysis_runtime': summary.get('runtime_seconds', 0)
                },
                details=filtered_events
            )
            
            return report_data
            
        except Exception as e:
            log_error(f"Error generating network report: {e}")
            return ReportData(title="Network Analysis Report")
    
    def _generate_security_report(self, start_time: datetime, end_time: datetime) -> ReportData:
        """Generate security analysis report"""
        try:
            # Get security-related events
            recent_events = advanced_traffic_analyzer.get_recent_events(200)
            
            # Filter security events
            security_events = [
                event for event in recent_events
                if start_time <= event['timestamp'] <= end_time and
                event.get('severity') in ['high', 'critical']
            ]
            
            # Analyze threat patterns
            threat_types = {}
            blocked_ips = set()
            suspicious_activities = []
            
            for event in security_events:
                event_type = event.get('event_type', 'unknown')
                threat_types[event_type] = threat_types.get(event_type, 0) + 1
                
                # Extract IP addresses from flow_id
                flow_id = event.get('flow_id', '')
                if ':' in flow_id:
                    ip = flow_id.split(':')[0]
                    blocked_ips.add(ip)
                
                if event.get('severity') == 'critical':
                    suspicious_activities.append(event)
            
            # Calculate security metrics
            total_threats = len(security_events)
            critical_threats = len([e for e in security_events if e.get('severity') == 'critical'])
            unique_ips_blocked = len(blocked_ips)
            
            report_data = ReportData(
                title="Security Analysis Report",
                time_range=f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}",
                summary={
                    'total_threats': total_threats,
                    'critical_threats': critical_threats,
                    'unique_ips_blocked': unique_ips_blocked,
                    'threat_types': threat_types,
                    'blocked_ips': list(blocked_ips),
                    'suspicious_activities': len(suspicious_activities)
                },
                details=security_events
            )
            
            return report_data
            
        except Exception as e:
            log_error(f"Error generating security report: {e}")
            return ReportData(title="Security Analysis Report")
    
    def _generate_performance_report(self, start_time: datetime, end_time: datetime) -> ReportData:
        """Generate performance analysis report"""
        try:
            # Get performance metrics
            summary = advanced_traffic_analyzer.get_analysis_summary()
            
            # Calculate performance metrics
            runtime_seconds = summary.get('runtime_seconds', 0)
            total_bytes = summary.get('total_bytes_analyzed', 0)
            total_packets = summary.get('total_packets_analyzed', 0)
            
            # Calculate throughput
            if runtime_seconds > 0:
                bytes_per_second = total_bytes / runtime_seconds
                packets_per_second = total_packets / runtime_seconds
            else:
                bytes_per_second = 0
                packets_per_second = 0
            
            # Memory usage (simulated)
            memory_usage = 150  # MB
            cpu_usage = 25  # Percentage
            
            report_data = ReportData(
                title="Performance Analysis Report",
                time_range=f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}",
                summary={
                    'runtime_seconds': runtime_seconds,
                    'total_bytes_analyzed': total_bytes,
                    'total_packets_analyzed': total_packets,
                    'bytes_per_second': bytes_per_second,
                    'packets_per_second': packets_per_second,
                    'memory_usage_mb': memory_usage,
                    'cpu_usage_percent': cpu_usage,
                    'active_flows': summary.get('active_flows', 0),
                    'threat_indicators': summary.get('threat_indicators', 0)
                },
                details=[]
            )
            
            return report_data
            
        except Exception as e:
            log_error(f"Error generating performance report: {e}")
            return ReportData(title="Performance Analysis Report")
    
    def _generate_comprehensive_report(self, start_time: datetime, end_time: datetime) -> ReportData:
        """Generate comprehensive analysis report"""
        try:
            # Combine all report types
            network_data = self._generate_network_report(start_time, end_time)
            security_data = self._generate_security_report(start_time, end_time)
            performance_data = self._generate_performance_report(start_time, end_time)
            
            # Merge summaries
            comprehensive_summary = {
                'network': network_data.summary,
                'security': security_data.summary,
                'performance': performance_data.summary,
                'report_generated_at': datetime.now().isoformat(),
                'time_range': f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}"
            }
            
            # Combine details
            all_details = network_data.details + security_data.details + performance_data.details
            
            report_data = ReportData(
                title="Comprehensive Analysis Report",
                time_range=f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}",
                summary=comprehensive_summary,
                details=all_details
            )
            
            return report_data
            
        except Exception as e:
            log_error(f"Error generating comprehensive report: {e}")
            return ReportData(title="Comprehensive Analysis Report")
    
    def _generate_charts(self, report_data: ReportData, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Generate charts for the report"""
        try:
            charts = []
            
            # Traffic over time chart
            if 'network' in report_data.summary:
                traffic_chart = self._create_traffic_chart(start_time, end_time)
                charts.append({
                    'title': 'Network Traffic Over Time',
                    'type': 'line',
                    'data': traffic_chart
                })
            
            # Event distribution chart
            if report_data.details:
                event_chart = self._create_event_distribution_chart(report_data.details)
                charts.append({
                    'title': 'Event Distribution',
                    'type': 'pie',
                    'data': event_chart
                })
            
            # Performance metrics chart
            if 'performance' in report_data.summary:
                perf_chart = self._create_performance_chart(report_data.summary['performance'])
                charts.append({
                    'title': 'Performance Metrics',
                    'type': 'bar',
                    'data': perf_chart
                })
            
            return charts
            
        except Exception as e:
            log_error(f"Error generating charts: {e}")
            return []
    
    def _create_traffic_chart(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Create traffic over time chart"""
        try:
            # Simulate traffic data points
            import random
            data_points = []
            current_time = start_time
            
            while current_time <= end_time:
                data_points.append({
                    'timestamp': current_time.isoformat(),
                    'bytes': random.randint(1000, 10000),
                    'packets': random.randint(10, 100)
                })
                current_time += timedelta(minutes=5)
            
            return {
                'labels': [point['timestamp'] for point in data_points],
                'datasets': [
                    {
                        'label': 'Bytes',
                        'data': [point['bytes'] for point in data_points],
                        'borderColor': 'rgb(75, 192, 192)',
                        'backgroundColor': 'rgba(75, 192, 192, 0.2)'
                    },
                    {
                        'label': 'Packets',
                        'data': [point['packets'] for point in data_points],
                        'borderColor': 'rgb(255, 99, 132)',
                        'backgroundColor': 'rgba(255, 99, 132, 0.2)'
                    }
                ]
            }
            
        except Exception as e:
            log_error(f"Error creating traffic chart: {e}")
            return {}
    
    def _create_event_distribution_chart(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create event distribution chart"""
        try:
            event_types = {}
            for event in events:
                event_type = event.get('event_type', 'unknown')
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            return {
                'labels': list(event_types.keys()),
                'datasets': [{
                    'data': list(event_types.values()),
                    'backgroundColor': [
                        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
                        '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
                    ]
                }]
            }
            
        except Exception as e:
            log_error(f"Error creating event distribution chart: {e}")
            return {}
    
    def _create_performance_chart(self, perf_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create performance metrics chart"""
        try:
            metrics = ['bytes_per_second', 'packets_per_second', 'memory_usage_mb', 'cpu_usage_percent']
            values = [perf_data.get(metric, 0) for metric in metrics]
            
            return {
                'labels': ['Bytes/sec', 'Packets/sec', 'Memory (MB)', 'CPU (%)'],
                'datasets': [{
                    'label': 'Performance Metrics',
                    'data': values,
                    'backgroundColor': 'rgba(54, 162, 235, 0.2)',
                    'borderColor': 'rgb(54, 162, 235)',
                    'borderWidth': 1
                }]
            }
            
        except Exception as e:
            log_error(f"Error creating performance chart: {e}")
            return {}
    
    def _generate_recommendations(self, report_data: ReportData) -> List[str]:
        """Generate recommendations based on report data"""
        try:
            recommendations = []
            
            # Network recommendations
            if 'network' in report_data.summary:
                network_summary = report_data.summary['network']
                
                if network_summary.get('total_flows', 0) > 1000:
                    recommendations.append("Consider implementing traffic filtering to reduce the number of active flows")
                
                if network_summary.get('total_bytes_analyzed', 0) > 1000000000:  # 1GB
                    recommendations.append("High traffic volume detected - consider bandwidth optimization")
            
            # Security recommendations
            if 'security' in report_data.summary:
                security_summary = report_data.summary['security']
                
                if security_summary.get('critical_threats', 0) > 0:
                    recommendations.append("Critical threats detected - review security policies immediately")
                
                if security_summary.get('unique_ips_blocked', 0) > 10:
                    recommendations.append("Multiple IPs blocked - consider implementing stricter access controls")
            
            # Performance recommendations
            if 'performance' in report_data.summary:
                perf_summary = report_data.summary['performance']
                
                if perf_summary.get('memory_usage_mb', 0) > 200:
                    recommendations.append("High memory usage - consider optimizing resource allocation")
                
                if perf_summary.get('cpu_usage_percent', 0) > 80:
                    recommendations.append("High CPU usage - consider load balancing or hardware upgrade")
            
            # General recommendations
            if len(report_data.details) > 1000:
                recommendations.append("Large number of events - consider implementing event filtering")
            
            if not recommendations:
                recommendations.append("System appears to be operating within normal parameters")
            
            return recommendations
            
        except Exception as e:
            log_error(f"Error generating recommendations: {e}")
            return ["Unable to generate recommendations due to error"]
    
    def _save_report(self, report_data: ReportData, config: ReportConfig):
        """Save the report to database and file"""
        try:
            report_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Save to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO reports (report_id, title, report_type, generated_at, config, data, file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                report_id,
                report_data.title,
                config.report_type,
                report_data.generated_at,
                json.dumps(config.__dict__),
                json.dumps(report_data.__dict__, default=str),
                config.output_path or f"report_{report_id}.{config.export_format}"
            ))
            
            conn.commit()
            conn.close()
            
            # Export report
            if config.output_path:
                self._export_report(report_data, config)
            
            log_info(f"Saved report: {report_id}")
            
        except Exception as e:
            log_error(f"Error saving report: {e}")
    
    def _export_report(self, report_data: ReportData, config: ReportConfig):
        """Export report in specified format"""
        try:
            if config.export_format == "html":
                self._export_html_report(report_data, config.output_path)
            elif config.export_format == "json":
                self._export_json_report(report_data, config.output_path)
            elif config.export_format == "csv":
                self._export_csv_report(report_data, config.output_path)
            else:
                log_error(f"Unsupported export format: {config.export_format}")
                
        except Exception as e:
            log_error(f"Error exporting report: {e}")
    
    def _export_html_report(self, report_data: ReportData, output_path: str):
        """Export report as HTML"""
        try:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{report_data.title}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                    .summary {{ margin: 20px 0; }}
                    .details {{ margin: 20px 0; }}
                    .recommendations {{ background-color: #fff3cd; padding: 15px; border-radius: 5px; }}
                    table {{ border-collapse: collapse; width: 100%; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>{report_data.title}</h1>
                    <p>Generated: {report_data.generated_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Time Range: {report_data.time_range}</p>
                </div>
                
                <div class="summary">
                    <h2>Summary</h2>
                    <pre>{json.dumps(report_data.summary, indent=2)}</pre>
                </div>
                
                <div class="details">
                    <h2>Details</h2>
                    <table>
                        <tr><th>Event Type</th><th>Severity</th><th>Description</th><th>Timestamp</th></tr>
                        {''.join(f"<tr><td>{event.get('event_type', 'N/A')}</td><td>{event.get('severity', 'N/A')}</td><td>{event.get('description', 'N/A')}</td><td>{event.get('timestamp', 'N/A')}</td></tr>" for event in report_data.details[:50])}
                    </table>
                </div>
                
                <div class="recommendations">
                    <h2>Recommendations</h2>
                    <ul>
                        {''.join(f"<li>{rec}</li>" for rec in report_data.recommendations)}
                    </ul>
                </div>
            </body>
            </html>
            """
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            log_info(f"Exported HTML report: {output_path}")
            
        except Exception as e:
            log_error(f"Error exporting HTML report: {e}")
    
    def _export_json_report(self, report_data: ReportData, output_path: str):
        """Export report as JSON"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report_data.__dict__, f, indent=2, default=str)
            
            log_info(f"Exported JSON report: {output_path}")
            
        except Exception as e:
            log_error(f"Error exporting JSON report: {e}")
    
    def _export_csv_report(self, report_data: ReportData, output_path: str):
        """Export report as CSV"""
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write summary
                writer.writerow(['Summary'])
                for key, value in report_data.summary.items():
                    writer.writerow([key, value])
                
                writer.writerow([])
                writer.writerow(['Details'])
                writer.writerow(['Event Type', 'Severity', 'Description', 'Timestamp'])
                
                for event in report_data.details:
                    writer.writerow([
                        event.get('event_type', 'N/A'),
                        event.get('severity', 'N/A'),
                        event.get('description', 'N/A'),
                        event.get('timestamp', 'N/A')
                    ])
            
            log_info(f"Exported CSV report: {output_path}")
            
        except Exception as e:
            log_error(f"Error exporting CSV report: {e}")
    
    def get_report_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get report history"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT report_id, title, report_type, generated_at, file_path
                FROM reports
                ORDER BY generated_at DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            reports = []
            for row in rows:
                reports.append({
                    'report_id': row[0],
                    'title': row[1],
                    'report_type': row[2],
                    'generated_at': datetime.fromisoformat(row[3]),
                    'file_path': row[4]
                })
            
            return reports
            
        except Exception as e:
            log_error(f"Error getting report history: {e}")
            return []
    
    def delete_report(self, report_id: str):
        """Delete a report"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM reports WHERE report_id = ?', (report_id,))
            cursor.execute('DELETE FROM report_metrics WHERE report_id = ?', (report_id,))
            
            conn.commit()
            conn.close()
            
            log_info(f"Deleted report: {report_id}")
            
        except Exception as e:
            log_error(f"Error deleting report {report_id}: {e}")

# Global reporting system instance - Singleton pattern to prevent duplicate initialization
_advanced_reporting_system = None

def get_advanced_reporting_system():
    """Get singleton advanced reporting system instance"""
    global _advanced_reporting_system
    if _advanced_reporting_system is None:
        _advanced_reporting_system = AdvancedReportingSystem()
    return _advanced_reporting_system

# Backward compatibility
advanced_reporting_system = get_advanced_reporting_system() 