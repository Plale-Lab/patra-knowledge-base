"""
Tests for URL validation script
"""

import pytest
from unittest.mock import Mock, patch
import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.validate_urls import validate_url


class TestURLValidation:
    
    @patch('requests.head')
    def test_valid_url_format(self, mock_head):
        """Test that valid URL formats are accepted"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response
        
        is_valid, error = validate_url("https://example.com/model")
        assert is_valid is True
        assert error is None
    
    def test_invalid_url_format(self):
        """Test that invalid URL formats are rejected"""
        is_valid, error = validate_url("invalid-url")
        assert is_valid is False
        assert "Invalid URL format" in error
    
    def test_missing_scheme(self):
        """Test URLs without scheme are rejected"""
        is_valid, error = validate_url("example.com/model")
        assert is_valid is False
        assert "Invalid URL format" in error
    
    def test_missing_netloc(self):
        """Test URLs without netloc are rejected"""
        is_valid, error = validate_url("https://")
        assert is_valid is False
        assert "Invalid URL format" in error
    
    @patch('requests.head')
    def test_successful_http_request(self, mock_head):
        """Test successful HTTP request"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response
        
        is_valid, error = validate_url("https://example.com/model")
        assert is_valid is True
        assert error is None
    
    @patch('requests.head')
    def test_http_404_error(self, mock_head):
        """Test HTTP 404 error"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_head.return_value = mock_response
        
        is_valid, error = validate_url("https://example.com/nonexistent")
        assert is_valid is False
        assert "HTTP 404" in error
    
    @patch('requests.head')
    def test_http_500_error(self, mock_head):
        """Test HTTP 500 error"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_head.return_value = mock_response
        
        is_valid, error = validate_url("https://example.com/error")
        assert is_valid is False
        assert "HTTP 500" in error
    
    @patch('requests.head')
    def test_connection_timeout(self, mock_head):
        """Test connection timeout"""
        mock_head.side_effect = Exception("Connection timeout")
        
        is_valid, error = validate_url("https://example.com/timeout")
        assert is_valid is False
        assert "Connection timeout" in error


if __name__ == "__main__":
    pytest.main([__file__])
