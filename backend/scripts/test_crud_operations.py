#!/usr/bin/env python3
"""
Test CRUD (Create, Read, Update, Delete) operations on Manager.io API.

This script tests write operations using a blank test company.
It creates records, reads them back, updates them, and deletes them.

Usage:
    python scripts/test_crud_operations.py
    python scripts/test_crud_operations.py --keep  # Don't delete created records
"""

import asyncio
import json
import argparse
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx


# =============================================================================
# Configuration
# =============================================================================

# Load from environment or use defaults for local testing
import os
from dotenv import load_dotenv

# Try to load from .env.test file
load_dotenv(SCRIPT_DIR / ".env.test")

BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")

# READ-ONLY: 
READ_API_KEY = os.getenv("MANAGER_READ_API_KEY", "")

# WRITE: 
WRITE_API_KEY = os.getenv("MANAGER_WRITE_API_KEY", "")

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "test_results"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CRUDResult:
    """Result of a CRUD operation."""
    entity: str
    operation: str
    success: bool
    key: Optional[str]
    status_code: int
    error_message: Optional[str]
    response_data: Optional[Dict]


# =============================================================================
# Helper Functions
# =============================================================================

def get_today() -> str:
    """Get today's date in YYYY-MM-DD format."""
    return date.today().isoformat()


async def create_record(
    client: httpx.AsyncClient,
    form_endpoint: str,
    data: Dict,
) -> CRUDResult:
    """Create a record using a form endpoint."""
    url = f"{BASE_URL}{form_endpoint}"
    
    try:
        response = await client.post(url, json=data)
        
        if response.is_success:
            resp_data = response.json()
            key = resp_data.get("Key")
            return CRUDResult(
                entity=form_endpoint,
                operation="CREATE",
                success=True,
                key=key,
                status_code=response.status_code,
                error_message=None,
                response_data=resp_data,
            )
        else:
            return CRUDResult(
                entity=form_endpoint,
                operation="CREATE",
                success=False,
                key=None,
                status_code=response.status_code,
                error_message=response.text[:500],
                response_data=None,
            )
    except Exception as e:
        return CRUDResult(
            entity=form_endpoint,
            operation="CREATE",
            success=False,
            key=None,
            status_code=0,
            error_message=str(e),
            response_data=None,
        )


async def read_record(
    client: httpx.AsyncClient,
    form_endpoint: str,
    key: str,
) -> CRUDResult:
    """Read a record using a form endpoint with key."""
    url = f"{BASE_URL}{form_endpoint}/{key}"
    
    try:
        response = await client.get(url)
        
        if response.is_success:
            resp_data = response.json()
            return CRUDResult(
                entity=form_endpoint,
                operation="READ",
                success=True,
                key=key,
                status_code=response.status_code,
                error_message=None,
                response_data=resp_data,
            )
        else:
            return CRUDResult(
                entity=form_endpoint,
                operation="READ",
                success=False,
                key=key,
                status_code=response.status_code,
                error_message=response.text[:500],
                response_data=None,
            )
    except Exception as e:
        return CRUDResult(
            entity=form_endpoint,
            operation="READ",
            success=False,
            key=key,
            status_code=0,
            error_message=str(e),
            response_data=None,
        )


async def update_record(
    client: httpx.AsyncClient,
    form_endpoint: str,
    key: str,
    data: Dict,
) -> CRUDResult:
    """Update a record using a form endpoint with key."""
    url = f"{BASE_URL}{form_endpoint}/{key}"
    
    try:
        response = await client.put(url, json=data)
        
        if response.is_success:
            resp_data = response.json() if response.text else {}
            return CRUDResult(
                entity=form_endpoint,
                operation="UPDATE",
                success=True,
                key=key,
                status_code=response.status_code,
                error_message=None,
                response_data=resp_data,
            )
        else:
            return CRUDResult(
                entity=form_endpoint,
                operation="UPDATE",
                success=False,
                key=key,
                status_code=response.status_code,
                error_message=response.text[:500],
                response_data=None,
            )
    except Exception as e:
        return CRUDResult(
            entity=form_endpoint,
            operation="UPDATE",
            success=False,
            key=key,
            status_code=0,
            error_message=str(e),
            response_data=None,
        )


