# pystxmcontrol-mcp Test Suite

This directory contains comprehensive unit tests for the pystxmcontrol-mcp project.

## Test Files

- `test_server.py` - Tests for the MCP server module (server.py:347)
  - Tests all MCP tool functions
  - Tests connection handling and error cases
  - Tests motor operations and scan functions
  - Tests motor position plotting

- `test_scripter.py` - Tests for the scripter client module (scripter.py:404)
  - Tests ZMQ connection initialization
  - Tests motor movement and position reading
  - Tests DAQ operations
  - Tests STXM scan execution
  - Tests configuration retrieval

- `test_utilities.py` - Tests for utility functions (utilities.py:288)
  - Tests scan extraction from STXM files
  - Tests database utilities (monthly rotation, path generation)
  - Tests motor position queries from SQLite databases
  - Tests motor position plotting

## Running Tests

### Run all tests
```bash
pytest tests/
```

### Run specific test file
```bash
pytest tests/test_server.py
pytest tests/test_scripter.py
pytest tests/test_utilities.py
```

### Run specific test class
```bash
pytest tests/test_server.py::TestConnectToServer
```

### Run specific test
```bash
pytest tests/test_server.py::TestConnectToServer::test_connect_to_server_success
```

### Run with verbose output
```bash
pytest tests/ -v
```

### Run with coverage report
```bash
pytest tests/ --cov=pystxmcontrol --cov-report=html
```

## Test Coverage

The test suite provides comprehensive coverage of:

### Server Module (server.py)
- ✓ Motor status checking
- ✓ Scan definition from files
- ✓ Scan parameter updates
- ✓ Motor position retrieval
- ✓ Server connection (success, timeout, errors)
- ✓ Motor movement (success, failures, invalid motors)
- ✓ Configuration retrieval
- ✓ STXM scan execution
- ✓ Motor position plotting (various time ranges)

### Scripter Module (scripter.py)
- ✓ Initialization with custom/default parameters
- ✓ ZMQ socket configuration
- ✓ Motor movement with validation
- ✓ Configuration retrieval with error handling
- ✓ DAQ reading
- ✓ Monitor start/stop
- ✓ Motor position reading
- ✓ STXM scan execution with energy lists
- ✓ Scan failure handling

### Utilities Module (utilities.py)
- ✓ Scan extraction from STXM files
- ✓ Database directory creation
- ✓ Monthly database path generation
- ✓ Multi-month database queries
- ✓ Motor position queries with filters
- ✓ Position plotting with various time ranges
- ✓ Error handling for missing data

## Test Statistics

- **Total Tests**: 59
- **Test Classes**: 15
- **Success Rate**: 100%

## Mocking Strategy

Tests use `unittest.mock` to:
- Mock ZMQ socket connections (avoiding real network calls)
- Mock database operations (using temporary directories)
- Mock file I/O for STXM files
- Mock matplotlib for plot generation tests

This ensures tests:
- Run quickly without external dependencies
- Don't require a running pystxmcontrol server
- Don't create permanent files or databases
- Are isolated and repeatable

## Adding New Tests

When adding new functionality:

1. Add corresponding test methods to the appropriate test class
2. Use descriptive test names: `test_<function>_<scenario>`
3. Include docstrings explaining what is being tested
4. Mock external dependencies (network, filesystem, etc.)
5. Test both success and failure cases
6. Run the full test suite to ensure no regressions

Example:
```python
def test_new_function_success(self):
    """Test new_function with valid input"""
    # Setup
    mock_obj = Mock()

    # Execute
    result = new_function(mock_obj)

    # Assert
    assert result == expected_value
    mock_obj.method.assert_called_once()
```
