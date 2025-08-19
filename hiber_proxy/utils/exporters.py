"""
Export utilities for HiberProxy Enhanced

Provides multiple output formats (JSON, CSV, XML) with metadata and filtering options.
"""

import json
import csv
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging

from ..core.exceptions import ResourceError, ParsingError
from ..core.error_handler import handle_errors, error_context

logger = logging.getLogger(__name__)


class BaseExporter:
    """Base class for all exporters"""
    
    def __init__(self, include_metadata: bool = True, include_stats: bool = True):
        self.include_metadata = include_metadata
        self.include_stats = include_stats
    
    def _prepare_data(self, proxies: List[Dict[str, Any]], 
                     additional_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prepare data structure for export"""
        data = {
            'proxies': proxies,
            'count': len(proxies)
        }
        
        if self.include_metadata:
            metadata = {
                'export_timestamp': datetime.now().isoformat(),
                'export_format': self.__class__.__name__.replace('Exporter', '').lower(),
                'hiber_proxy_version': '2.0.0',
                'total_proxies': len(proxies)
            }
            
            if additional_metadata:
                metadata.update(additional_metadata)
            
            data['metadata'] = metadata
        
        if self.include_stats and proxies:
            stats = self._calculate_stats(proxies)
            data['statistics'] = stats
        
        return data
    
    def _calculate_stats(self, proxies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate statistics for the proxy list"""
        if not proxies:
            return {}
        
        total = len(proxies)
        working = sum(1 for p in proxies if p.get('is_working', False))
        
        # Protocol distribution
        protocols = {}
        for proxy in proxies:
            protocol = proxy.get('protocol', 'unknown')
            protocols[protocol] = protocols.get(protocol, 0) + 1
        
        # Country distribution (if available)
        countries = {}
        for proxy in proxies:
            country = proxy.get('country')
            if country:
                countries[country] = countries.get(country, 0) + 1
        
        # Response time statistics
        response_times = [p.get('avg_response_time', 0) for p in proxies 
                         if p.get('avg_response_time') is not None and p.get('avg_response_time') > 0]
        
        stats = {
            'total_proxies': total,
            'working_proxies': working,
            'failed_proxies': total - working,
            'success_rate': (working / total * 100) if total > 0 else 0,
            'protocol_distribution': protocols
        }
        
        if countries:
            stats['country_distribution'] = countries
        
        if response_times:
            stats['response_time_stats'] = {
                'average': sum(response_times) / len(response_times),
                'min': min(response_times),
                'max': max(response_times),
                'count': len(response_times)
            }
        
        return stats


class JSONExporter(BaseExporter):
    """JSON format exporter with structured metadata"""
    
    @handle_errors(operation="json_export")
    def export(self, proxies: List[Dict[str, Any]], output_path: str,
               additional_metadata: Optional[Dict[str, Any]] = None,
               indent: int = 2, sort_keys: bool = True) -> int:
        """
        Export proxies to JSON format
        
        Args:
            proxies: List of proxy dictionaries
            output_path: Output file path
            additional_metadata: Additional metadata to include
            indent: JSON indentation level
            sort_keys: Whether to sort JSON keys
            
        Returns:
            Number of proxies exported
        """
        with error_context("json_export", output_path=output_path, count=len(proxies)):
            data = self._prepare_data(proxies, additional_metadata)
            
            try:
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=indent, sort_keys=sort_keys, 
                             ensure_ascii=False, default=str)
                
                logger.info(f"Exported {len(proxies)} proxies to JSON: {output_path}")
                return len(proxies)
                
            except (IOError, OSError) as e:
                raise ResourceError(
                    message=f"Failed to write JSON file: {str(e)}",
                    resource_type="file",
                    resource_path=output_path
                )
            except (TypeError, ValueError) as e:
                raise ParsingError(
                    message=f"Failed to serialize data to JSON: {str(e)}",
                    data_type="json",
                    data_source="proxy_data"
                )
    
    def export_to_string(self, proxies: List[Dict[str, Any]],
                        additional_metadata: Optional[Dict[str, Any]] = None,
                        indent: int = 2, sort_keys: bool = True) -> str:
        """Export proxies to JSON string"""
        data = self._prepare_data(proxies, additional_metadata)
        return json.dumps(data, indent=indent, sort_keys=sort_keys, 
                         ensure_ascii=False, default=str)


