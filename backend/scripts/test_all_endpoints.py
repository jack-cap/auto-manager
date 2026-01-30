#!/usr/bin/env python3
"""
Comprehensive Manager.io API Test Script

This script:
1. Reads all endpoints from manager_openapi.json
2. Tests each GET endpoint automatically
3. Records response structure (keys, types, sample data)
4. Generates a report of working vs failing endpoints
5. Outputs a JSON file with endpoint metadata for the agent

Usage:
    python backend/scripts/test_all_endpoints.py
    python backend/scripts/test_all_endpoints.py --only-get        # Only test GET endpoints
    python backend/scripts/test_all_endpoints.py --save-responses  # Save full responses
    python backend/scripts/test_all_endpoints.py --endpoint /receipts  # Test specific endpoint
"""

import asyncio
import json
import argparse
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
from dotenv import load_dotenv


# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env.test")

BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")
API_KEY = os.getenv("MANAGER_READ_API_KEY", "")

OPENAPI_FILE = SCRIPT_DIR / "manager_openapi.json"
OUTPUT_DIR = SCRIPT_DIR / "test_results"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EndpointResult:
    """Result of testing an endpoint."""
    endpoint: str
    method: str
    status_code: int
    success: bool
    response_keys: List[str]
    data_key: Optional[str]  # The key containing the main data array
    record_count: Optional[int]
    sample_record_keys: List[str]
    error_message: Optional[str]
    response_preview: Optional[str]


@dataclass 
class TestReport:
    """Overall test report."""
    timestamp: str
    base_url: str
    total_endpoints: int
    tested_endpoints: int
    successful: int
    failed: int
    skipped: int
    results: List[EndpointResult]


# =============================================================================
# Helper Functions
# =============================================================================

def get_type_name(value: Any) -> str:
    """Get a readable type name for a value."""
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "integer"
    elif isinstance(value, float):
        return "number"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, list):
        if value:
            return f"array[{get_type_name(value[0])}]"
        return "array[]"
    elif isinstance(value, dict):
        return "object"
    return type(value).__name__


def analyze_response(data: Any) -> Dict[str, Any]:
    """Analyze response structure."""
    result = {
        "type": get_type_name(data),
        "keys": [],
        "data_key": None,
        "record_count": None,
        "sample_record_keys": [],
    }
    
    if isinstance(data, dict):
        result["keys"] = list(data.keys())
        
        # Find the main data array (usually matches endpoint name in camelCase)
        for key, value in data.items():
            if isinstance(value, list) and key not in ["Columns", "Rows"]:
                result["data_key"] = key
                result["record_count"] = len(value)
                if value and isinstance(value[0], dict):
                    result["sample_record_keys"] = list(value[0].keys())
                break
        
        # Check for totalRecords
        if "totalRecords" in data:
            result["total_records"] = data["totalRecords"]
            
    elif isinstance(data, list):
        result["record_count"] = len(data)
        if data and isinstance(data[0], dict):
            result["sample_record_keys"] = list(data[0].keys())
    
    return result


def truncate_preview(data: Any, max_length: int = 500) -> str:
    """Create a truncated preview of the response."""
    text = json.dumps(data, indent=2, default=str)
    if len(text) > max_length:
        return text[:max_length] + "\n... [truncated]"
    return text


# =============================================================================
# Main Test Functions
# =============================================================================