async def delete_record(
    client: httpx.AsyncClient,
    form_endpoint: str,
    key: str,
) -> CRUDResult:
    """Delete a record using a form endpoint with key."""
    url = f"{BASE_URL}{form_endpoint}/{key}"
    
    try:
        response = await client.delete(url)
        
        if response.is_success:
            return CRUDResult(
                entity=form_endpoint,
                operation="DELETE",
                success=True,
                key=key,
                status_code=response.status_code,
                error_message=None,
                response_data=None,
            )
        else:
            return CRUDResult(
                entity=form_endpoint,
                operation="DELETE",
                success=False,
                key=key,
                status_code=response.status_code,
                error_message=response.text[:500],
                response_data=None,
            )
    except Exception as e:
        return CRUDResult(
            entity=form_endpoint,
            operation="DELETE",
            success=False,
            key=key,
            status_code=0,
            error_message=str(e),
            response_data=None,
        )


# =============================================================================
# Test Cases
# =============================================================================

async def test_supplier_crud(client: httpx.AsyncClient, keep: bool = False) -> List[CRUDResult]:
    """Test CRUD operations on suppliers."""
    results = []
    form_endpoint = "/supplier-form"
    
    print("\n" + "=" * 60)
    print("Testing Supplier CRUD")
    print("=" * 60)
    
    # CREATE
    create_data = {
        "Name": f"Test Supplier {datetime.now().strftime('%H%M%S')}",
        "Code": f"TEST{datetime.now().strftime('%H%M%S')}",
    }
    print(f"  CREATE: {create_data['Name']}", end=" ")
    result = await create_record(client, form_endpoint, create_data)
    results.append(result)
    if result.success:
        print(f"✅ Key: {result.key[:8]}...")
        key = result.key
        
        # READ
        print(f"  READ:   {key[:8]}...", end=" ")
        result = await read_record(client, form_endpoint, key)
        results.append(result)
        if result.success:
            print(f"✅ Name: {result.response_data.get('Name')}")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # UPDATE
        update_data = {
            "Name": f"Updated Supplier {datetime.now().strftime('%H%M%S')}",
            "Code": create_data["Code"],
        }
        print(f"  UPDATE: {update_data['Name']}", end=" ")
        result = await update_record(client, form_endpoint, key, update_data)
        results.append(result)
        if result.success:
            print(f"✅")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # DELETE (unless --keep)
        if not keep:
            print(f"  DELETE: {key[:8]}...", end=" ")
            result = await delete_record(client, form_endpoint, key)
            results.append(result)
            if result.success:
                print(f"✅")
            else:
                print(f"❌ {result.status_code} - {result.error_message[:50]}")
        else:
            print(f"  DELETE: Skipped (--keep)")
    else:
        print(f"❌ {result.status_code} - {result.error_message[:50] if result.error_message else 'Unknown'}")
    
    return results


async def test_customer_crud(client: httpx.AsyncClient, keep: bool = False) -> List[CRUDResult]:
    """Test CRUD operations on customers."""
    results = []
    form_endpoint = "/customer-form"
    
    print("\n" + "=" * 60)
    print("Testing Customer CRUD")
    print("=" * 60)
    
    # CREATE
    create_data = {
        "Name": f"Test Customer {datetime.now().strftime('%H%M%S')}",
    }
    print(f"  CREATE: {create_data['Name']}", end=" ")
    result = await create_record(client, form_endpoint, create_data)
    results.append(result)
    if result.success:
        print(f"✅ Key: {result.key[:8]}...")
        key = result.key
        
        # READ
        print(f"  READ:   {key[:8]}...", end=" ")
        result = await read_record(client, form_endpoint, key)
        results.append(result)
        if result.success:
            print(f"✅ Name: {result.response_data.get('Name')}")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # UPDATE
        update_data = {
            "Name": f"Updated Customer {datetime.now().strftime('%H%M%S')}",
        }
        print(f"  UPDATE: {update_data['Name']}", end=" ")
        result = await update_record(client, form_endpoint, key, update_data)
        results.append(result)
        if result.success:
            print(f"✅")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # DELETE
        if not keep:
            print(f"  DELETE: {key[:8]}...", end=" ")
            result = await delete_record(client, form_endpoint, key)
            results.append(result)
            if result.success:
                print(f"✅")
            else:
                print(f"❌ {result.status_code} - {result.error_message[:50]}")
        else:
            print(f"  DELETE: Skipped (--keep)")
    else:
        print(f"❌ {result.status_code} - {result.error_message[:50] if result.error_message else 'Unknown'}")
    
    return results