class CSVExporter(BaseExporter):
    """CSV format exporter with customizable columns"""
    
    DEFAULT_COLUMNS = [
        'id', 'host', 'port', 'protocol', 'is_working', 
        'success_rate', 'total_checks', 'avg_response_time',
        'country', 'city', 'created_at', 'updated_at'
    ]
    
    def __init__(self, columns: Optional[List[str]] = None, **kwargs):
        super().__init__(**kwargs)
        self.columns = columns or self.DEFAULT_COLUMNS
    
    @handle_errors(operation="csv_export")
    def export(self, proxies: List[Dict[str, Any]], output_path: str,
               additional_metadata: Optional[Dict[str, Any]] = None,
               include_header: bool = True, delimiter: str = ',') -> int:
        """
        Export proxies to CSV format
        
        Args:
            proxies: List of proxy dictionaries
            output_path: Output file path
            additional_metadata: Additional metadata to include
            include_header: Whether to include column headers
            delimiter: CSV delimiter character
            
        Returns:
            Number of proxies exported
        """
        with error_context("csv_export", output_path=output_path, count=len(proxies)):
            try:
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.columns, 
                                          delimiter=delimiter, extrasaction='ignore')
                    
                    if include_header:
                        writer.writeheader()
                    
                    # Write proxy data
                    for proxy in proxies:
                        # Convert None values to empty strings for CSV
                        row = {col: proxy.get(col, '') or '' for col in self.columns}
                        writer.writerow(row)
                    
                    # Write metadata as comments if requested
                    if self.include_metadata and additional_metadata:
                        f.write(f"\n# Metadata:\n")
                        for key, value in additional_metadata.items():
                            f.write(f"# {key}: {value}\n")
                
                logger.info(f"Exported {len(proxies)} proxies to CSV: {output_path}")
                return len(proxies)
                
            except (IOError, OSError) as e:
                raise ResourceError(
                    message=f"Failed to write CSV file: {str(e)}",
                    resource_type="file",
                    resource_path=output_path
                )
            except csv.Error as e:
                raise ParsingError(
                    message=f"CSV formatting error: {str(e)}",
                    data_type="csv",
                    data_source="proxy_data"
                )


class XMLExporter(BaseExporter):
    """XML format exporter with schema validation"""
    
    @handle_errors(operation="xml_export")
    def export(self, proxies: List[Dict[str, Any]], output_path: str,
               additional_metadata: Optional[Dict[str, Any]] = None,
               pretty_print: bool = True) -> int:
        """
        Export proxies to XML format
        
        Args:
            proxies: List of proxy dictionaries
            output_path: Output file path
            additional_metadata: Additional metadata to include
            pretty_print: Whether to format XML with indentation
            
        Returns:
            Number of proxies exported
        """
        with error_context("xml_export", output_path=output_path, count=len(proxies)):
            try:
                # Create root element
                root = ET.Element("hiber_proxy_export")
                
                # Add metadata
                if self.include_metadata:
                    metadata_elem = ET.SubElement(root, "metadata")
                    metadata = {
                        'export_timestamp': datetime.now().isoformat(),
                        'export_format': 'xml',
                        'hiber_proxy_version': '2.0.0',
                        'total_proxies': len(proxies)
                    }
                    
                    if additional_metadata:
                        metadata.update(additional_metadata)
                    
                    for key, value in metadata.items():
                        elem = ET.SubElement(metadata_elem, key)
                        elem.text = str(value)
                
                # Add statistics
                if self.include_stats and proxies:
                    stats = self._calculate_stats(proxies)
                    stats_elem = ET.SubElement(root, "statistics")
                    self._dict_to_xml(stats, stats_elem)
                
                # Add proxies
                proxies_elem = ET.SubElement(root, "proxies")
                for proxy in proxies:
                    proxy_elem = ET.SubElement(proxies_elem, "proxy")
                    
                    for key, value in proxy.items():
                        if value is not None:
                            elem = ET.SubElement(proxy_elem, key)
                            elem.text = str(value)
                
                # Write to file
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                tree = ET.ElementTree(root)
                if pretty_print:
                    self._indent_xml(root)
                
                tree.write(output_file, encoding='utf-8', xml_declaration=True)
                
                logger.info(f"Exported {len(proxies)} proxies to XML: {output_path}")
                return len(proxies)
                
            except (IOError, OSError) as e:
                raise ResourceError(
                    message=f"Failed to write XML file: {str(e)}",
                    resource_type="file",
                    resource_path=output_path
                )
            except ET.ParseError as e:
                raise ParsingError(
                    message=f"XML formatting error: {str(e)}",
                    data_type="xml",
                    data_source="proxy_data"
                )
    
    def _dict_to_xml(self, data: Dict[str, Any], parent: ET.Element):
        """Convert dictionary to XML elements"""
        for key, value in data.items():
            elem = ET.SubElement(parent, key)
            if isinstance(value, dict):
                self._dict_to_xml(value, elem)
            elif isinstance(value, list):
                for item in value:
                    item_elem = ET.SubElement(elem, "item")
                    if isinstance(item, dict):
                        self._dict_to_xml(item, item_elem)
                    else:
                        item_elem.text = str(item)
            else:
                elem.text = str(value)
    
    def _indent_xml(self, elem: ET.Element, level: int = 0):
        """Add indentation to XML for pretty printing"""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent


class ExportManager:
    """Manager class for handling multiple export formats"""
    
    def __init__(self):
        self.exporters = {
            'json': JSONExporter,
            'csv': CSVExporter,
            'xml': XMLExporter
        }
    
    def get_exporter(self, format_name: str, **kwargs) -> BaseExporter:
        """Get exporter instance for specified format"""
        if format_name.lower() not in self.exporters:
            raise ValueError(f"Unsupported export format: {format_name}")
        
        exporter_class = self.exporters[format_name.lower()]
        return exporter_class(**kwargs)
    
    def export(self, proxies: List[Dict[str, Any]], output_path: str,
               format_name: str, **kwargs) -> int:
        """Export proxies using specified format"""
        exporter = self.get_exporter(format_name, **kwargs)
        return exporter.export(proxies, output_path, **kwargs)
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported export formats"""
        return list(self.exporters.keys())
