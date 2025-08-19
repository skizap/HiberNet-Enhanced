"""
API routes for HiberNet Enhanced web interface

Provides RESTful API endpoints for proxy management, statistics,
and system operations with proper error handling and validation.
"""

from flask import Blueprint, request, jsonify, send_file, current_app
import tempfile
import json
import os
from typing import Dict, Any, Optional

# Create API blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/stats')
def get_stats():
    """Get comprehensive system statistics"""
    try:
        hiber_app = current_app.hiber_app
        if hiber_app is None:
            # Return default stats if app not initialized
            return jsonify({
                'total_proxies': 0,
                'working_proxies': 0,
                'failed_proxies': 0,
                'success_percentage': 0,
                'average_response_time': 0,
                'average_success_rate': 0,
                'last_check': 'Never',
                'status': 'Initializing...'
            })

        stats = hiber_app.get_statistics()

        # Add additional computed stats
        if 'total_proxies' in stats and 'working_proxies' in stats:
            stats['failed_proxies'] = stats['total_proxies'] - stats['working_proxies']
            if stats['total_proxies'] > 0:
                stats['success_percentage'] = (stats['working_proxies'] / stats['total_proxies']) * 100
            else:
                stats['success_percentage'] = 0

        return jsonify(stats)

    except Exception as e:
        current_app.logger_instance.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/protocol-stats')