async def test_project_crud(client: httpx.AsyncClient, keep: bool = False) -> List[CRUDResult]:
    """Test CRUD operations on projects."""
    results = []
    form_endpoint = "/project-form"
    
    print("\n" + "=" * 60)
    print("Testing Project CRUD")
    print("=" * 60)
    
    # CREATE
    create_data = {
        "Name": f"Test Project {datetime.now().strftime('%H%M%S')}",
    }
    print(f"  CREATE: {create_data['Name']}", end=" ")
    result = await create_record(client, form_endpoint, create_data)
    results.append(result)
    if result.success:
        print(f"✅ Key: {result.key[:8]}...")
        key = result.key
        
        # READ
        print(f"  READ:   {key[:8]}...", end=" ")
        result = await read_record(client, form_endpoint, key)
        results.append(result)
        if result.success:
            print(f"✅ Name: {result.response_data.get('Name')}")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # UPDATE
        update_data = {
            "Name": f"Updated Project {datetime.now().strftime('%H%M%S')}",
        }
        print(f"  UPDATE: {update_data['Name']}", end=" ")
        result = await update_record(client, form_endpoint, key, update_data)
        results.append(result)
        if result.success:
            print(f"✅")
        else:
            print(f"❌ {result.status_code} - {result.error_message[:50]}")
        
        # DELETE
        if not keep:
            print(f"  DELETE: {key[:8]}...", end=" ")
            result = await delete_record(client, form_endpoint, key)
            results.append(result)
            if result.success:
                print(f"✅")
            else:
                print(f"❌ {result.status_code} - {result.error_message[:50]}")
        else:
            print(f"  DELETE: Skipped (--keep)")
    else:
        print(f"❌ {result.status_code} - {result.error_message[:50] if result.error_message else 'Unknown'}")
    
    return results


async def test_journal_entry_crud(client: httpx.AsyncClient, keep: bool = False) -> List[CRUDResult]:
    """Test CRUD operations on journal entries."""
    results = []
    form_endpoint = "/journal-entry-form"
    
    print("\n" + "=" * 60)
    print("Testing Journal Entry CRUD")
    print("=" * 60)
    
    # First, we need to get chart of accounts to find valid account keys
    print("  Fetching chart of accounts...", end=" ")
    try:
        response = await client.get(f"{BASE_URL}/chart-of-accounts")
        if response.is_success:
            accounts = response.json().get("chartOfAccounts", [])
            print(f"✅ Found {len(accounts)} accounts")
            
            if len(accounts) >= 2:
                # Use first two accounts for debit/credit
                debit_account = accounts[0]["key"]
                credit_account = accounts[1]["key"]
                
                # CREATE
                create_data = {
                    "Date": get_today(),
                    "Narration": f"Test Journal Entry {datetime.now().strftime('%H%M%S')}",
                    "Lines": [
                        {
                            "Account": debit_account,
                            "Debit": 100.00,
                        },
                        {
                            "Account": credit_account,
                            "Credit": 100.00,
                        },
                    ],
                }
                print(f"  CREATE: {create_data['Narration']}", end=" ")
                result = await create_record(client, form_endpoint, create_data)
                results.append(result)
                if result.success:
                    print(f"✅ Key: {result.key[:8]}...")
                    key = result.key
                    
                    # READ
                    print(f"  READ:   {key[:8]}...", end=" ")
                    result = await read_record(client, form_endpoint, key)
                    results.append(result)
                    if result.success:
                        print(f"✅ Narration: {result.response_data.get('Narration')}")
                    else:
                        print(f"❌ {result.status_code} - {result.error_message[:50]}")
                    
                    # UPDATE
                    update_data = {
                        "Date": get_today(),
                        "Narration": f"Updated Journal Entry {datetime.now().strftime('%H%M%S')}",
                        "Lines": create_data["Lines"],
                    }
                    print(f"  UPDATE: {update_data['Narration']}", end=" ")
                    result = await update_record(client, form_endpoint, key, update_data)
                    results.append(result)
                    if result.success:
                        print(f"✅")
                    else:
                        print(f"❌ {result.status_code} - {result.error_message[:50]}")
                    
                    # DELETE
                    if not keep:
                        print(f"  DELETE: {key[:8]}...", end=" ")
                        result = await delete_record(client, form_endpoint, key)
                        results.append(result)
                        if result.success:
                            print(f"✅")
                        else:
                            print(f"❌ {result.status_code} - {result.error_message[:50]}")
                    else:
                        print(f"  DELETE: Skipped (--keep)")
                else:
                    print(f"❌ {result.status_code} - {result.error_message[:50] if result.error_message else 'Unknown'}")
            else:
                print("  ⚠️  Not enough accounts to create journal entry")
        else:
            print(f"❌ {response.status_code}")
    except Exception as e:
        print(f"❌ {e}")
    
    return results