async def test_endpoint(
    client: httpx.AsyncClient,
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict] = None,
    data: Optional[Dict] = None,
) -> EndpointResult:
    """Test a single endpoint."""
    
    url = f"{BASE_URL}{endpoint}"
    
    # Add pagination params for GET requests
    if method == "GET" and params is None:
        params = {"skip": 0, "pageSize": 5}
    
    try:
        if method == "GET":
            response = await client.get(url, params=params)
        elif method == "POST":
            response = await client.post(url, json=data or {})
        elif method == "PUT":
            response = await client.put(url, json=data or {})
        elif method == "DELETE":
            response = await client.delete(url)
        else:
            return EndpointResult(
                endpoint=endpoint,
                method=method,
                status_code=0,
                success=False,
                response_keys=[],
                data_key=None,
                record_count=None,
                sample_record_keys=[],
                error_message=f"Unsupported method: {method}",
                response_preview=None,
            )
        
        status_code = response.status_code
        success = response.is_success
        
        if success:
            try:
                resp_data = response.json()
                analysis = analyze_response(resp_data)
                
                return EndpointResult(
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    success=True,
                    response_keys=analysis["keys"],
                    data_key=analysis["data_key"],
                    record_count=analysis["record_count"],
                    sample_record_keys=analysis["sample_record_keys"],
                    error_message=None,
                    response_preview=truncate_preview(resp_data),
                )
            except json.JSONDecodeError:
                return EndpointResult(
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    success=True,
                    response_keys=[],
                    data_key=None,
                    record_count=None,
                    sample_record_keys=[],
                    error_message="Response is not JSON",
                    response_preview=response.text[:500],
                )
        else:
            return EndpointResult(
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                success=False,
                response_keys=[],
                data_key=None,
                record_count=None,
                sample_record_keys=[],
                error_message=response.text[:200],
                response_preview=None,
            )
            
    except Exception as e:
        return EndpointResult(
            endpoint=endpoint,
            method=method,
            status_code=0,
            success=False,
            response_keys=[],
            data_key=None,
            record_count=None,
            sample_record_keys=[],
            error_message=str(e),
            response_preview=None,
        )