def get_protocol_stats():
    """Get protocol distribution statistics"""
    try:
        hiber_app = current_app.hiber_app
        if hiber_app is None:
            # Return default protocol stats if app not initialized
            return jsonify({'http': 0, 'https': 0, 'socks4': 0, 'socks5': 0})

        stats = hiber_app.get_statistics()

        # Extract protocol distribution
        protocol_stats = stats.get('protocol_distribution', {})

        # Ensure all protocols are represented
        default_protocols = {'http': 0, 'https': 0, 'socks4': 0, 'socks5': 0}
        default_protocols.update(protocol_stats)

        return jsonify(default_protocols)

    except Exception as e:
        current_app.logger_instance.error(f"Error getting protocol stats: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/proxies')
def get_proxies():
    """Get proxy list with filtering options"""
    try:
        hiber_app = current_app.hiber_app
        
        # Parse query parameters
        protocol = request.args.get('protocol')
        working_only = request.args.get('working_only', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        # Validate parameters
        if limit > 1000:
            limit = 1000  # Prevent excessive data transfer
        
        proxies = hiber_app.list_proxies(
            protocol=protocol,
            working_only=working_only,
            limit=limit
        )
        
        # Apply offset if specified
        if offset > 0:
            proxies = proxies[offset:]
        
        return jsonify({
            'proxies': proxies,
            'count': len(proxies),
            'filters': {
                'protocol': protocol,
                'working_only': working_only,
                'limit': limit,
                'offset': offset
            }
        })
        
    except ValueError as e:
        return jsonify({'error': f'Invalid parameter: {e}'}), 400
    except Exception as e:
        current_app.logger_instance.error(f"Error getting proxies: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/download', methods=['POST'])
def download_proxies():
    """Download proxies from configured sources"""
    try:
        hiber_app = current_app.hiber_app
        data = request.get_json() or {}
        
        protocol = data.get('protocol')
        repository = data.get('repository')
        
        # Validate protocol if specified
        valid_protocols = ['http', 'https', 'socks4', 'socks5']
        if protocol and protocol not in valid_protocols:
            return jsonify({'error': f'Invalid protocol. Must be one of: {valid_protocols}'}), 400
        
        results = hiber_app.download_proxies(
            protocol=protocol,
            repository=repository
        )
        
        # Emit real-time update via WebSocket
        if hasattr(current_app, 'socketio'):
            current_app.socketio.emit('proxy_update', {
                'type': 'download',
                'data': results
            })
        
        return jsonify(results)
        
    except Exception as e:
        current_app.logger_instance.error(f"Error downloading proxies: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/check', methods=['POST'])
def check_proxies():
    """Check proxy connectivity and update status"""
    try:
        hiber_app = current_app.hiber_app
        data = request.get_json() or {}
        
        protocol = data.get('protocol')
        limit = data.get('limit', 100)
        working_only = data.get('working_only', True)
        
        # Validate parameters
        if limit > 500:
            limit = 500  # Prevent excessive checking
        
        valid_protocols = ['http', 'https', 'socks4', 'socks5']
        if protocol and protocol not in valid_protocols:
            return jsonify({'error': f'Invalid protocol. Must be one of: {valid_protocols}'}), 400
        
        results = hiber_app.check_proxies(
            protocol=protocol,
            limit=limit,
            working_only=not working_only,
            socketio=getattr(current_app, 'socketio', None)
        )
        
        # Emit real-time update via WebSocket
        if hasattr(current_app, 'socketio'):
            current_app.socketio.emit('proxy_update', {
                'type': 'check',
                'data': results
            })
        
        return jsonify(results)
        
    except ValueError as e:
        return jsonify({'error': f'Invalid parameter: {e}'}), 400
    except Exception as e:
        current_app.logger_instance.error(f"Error checking proxies: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/add', methods=['POST'])
def add_proxy():
    """Add a single proxy to the database"""
    try:
        hiber_app = current_app.hiber_app
        data = request.get_json()
        
        if not data or 'proxy' not in data:
            return jsonify({'error': 'Proxy string required in request body'}), 400
        
        proxy_string = data['proxy'].strip()
        if not proxy_string:
            return jsonify({'error': 'Proxy string cannot be empty'}), 400
        
        proxy_id = hiber_app.add_proxy(proxy_string)
        
        if proxy_id:
            # Emit real-time update via WebSocket
            if hasattr(current_app, 'socketio'):
                current_app.socketio.emit('proxy_update', {
                    'type': 'add',
                    'data': {'proxy_id': proxy_id, 'proxy': proxy_string}
                })
            
            return jsonify({
                'success': True,
                'proxy_id': proxy_id,
                'message': f'Proxy added successfully (ID: {proxy_id})'
            })
        else:
            return jsonify({'error': 'Failed to add proxy - invalid format or duplicate'}), 400
            
    except Exception as e:
        current_app.logger_instance.error(f"Error adding proxy: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/cleanup', methods=['POST'])
def cleanup_database():
    """Remove failed or invalid proxies from database"""
    try:
        hiber_app = current_app.hiber_app
        
        # Get cleanup options from request
        data = request.get_json() or {}
        remove_failed = data.get('remove_failed', True)
        remove_duplicates = data.get('remove_duplicates', True)
        
        results = hiber_app.cleanup_database()
        
        # Emit real-time update via WebSocket
        if hasattr(current_app, 'socketio'):
            current_app.socketio.emit('proxy_update', {
                'type': 'cleanup',
                'data': results
            })
        
        return jsonify(results)
        
    except Exception as e:
        current_app.logger_instance.error(f"Error during cleanup: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/export')
def export_proxies():
    """Export proxies to downloadable file"""
    try:
        hiber_app = current_app.hiber_app
        
        # Parse query parameters
        format_type = request.args.get('format', 'txt').lower()
        protocol = request.args.get('protocol')
        working_only = request.args.get('working_only', 'true').lower() == 'true'
        
        # Validate format
        valid_formats = ['txt', 'json', 'csv']
        if format_type not in valid_formats:
            return jsonify({'error': f'Invalid format. Must be one of: {valid_formats}'}), 400
        
        # Get proxies
        proxies = hiber_app.list_proxies(
            protocol=protocol,
            working_only=working_only
        )
        
        if not proxies:
            return jsonify({'error': 'No proxies found matching criteria'}), 404
        
        # Generate content based on format
        if format_type == 'json':
            content = json.dumps(proxies, indent=2)
            filename = 'proxies.json'
            mimetype = 'application/json'
            
        elif format_type == 'csv':
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=proxies[0].keys())
            writer.writeheader()
            writer.writerows(proxies)
            content = output.getvalue()
            filename = 'proxies.csv'
            mimetype = 'text/csv'
            
        else:  # txt format (default)
            content = '\n'.join([f"{p['host']}:{p['port']}" for p in proxies])
            filename = 'proxies.txt'
            mimetype = 'text/plain'
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=f'.{format_type}')
        temp_file.write(content)
        temp_file.close()
        
        # Schedule file cleanup after download
        def cleanup_temp_file():
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
        
        # Return file for download
        return send_file(
            temp_file.name,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
    except Exception as e:
        current_app.logger_instance.error(f"Error exporting proxies: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/sources')
def get_sources():
    """Get available proxy sources information"""
    try:
        hiber_app = current_app.hiber_app
        sources = hiber_app.get_available_sources()
        return jsonify(sources)
        
    except Exception as e:
        current_app.logger_instance.error(f"Error getting sources: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/sources/test', methods=['POST'])
def test_sources():
    """Test availability of proxy sources"""
    try:
        hiber_app = current_app.hiber_app
        availability = hiber_app.test_source_availability()
        return jsonify(availability)

    except Exception as e:
        current_app.logger_instance.error(f"Error testing sources: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stress-test', methods=['POST'])
def stress_test():
    """Run network stress test on proxies"""
    try:
        hiber_app = current_app.hiber_app
        data = request.get_json() or {}

        # Parse stress test parameters
        test_type = data.get('test_type', 'basic')
        concurrent_connections = data.get('concurrent_connections', 10)
        duration = data.get('duration', 60)  # seconds
        target_url = data.get('target_url', 'http://httpbin.org/ip')
        protocol = data.get('protocol')
        proxy_limit = data.get('proxy_limit', 50)

        # Validate parameters
        if concurrent_connections > 100:
            concurrent_connections = 100
        if duration > 300:  # Max 5 minutes
            duration = 300

        # Run stress test
        results = run_stress_test(
            hiber_app=hiber_app,
            test_type=test_type,
            concurrent_connections=concurrent_connections,
            duration=duration,
            target_url=target_url,
            protocol=protocol,
            proxy_limit=proxy_limit
        )

        # Emit real-time update via WebSocket
        if hasattr(current_app, 'socketio'):
            current_app.socketio.emit('stress_test_update', {
                'type': 'stress_test',
                'data': results
            })

        return jsonify(results)

    except Exception as e:
        current_app.logger_instance.error(f"Error running stress test: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stress-test/status')
def stress_test_status():
    """Get current stress test status"""
    try:
        # Return current stress test status
        # In a real implementation, this would track ongoing tests
        return jsonify({
            'running': False,
            'progress': 0,
            'current_test': None,
            'results': None
        })

    except Exception as e:
        current_app.logger_instance.error(f"Error getting stress test status: {e}")
        return jsonify({'error': str(e)}), 500

def run_stress_test(hiber_app, test_type, concurrent_connections, duration, target_url, protocol, proxy_limit):
    """Run the actual stress test"""
    import time
    import threading
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Get proxies for testing
    proxies = hiber_app.list_proxies(
        protocol=protocol,
        working_only=True,
        limit=proxy_limit
    )

    if not proxies:
        return {
            'error': 'No working proxies available for stress testing',
            'total_proxies': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'average_response_time': 0,
            'requests_per_second': 0
        }

    results = {
        'test_type': test_type,
        'duration': duration,
        'concurrent_connections': concurrent_connections,
        'target_url': target_url,
        'total_proxies': len(proxies),
        'successful_requests': 0,
        'failed_requests': 0,
        'total_requests': 0,
        'response_times': [],
        'start_time': time.time(),
        'end_time': None,
        'requests_per_second': 0,
        'average_response_time': 0,
        'proxy_performance': {}
    }

    def test_proxy_request(proxy):
        """Test a single request through a proxy"""
        try:
            proxy_url = f"{proxy['protocol']}://{proxy['host']}:{proxy['port']}"
            proxies_dict = {
                'http': proxy_url,
                'https': proxy_url
            }

            start_time = time.time()
            response = requests.get(
                target_url,
                proxies=proxies_dict,
                timeout=10,
                verify=False
            )
            end_time = time.time()

            response_time = (end_time - start_time) * 1000  # Convert to milliseconds

            if response.status_code == 200:
                return {
                    'success': True,
                    'response_time': response_time,
                    'proxy_id': proxy['id'],
                    'status_code': response.status_code
                }
            else:
                return {
                    'success': False,
                    'response_time': response_time,
                    'proxy_id': proxy['id'],
                    'status_code': response.status_code,
                    'error': f'HTTP {response.status_code}'
                }

        except Exception as e:
            return {
                'success': False,
                'response_time': 0,
                'proxy_id': proxy['id'],
                'status_code': 0,
                'error': str(e)
            }

    # Run stress test
    start_time = time.time()
    end_time = start_time + duration

    with ThreadPoolExecutor(max_workers=concurrent_connections) as executor:
        while time.time() < end_time:
            # Submit requests for all proxies
            futures = []
            for proxy in proxies:
                if time.time() >= end_time:
                    break
                future = executor.submit(test_proxy_request, proxy)
                futures.append(future)

            # Collect results
            for future in as_completed(futures, timeout=duration):
                if time.time() >= end_time:
                    break

                try:
                    result = future.result()
                    results['total_requests'] += 1

                    if result['success']:
                        results['successful_requests'] += 1
                        results['response_times'].append(result['response_time'])
                    else:
                        results['failed_requests'] += 1

                    # Track proxy performance
                    proxy_id = result['proxy_id']
                    if proxy_id not in results['proxy_performance']:
                        results['proxy_performance'][proxy_id] = {
                            'requests': 0,
                            'successes': 0,
                            'failures': 0,
                            'avg_response_time': 0,
                            'response_times': []
                        }

                    perf = results['proxy_performance'][proxy_id]
                    perf['requests'] += 1

                    if result['success']:
                        perf['successes'] += 1
                        perf['response_times'].append(result['response_time'])
                        if perf['response_times']:
                            perf['avg_response_time'] = sum(perf['response_times']) / len(perf['response_times'])
                    else:
                        perf['failures'] += 1

                except Exception as e:
                    results['failed_requests'] += 1
                    results['total_requests'] += 1

    # Calculate final statistics
    results['end_time'] = time.time()
    actual_duration = results['end_time'] - results['start_time']

    if actual_duration > 0:
        results['requests_per_second'] = results['total_requests'] / actual_duration

    if results['response_times']:
        results['average_response_time'] = sum(results['response_times']) / len(results['response_times'])
        results['min_response_time'] = min(results['response_times'])
        results['max_response_time'] = max(results['response_times'])

    # Calculate success rate
    if results['total_requests'] > 0:
        results['success_rate'] = (results['successful_requests'] / results['total_requests']) * 100
    else:
        results['success_rate'] = 0

    return results

# Error handlers for the API blueprint
@api_bp.errorhandler(404)
def api_not_found(error):
    return jsonify({'error': 'API endpoint not found'}), 404

@api_bp.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'error': 'Method not allowed'}), 405

@api_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