async def test_report_form_view(client: httpx.AsyncClient) -> List[CRUDResult]:
    """Test report form/view pattern (POST form → GET view)."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing Report Form/View Pattern")
    print("=" * 60)
    
    reports = [
        ("/general-ledger-summary-form", "/general-ledger-summary-view", {}),
        ("/aged-receivables-form", "/aged-receivables-view", {}),
        ("/aged-payables-form", "/aged-payables-view", {}),
    ]
    
    for form_endpoint, view_endpoint, form_data in reports:
        report_name = form_endpoint.replace("-form", "").replace("/", "")
        print(f"  {report_name}:", end=" ")
        
        # POST to form to get key
        try:
            response = await client.post(f"{BASE_URL}{form_endpoint}", json=form_data)
            if response.is_success:
                resp_data = response.json()
                key = resp_data.get("Key")
                if key:
                    # GET view with key
                    view_response = await client.get(f"{BASE_URL}{view_endpoint}/{key}")
                    if view_response.is_success:
                        view_data = view_response.json()
                        print(f"✅ Form Key: {key[:8]}... View keys: {list(view_data.keys())[:3]}")
                        results.append(CRUDResult(
                            entity=report_name,
                            operation="FORM_VIEW",
                            success=True,
                            key=key,
                            status_code=view_response.status_code,
                            error_message=None,
                            response_data={"form_key": key, "view_keys": list(view_data.keys())},
                        ))
                    else:
                        print(f"❌ View failed: {view_response.status_code}")
                        results.append(CRUDResult(
                            entity=report_name,
                            operation="FORM_VIEW",
                            success=False,
                            key=key,
                            status_code=view_response.status_code,
                            error_message=view_response.text[:200],
                            response_data=None,
                        ))
                else:
                    print(f"❌ No key returned from form")
            else:
                print(f"❌ Form failed: {response.status_code}")
                results.append(CRUDResult(
                    entity=report_name,
                    operation="FORM_VIEW",
                    success=False,
                    key=None,
                    status_code=response.status_code,
                    error_message=response.text[:200],
                    response_data=None,
                ))
        except Exception as e:
            print(f"❌ {e}")
            results.append(CRUDResult(
                entity=report_name,
                operation="FORM_VIEW",
                success=False,
                key=None,
                status_code=0,
                error_message=str(e),
                response_data=None,
            ))
    
    return results


async def test_form_get_with_key(client: httpx.AsyncClient) -> List[CRUDResult]:
    """Test GET form/{key} endpoints by creating records first."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing Form GET with Key (Create → Read)")
    print("=" * 60)
    
    # Test various form endpoints
    form_tests = [
        # (form_endpoint, create_data, name_field)
        ("/supplier-form", {"Name": "Test Supplier for GET", "Code": "TESTGET"}, "Name"),
        ("/customer-form", {"Name": "Test Customer for GET"}, "Name"),
        ("/project-form", {"Name": "Test Project for GET"}, "Name"),
        ("/employee-form", {"Name": "Test Employee for GET"}, "Name"),
        ("/division-form", {"Name": "Test Division for GET"}, "Name"),
    ]
    
    for form_endpoint, create_data, name_field in form_tests:
        entity_name = form_endpoint.replace("-form", "").replace("/", "")
        print(f"  {entity_name}:", end=" ")
        
        try:
            # CREATE
            response = await client.post(f"{BASE_URL}{form_endpoint}", json=create_data)
            if response.is_success:
                resp_data = response.json()
                key = resp_data.get("Key")
                if key:
                    # GET with key
                    get_response = await client.get(f"{BASE_URL}{form_endpoint}/{key}")
                    if get_response.is_success:
                        get_data = get_response.json()
                        name = get_data.get(name_field, "?")
                        print(f"✅ Created & Read: {name} (Key: {key[:8]}...)")
                        results.append(CRUDResult(
                            entity=entity_name,
                            operation="FORM_GET",
                            success=True,
                            key=key,
                            status_code=get_response.status_code,
                            error_message=None,
                            response_data={"name": name, "keys": list(get_data.keys())[:10]},
                        ))
                        
                        # Cleanup - DELETE
                        await client.delete(f"{BASE_URL}{form_endpoint}/{key}")
                    else:
                        print(f"❌ GET failed: {get_response.status_code} - {get_response.text[:100]}")
                        results.append(CRUDResult(
                            entity=entity_name,
                            operation="FORM_GET",
                            success=False,
                            key=key,
                            status_code=get_response.status_code,
                            error_message=get_response.text[:200],
                            response_data=None,
                        ))
                        # Cleanup
                        await client.delete(f"{BASE_URL}{form_endpoint}/{key}")
                else:
                    print(f"❌ No key returned")
            else:
                print(f"❌ Create failed: {response.status_code} - {response.text[:100]}")
                results.append(CRUDResult(
                    entity=entity_name,
                    operation="FORM_GET",
                    success=False,
                    key=None,
                    status_code=response.status_code,
                    error_message=response.text[:200],
                    response_data=None,
                ))
        except Exception as e:
            print(f"❌ {e}")
            results.append(CRUDResult(
                entity=entity_name,
                operation="FORM_GET",
                success=False,
                key=None,
                status_code=0,
                error_message=str(e),
                response_data=None,
            ))
    
    return results


