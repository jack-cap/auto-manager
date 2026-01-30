#!/usr/bin/env python3
"""Test script to discover the correct payment structure for paying purchase invoices."""

import asyncio
import httpx
import json

# Read-only API key
BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")
API_KEY = os.getenv("MANAGER_READ_API_KEY", "")


async def main():
    async with httpx.AsyncClient(
        timeout=30.0,
        verify=False,
        headers={
            "X-API-KEY": API_KEY,
            "Content-Type": "application/json",
        },
    ) as client:
        # Get payments
        print("=== FETCHING PAYMENTS ===")
        response = await client.get(f"{BASE_URL}/payments?pageSize=10")
        payments = response.json()
        
        print(f"Total payments: {payments.get('totalRecords', 0)}")
        
        # Find a payment that might be linked to an invoice
        for payment in payments.get("payments", [])[:5]:
            print(f"\n--- Payment: {payment.get('date')} - {payment.get('payee')} - {payment.get('amount')} ---")
            
            # Get the full form to see all fields
            payment_key = payment.get("key")
            form_response = await client.get(f"{BASE_URL}/payment-form/{payment_key}")
            form_data = form_response.json()
            
            print("Full payment form structure:")
            print(json.dumps(form_data, indent=2, default=str))
            
            # Check if it has Lines with PurchaseInvoice
            lines = form_data.get("Lines", [])
            for i, line in enumerate(lines):
                print(f"\n  Line {i+1} keys: {list(line.keys())}")
                if "PurchaseInvoice" in line or "AccountsPayableSupplier" in line:
                    print(f"  *** FOUND INVOICE PAYMENT LINE ***")
                    print(f"  Line data: {json.dumps(line, indent=4)}")
            
            print("\n" + "="*60)


if __name__ == "__main__":
    asyncio.run(main())