async def run_all_tests(
    only_get: bool = True,
    specific_endpoint: Optional[str] = None,
    save_responses: bool = False,
) -> TestReport:
    """Run tests on all endpoints from OpenAPI spec."""
    
    # Load OpenAPI spec
    if not OPENAPI_FILE.exists():
        print(f"❌ OpenAPI file not found: {OPENAPI_FILE}")
        print("   Run: python backend/scripts/test_manager_openapi.py")
        return None
    
    with open(OPENAPI_FILE) as f:
        spec = json.load(f)
    
    paths = spec.get("paths", {})
    print(f"📋 Loaded {len(paths)} endpoints from OpenAPI spec")
    
    # Filter endpoints
    endpoints_to_test = []
    for path, methods in paths.items():
        for method in methods.keys():
            method_upper = method.upper()
            
            # Skip non-GET if only_get is True
            if only_get and method_upper != "GET":
                continue
            
            # Skip if specific endpoint requested and doesn't match
            if specific_endpoint and path != specific_endpoint:
                continue
            
            # Skip form endpoints with {key} - they need a valid key
            if "{key}" in path:
                continue
            
            # Skip form endpoints for GET (they need POST)
            if method_upper == "GET" and "-form" in path:
                continue
                
            # Skip view endpoints (they need a key from form)
            if "-view" in path:
                continue
            
            endpoints_to_test.append((path, method_upper))
    
    print(f"🧪 Testing {len(endpoints_to_test)} endpoints...")
    print()
    
    results = []
    successful = 0
    failed = 0
    
    async with httpx.AsyncClient(
        timeout=30.0,
        verify=False,
        headers={
            "X-API-KEY": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    ) as client:
        
        for i, (endpoint, method) in enumerate(endpoints_to_test, 1):
            print(f"[{i:3}/{len(endpoints_to_test)}] {method:6} {endpoint:50}", end=" ")
            
            result = await test_endpoint(client, endpoint, method)
            results.append(result)
            
            if result.success:
                successful += 1
                data_info = ""
                if result.data_key:
                    data_info = f" → {result.data_key}[{result.record_count}]"
                elif result.record_count is not None:
                    data_info = f" → [{result.record_count}]"
                print(f"✅ {result.status_code}{data_info}")
            else:
                failed += 1
                print(f"❌ {result.status_code} - {result.error_message[:50] if result.error_message else 'Unknown error'}")
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
    
    report = TestReport(
        timestamp=datetime.now().isoformat(),
        base_url=BASE_URL,
        total_endpoints=len(paths),
        tested_endpoints=len(endpoints_to_test),
        successful=successful,
        failed=failed,
        skipped=len(paths) - len(endpoints_to_test),
        results=results,
    )
    
    return report


def print_report(report: TestReport) -> None:
    """Print a summary report."""
    print()
    print("=" * 70)
    print("TEST REPORT SUMMARY")
    print("=" * 70)
    print(f"Timestamp:    {report.timestamp}")
    print(f"Base URL:     {report.base_url}")
    print(f"Total:        {report.total_endpoints} endpoints in OpenAPI spec")
    print(f"Tested:       {report.tested_endpoints}")
    print(f"Successful:   {report.successful} ✅")
    print(f"Failed:       {report.failed} ❌")
    print(f"Skipped:      {report.skipped}")
    print()
    
    # Group by success/failure
    successful = [r for r in report.results if r.success]
    failed = [r for r in report.results if not r.success]
    
    if successful:
        print("=" * 70)
        print("SUCCESSFUL ENDPOINTS")
        print("=" * 70)
        for r in successful:
            data_info = ""
            if r.data_key:
                data_info = f"→ {r.data_key}"
                if r.sample_record_keys:
                    keys_preview = ", ".join(r.sample_record_keys[:5])
                    if len(r.sample_record_keys) > 5:
                        keys_preview += f"... (+{len(r.sample_record_keys)-5})"
                    data_info += f" [{keys_preview}]"
            print(f"  {r.method:6} {r.endpoint:45} {data_info}")
    
    if failed:
        print()
        print("=" * 70)
        print("FAILED ENDPOINTS")
        print("=" * 70)
        for r in failed:
            print(f"  {r.method:6} {r.endpoint:45} {r.status_code} - {r.error_message[:30] if r.error_message else ''}")


def save_report(report: TestReport, save_responses: bool = False) -> None:
    """Save report to files."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Save full report as JSON
    report_file = OUTPUT_DIR / "endpoint_test_report.json"
    with open(report_file, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"\n📄 Full report saved to: {report_file}")
    
    # Save endpoint metadata (for agent use)
    metadata = {}
    for r in report.results:
        if r.success:
            metadata[r.endpoint] = {
                "method": r.method,
                "data_key": r.data_key,
                "record_keys": r.sample_record_keys,
            }
    
    metadata_file = OUTPUT_DIR / "endpoint_metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"📄 Endpoint metadata saved to: {metadata_file}")
    
    # Save working endpoints list
    working_file = OUTPUT_DIR / "working_endpoints.txt"
    with open(working_file, "w") as f:
        for r in report.results:
            if r.success:
                f.write(f"{r.method} {r.endpoint}\n")
    print(f"📄 Working endpoints list saved to: {working_file}")


# =============================================================================
# Main
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Test all Manager.io API endpoints")
    parser.add_argument("--only-get", action="store_true", default=True,
                       help="Only test GET endpoints (default: True)")
    parser.add_argument("--all-methods", action="store_true",
                       help="Test all HTTP methods (GET, POST, PUT, DELETE)")
    parser.add_argument("--save-responses", action="store_true",
                       help="Save full responses to files")
    parser.add_argument("--endpoint", type=str,
                       help="Test a specific endpoint only")
    args = parser.parse_args()
    
    only_get = not args.all_methods
    
    print("=" * 70)
    print("MANAGER.IO API ENDPOINT TESTER")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")
    print(f"Mode: {'GET only' if only_get else 'All methods'}")
    print()
    
    report = await run_all_tests(
        only_get=only_get,
        specific_endpoint=args.endpoint,
        save_responses=args.save_responses,
    )
    
    if report:
        print_report(report)
        save_report(report, args.save_responses)
        
        print()
        print("=" * 70)
        print("DONE!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