# =============================================================================
# Main
# =============================================================================

async def main(keep: bool = False):
    """Run all CRUD tests."""
    print("=" * 70)
    print("MANAGER.IO CRUD OPERATIONS TESTER")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")
    print(f"Using WRITE API key for blank test company")
    print(f"Keep records: {keep}")
    print()
    
    all_results = []
    
    async with httpx.AsyncClient(
        timeout=30.0,
        verify=False,
        headers={
            "X-API-KEY": WRITE_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    ) as client:
        
        # Test master data CRUD
        all_results.extend(await test_supplier_crud(client, keep))
        all_results.extend(await test_customer_crud(client, keep))
        all_results.extend(await test_project_crud(client, keep))
        
        # Test transaction CRUD
        all_results.extend(await test_journal_entry_crud(client, keep))
        
        # Test report form/view pattern
        all_results.extend(await test_report_form_view(client))
        
        # Test form GET with key (create → read)
        all_results.extend(await test_form_get_with_key(client))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    successful = [r for r in all_results if r.success]
    failed = [r for r in all_results if not r.success]
    
    print(f"Total operations: {len(all_results)}")
    print(f"Successful: {len(successful)} ✅")
    print(f"Failed: {len(failed)} ❌")
    
    if failed:
        print("\nFailed operations:")
        for r in failed:
            print(f"  - {r.operation} {r.entity}: {r.status_code} - {r.error_message[:50] if r.error_message else 'Unknown'}")
    
    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    results_file = OUTPUT_DIR / "crud_test_results.json"
    with open(results_file, "w") as f:
        json.dump([asdict(r) for r in all_results], f, indent=2, default=str)
    print(f"\n📄 Results saved to: {results_file}")
    
    print("\n" + "=" * 70)
    print("DONE!")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Manager.io CRUD operations")
    parser.add_argument("--keep", action="store_true",
                       help="Don't delete created records (for inspection)")
    args = parser.parse_args()
    
    asyncio.run(main(keep=args.keep))
