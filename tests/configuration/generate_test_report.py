"""
Test Report Generator for Configuration Service Tests
Generates comprehensive test reports with coverage analysis

Usage:
    python generate_test_report.py
    python generate_test_report.py --format html
    python generate_test_report.py --format json
    python generate_test_report.py --format markdown
"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any


class TestReportGenerator:
    """Generate comprehensive test reports"""
    
    def __init__(self):
        self.test_dir = Path(__file__).parent
        self.project_root = self.test_dir.parent.parent
        self.timestamp = datetime.now().isoformat()
        self.results = {}
    
    def run_tests_with_coverage(self) -> Dict[str, Any]:
        """Run tests and collect coverage data"""
        print("🧪 Running tests with coverage...")
        
        cmd = [
            'pytest',
            str(self.test_dir),
            '-v',
            '--cov=configuration',
            '--cov-report=json',
            '--cov-report=html',
            '--cov-report=term-missing',
            '--tb=short',
            '--json-report',
            '--json-report-file=test-report.json'
        ]
        
        try:
            result = subprocess.run(cmd, cwd=str(self.project_root), capture_output=True, text=True)
            
            # Parse coverage data
            coverage_file = self.project_root / '.coverage'
            coverage_json = self.project_root / 'coverage.json'
            
            coverage_data = {}
            if coverage_json.exists():
                with open(coverage_json) as f:
                    coverage_data = json.load(f)
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'coverage': coverage_data,
                'timestamp': self.timestamp
            }
        except Exception as e:
            print(f"❌ Error running tests: {e}")
            return {'success': False, 'error': str(e)}
    
    def parse_test_output(self, output: str) -> Dict[str, Any]:
        """Parse pytest output"""
        lines = output.split('\n')
        
        tests = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0,
            'details': []
        }
        
        for line in lines:
            if 'PASSED' in line:
                tests['passed'] += 1
                tests['details'].append({'status': 'PASSED', 'line': line})
            elif 'FAILED' in line:
                tests['failed'] += 1
                tests['details'].append({'status': 'FAILED', 'line': line})
            elif 'SKIPPED' in line:
                tests['skipped'] += 1
                tests['details'].append({'status': 'SKIPPED', 'line': line})
            elif 'ERROR' in line:
                tests['errors'] += 1
                tests['details'].append({'status': 'ERROR', 'line': line})
        
        return tests
    
    def generate_markdown_report(self, results: Dict[str, Any]) -> str:
        """Generate markdown format report"""
        report = []
        report.append("# Configuration Service Test Report\n")
        report.append(f"**Generated**: {self.timestamp}\n")
        
        # Summary
        report.append("## Summary\n")
        if results.get('success'):
            report.append("✅ **Status**: All tests passed\n")
        else:
            report.append("❌ **Status**: Some tests failed\n")
        
        # Coverage
        if 'coverage' in results:
            coverage = results['coverage']
            report.append("\n## Coverage\n")
            report.append(f"- **Overall Coverage**: {coverage.get('totals', {}).get('percent_covered', 'N/A')}%\n")
            report.append(f"- **Lines Covered**: {coverage.get('totals', {}).get('covered_lines', 'N/A')}\n")
            report.append(f"- **Lines Missing**: {coverage.get('totals', {}).get('missing_lines', 'N/A')}\n")
        
        # Test Results
        test_data = self.parse_test_output(results.get('stdout', ''))
        report.append("\n## Test Results\n")
        report.append(f"- **Passed**: {test_data['passed']}\n")
        report.append(f"- **Failed**: {test_data['failed']}\n")
        report.append(f"- **Skipped**: {test_data['skipped']}\n")
        report.append(f"- **Errors**: {test_data['errors']}\n")
        report.append(f"- **Total**: {test_data['passed'] + test_data['failed'] + test_data['skipped'] + test_data['errors']}\n")
        
        # Test Details
        if test_data['details']:
            report.append("\n## Test Details\n")
            for detail in test_data['details'][:20]:  # Show first 20
                status_emoji = '✅' if detail['status'] == 'PASSED' else '❌'
                report.append(f"{status_emoji} {detail['line']}\n")
        
        return ''.join(report)
    
    def generate_html_report(self, results: Dict[str, Any]) -> str:
        """Generate HTML format report"""
        test_data = self.parse_test_output(results.get('stdout', ''))
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Configuration Service Test Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                .summary {{ margin: 20px 0; }}
                .passed {{ color: green; }}
                .failed {{ color: red; }}
                .skipped {{ color: orange; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Configuration Service Test Report</h1>
                <p>Generated: {self.timestamp}</p>
                <p>Status: {'✅ All tests passed' if results.get('success') else '❌ Some tests failed'}</p>
            </div>
            
            <div class="summary">
                <h2>Test Summary</h2>
                <table>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Passed</td>
                        <td class="passed">{test_data['passed']}</td>
                    </tr>
                    <tr>
                        <td>Failed</td>
                        <td class="failed">{test_data['failed']}</td>
                    </tr>
                    <tr>
                        <td>Skipped</td>
                        <td class="skipped">{test_data['skipped']}</td>
                    </tr>
                    <tr>
                        <td>Errors</td>
                        <td class="failed">{test_data['errors']}</td>
                    </tr>
                    <tr>
                        <td>Total</td>
                        <td><strong>{test_data['passed'] + test_data['failed'] + test_data['skipped'] + test_data['errors']}</strong></td>
                    </tr>
                </table>
            </div>
            
            <div class="coverage">
                <h2>Coverage</h2>
                <table>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Overall Coverage</td>
                        <td>{results.get('coverage', {}).get('totals', {}).get('percent_covered', 'N/A')}%</td>
                    </tr>
                    <tr>
                        <td>Lines Covered</td>
                        <td>{results.get('coverage', {}).get('totals', {}).get('covered_lines', 'N/A')}</td>
                    </tr>
                    <tr>
                        <td>Lines Missing</td>
                        <td>{results.get('coverage', {}).get('totals', {}).get('missing_lines', 'N/A')}</td>
                    </tr>
                </table>
            </div>
        </body>
        </html>
        """
        return html
    
    def generate_json_report(self, results: Dict[str, Any]) -> str:
        """Generate JSON format report"""
        test_data = self.parse_test_output(results.get('stdout', ''))
        
        report = {
            'timestamp': self.timestamp,
            'status': 'passed' if results.get('success') else 'failed',
            'tests': {
                'passed': test_data['passed'],
                'failed': test_data['failed'],
                'skipped': test_data['skipped'],
                'errors': test_data['errors'],
                'total': test_data['passed'] + test_data['failed'] + test_data['skipped'] + test_data['errors']
            },
            'coverage': results.get('coverage', {}).get('totals', {}),
            'details': test_data['details'][:50]  # First 50 tests
        }
        
        return json.dumps(report, indent=2)
    
    def generate_report(self, format: str = 'markdown') -> str:
        """Generate report in specified format"""
        print(f"📊 Generating {format} report...")
        
        results = self.run_tests_with_coverage()
        
        if format == 'markdown':
            return self.generate_markdown_report(results)
        elif format == 'html':
            return self.generate_html_report(results)
        elif format == 'json':
            return self.generate_json_report(results)
        else:
            raise ValueError(f"Unknown format: {format}")
    
    def save_report(self, report: str, format: str = 'markdown'):
        """Save report to file"""
        if format == 'markdown':
            filename = 'TEST_REPORT.md'
        elif format == 'html':
            filename = 'TEST_REPORT.html'
        elif format == 'json':
            filename = 'TEST_REPORT.json'
        else:
            filename = 'TEST_REPORT.txt'
        
        filepath = self.test_dir / filename
        with open(filepath, 'w') as f:
            f.write(report)
        
        print(f"✅ Report saved to {filepath}")
        return filepath


def main():
    """Main entry point"""
    format = 'markdown'
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--format' and len(sys.argv) > 2:
            format = sys.argv[2]
    
    generator = TestReportGenerator()
    report = generator.generate_report(format)
    generator.save_report(report, format)
    
    print(f"\n{report[:500]}...")  # Print first 500 chars


if __name__ == '__main__':
    main()
