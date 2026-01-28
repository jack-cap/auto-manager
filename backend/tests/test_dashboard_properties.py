"""Property-based tests for dashboard calculations.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper

Properties tested:
- Property 15: Dashboard Balance Calculation
- Property 16: Date Range Filtering
"""

from datetime import date, timedelta
from typing import Dict, List, Any
from collections import defaultdict

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st, assume

from app.api.endpoints.dashboard import (
    filter_by_date_range,
    calculate_running_balance,
    parse_date,
)


# =============================================================================
# Custom Strategies
# =============================================================================

# Date strategy - generates dates within a reasonable range
date_strategy = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)

# Amount strategy - generates realistic monetary amounts
amount_strategy = st.floats(
    min_value=0.01,
    max_value=1_000_000.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda x: round(x, 2))

# Transaction type strategy
transaction_type_strategy = st.sampled_from(['payment', 'receipt', 'transfer'])

# Account key strategy - UUID-like strings
account_key_strategy = st.uuids().map(str)


def transaction_strategy(date_range: tuple = None):
    """Generate a single transaction record."""
    if date_range:
        start, end = date_range
        txn_date = st.dates(min_value=start, max_value=end)
    else:
        txn_date = date_strategy
    
    return st.fixed_dictionaries({
        'Date': txn_date.map(lambda d: d.isoformat()),
        'Amount': amount_strategy,
        'Account': account_key_strategy,
        'Description': st.text(min_size=0, max_size=100),
    })


# List of transactions strategy
transactions_list_strategy = st.lists(
    transaction_strategy(),
    min_size=0,
    max_size=100,
)


# =============================================================================
# Property 15: Dashboard Balance Calculation
# =============================================================================

class TestDashboardBalanceCalculationProperty:
    """Property 15: Dashboard Balance Calculation
    
    For any set of payments, receipts, transfers, and journal entries,
    calculating account balances SHALL produce running totals where the
    final balance equals the sum of all credits minus all debits for each account.
    
    **Validates: Requirements 7.1, 7.8**
    """
    
    @given(
        receipts=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
                'Account': account_key_strategy,
            }),
            min_size=0,
            max_size=50,
        ),
        payments=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
                'Account': account_key_strategy,
            }),
            min_size=0,
            max_size=50,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_balance_equals_credits_minus_debits(
        self,
        receipts: List[Dict[str, Any]],
        payments: List[Dict[str, Any]],
    ):
        """Feature: manager-io-bookkeeper, Property 15: Dashboard Balance Calculation
        
        Final balance should equal sum of all credits minus sum of all debits.
        **Validates: Requirements 7.1, 7.8**
        """
        # Calculate expected balance per account
        expected_balances: Dict[str, float] = defaultdict(float)
        
        # Receipts are credits (add to balance)
        for receipt in receipts:
            account = receipt['Account']
            amount = receipt['Amount']
            expected_balances[account] += amount
        
        # Payments are debits (subtract from balance)
        for payment in payments:
            account = payment['Account']
            amount = payment['Amount']
            expected_balances[account] -= amount
        
        # Calculate actual balance using the helper function
        actual_credit_total = calculate_running_balance(receipts, is_credit=True)
        actual_debit_total = calculate_running_balance(payments, is_credit=False)
        
        # Property: Total credits from receipts
        expected_credit_total = sum(r['Amount'] for r in receipts)
        assert abs(actual_credit_total - expected_credit_total) < 0.01, \
            f"Credit total mismatch: {actual_credit_total} != {expected_credit_total}"
        
        # Property: Total debits from payments (negative)
        expected_debit_total = -sum(p['Amount'] for p in payments)
        assert abs(actual_debit_total - expected_debit_total) < 0.01, \
            f"Debit total mismatch: {actual_debit_total} != {expected_debit_total}"
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=1,
            max_size=100,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_running_balance_is_cumulative(
        self,
        transactions: List[Dict[str, Any]],
    ):
        """Feature: manager-io-bookkeeper, Property 15: Dashboard Balance Calculation
        
        Running balance should be cumulative sum of all transaction amounts.
        **Validates: Requirements 7.8**
        """
        # Calculate expected cumulative sum
        expected_total = sum(t['Amount'] for t in transactions)
        
        # Calculate using helper (as credits)
        actual_total = calculate_running_balance(transactions, is_credit=True)
        
        # Property: Running balance equals cumulative sum
        assert abs(actual_total - expected_total) < 0.01, \
            f"Running balance mismatch: {actual_total} != {expected_total}"
    
    @given(
        amounts=st.lists(
            amount_strategy,
            min_size=0,
            max_size=100,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_empty_transactions_yields_zero_balance(
        self,
        amounts: List[float],
    ):
        """Feature: manager-io-bookkeeper, Property 15: Dashboard Balance Calculation
        
        Empty transaction list should yield zero balance.
        **Validates: Requirements 7.1**
        """
        # Empty list
        empty_transactions: List[Dict[str, Any]] = []
        
        # Property: Empty transactions = zero balance
        balance = calculate_running_balance(empty_transactions, is_credit=True)
        assert balance == 0.0, f"Empty transactions should yield zero, got {balance}"
    
    @given(
        receipts=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
                'Account': account_key_strategy,
            }),
            min_size=1,
            max_size=50,
        ),
        payments=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
                'Account': account_key_strategy,
            }),
            min_size=1,
            max_size=50,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_net_balance_is_receipts_minus_payments(
        self,
        receipts: List[Dict[str, Any]],
        payments: List[Dict[str, Any]],
    ):
        """Feature: manager-io-bookkeeper, Property 15: Dashboard Balance Calculation
        
        Net balance should equal total receipts minus total payments.
        **Validates: Requirements 7.1, 7.8**
        """
        # Calculate totals
        total_receipts = sum(r['Amount'] for r in receipts)
        total_payments = sum(p['Amount'] for p in payments)
        expected_net = total_receipts - total_payments
        
        # Calculate using helper functions
        credit_balance = calculate_running_balance(receipts, is_credit=True)
        debit_balance = calculate_running_balance(payments, is_credit=False)
        actual_net = credit_balance + debit_balance
        
        # Property: Net balance = receipts - payments
        assert abs(actual_net - expected_net) < 0.01, \
            f"Net balance mismatch: {actual_net} != {expected_net}"


# =============================================================================
# Property 16: Date Range Filtering
# =============================================================================

class TestDateRangeFilteringProperty:
    """Property 16: Date Range Filtering
    
    For any date range [start, end] applied to dashboard data, all returned
    data points SHALL have dates within the inclusive range [start, end].
    
    **Validates: Requirements 7.7**
    """
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=0,
            max_size=100,
        ),
        start_date=date_strategy,
        end_date=date_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_filtered_dates_within_range(
        self,
        transactions: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        All filtered records should have dates within [start, end] inclusive.
        **Validates: Requirements 7.7**
        """
        # Ensure start <= end
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        
        # Apply filter
        filtered = filter_by_date_range(transactions, start_date, end_date)
        
        # Property: All filtered dates are within range
        for record in filtered:
            record_date = parse_date(record['Date'])
            assert record_date is not None, "Filtered record should have valid date"
            assert start_date <= record_date <= end_date, \
                f"Date {record_date} not in range [{start_date}, {end_date}]"
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=1,
            max_size=100,
        ),
        start_date=date_strategy,
        end_date=date_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_no_records_outside_range_included(
        self,
        transactions: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        No records outside the date range should be included.
        **Validates: Requirements 7.7**
        """
        # Ensure start <= end
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        
        # Apply filter
        filtered = filter_by_date_range(transactions, start_date, end_date)
        filtered_dates = {record['Date'] for record in filtered}
        
        # Check that no excluded records are in the filtered set
        for record in transactions:
            record_date = parse_date(record['Date'])
            if record_date is not None:
                if record_date < start_date or record_date > end_date:
                    assert record['Date'] not in filtered_dates, \
                        f"Record with date {record['Date']} should be excluded"
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=0,
            max_size=100,
        ),
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_no_filter_returns_all_records(
        self,
        transactions: List[Dict[str, Any]],
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        No date filter should return all records.
        **Validates: Requirements 7.7**
        """
        # Apply filter with no dates
        filtered = filter_by_date_range(transactions, None, None)
        
        # Property: All records returned when no filter
        assert len(filtered) == len(transactions), \
            f"Expected {len(transactions)} records, got {len(filtered)}"
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=0,
            max_size=100,
        ),
        end_date=date_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_only_end_date_filter(
        self,
        transactions: List[Dict[str, Any]],
        end_date: date,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        Only end date filter should include all records up to end date.
        **Validates: Requirements 7.7**
        """
        # Apply filter with only end date
        filtered = filter_by_date_range(transactions, None, end_date)
        
        # Property: All filtered dates <= end_date
        for record in filtered:
            record_date = parse_date(record['Date'])
            if record_date is not None:
                assert record_date <= end_date, \
                    f"Date {record_date} should be <= {end_date}"
    
    @given(
        transactions=st.lists(
            st.fixed_dictionaries({
                'Date': date_strategy.map(lambda d: d.isoformat()),
                'Amount': amount_strategy,
            }),
            min_size=0,
            max_size=100,
        ),
        start_date=date_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_only_start_date_filter(
        self,
        transactions: List[Dict[str, Any]],
        start_date: date,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        Only start date filter should include all records from start date.
        **Validates: Requirements 7.7**
        """
        # Apply filter with only start date
        filtered = filter_by_date_range(transactions, start_date, None)
        
        # Property: All filtered dates >= start_date
        for record in filtered:
            record_date = parse_date(record['Date'])
            if record_date is not None:
                assert record_date >= start_date, \
                    f"Date {record_date} should be >= {start_date}"
    
    @given(
        single_date=date_strategy,
        amount=amount_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_single_day_range_includes_exact_date(
        self,
        single_date: date,
        amount: float,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        Single day range should include records on that exact date.
        **Validates: Requirements 7.7**
        """
        # Create transaction on the exact date
        transactions = [{'Date': single_date.isoformat(), 'Amount': amount}]
        
        # Apply filter with same start and end date
        filtered = filter_by_date_range(transactions, single_date, single_date)
        
        # Property: Record on exact date should be included
        assert len(filtered) == 1, \
            f"Expected 1 record for single day range, got {len(filtered)}"
    
    @given(
        base_date=date_strategy,
        days_before=st.integers(min_value=1, max_value=30),
        days_after=st.integers(min_value=1, max_value=30),
        amount=amount_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_boundary_dates_included(
        self,
        base_date: date,
        days_before: int,
        days_after: int,
        amount: float,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        Boundary dates (start and end) should be included in the range.
        **Validates: Requirements 7.7**
        """
        start_date = base_date - timedelta(days=days_before)
        end_date = base_date + timedelta(days=days_after)
        
        # Create transactions on boundary dates
        transactions = [
            {'Date': start_date.isoformat(), 'Amount': amount},
            {'Date': end_date.isoformat(), 'Amount': amount},
            {'Date': base_date.isoformat(), 'Amount': amount},
        ]
        
        # Apply filter
        filtered = filter_by_date_range(transactions, start_date, end_date)
        
        # Property: All boundary dates should be included
        assert len(filtered) == 3, \
            f"Expected 3 records (boundaries + middle), got {len(filtered)}"
    
    @given(
        start_date=date_strategy,
        end_date=date_strategy,
        amount=amount_strategy,
    )
    @hyp_settings(max_examples=100, deadline=None)
    def test_dates_outside_range_excluded(
        self,
        start_date: date,
        end_date: date,
        amount: float,
    ):
        """Feature: manager-io-bookkeeper, Property 16: Date Range Filtering
        
        Dates outside the range should be excluded.
        **Validates: Requirements 7.7**
        """
        # Ensure start <= end
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        
        # Create transactions outside the range
        before_start = start_date - timedelta(days=1)
        after_end = end_date + timedelta(days=1)
        
        transactions = [
            {'Date': before_start.isoformat(), 'Amount': amount},
            {'Date': after_end.isoformat(), 'Amount': amount},
        ]
        
        # Apply filter
        filtered = filter_by_date_range(transactions, start_date, end_date)
        
        # Property: No records should be included
        assert len(filtered) == 0, \
            f"Expected 0 records outside range, got {len(filtered)}"


# =============================================================================
# Additional Helper Tests
# =============================================================================

class TestParseDateHelper:
    """Tests for the parse_date helper function."""
    
    @given(d=date_strategy)
    @hyp_settings(max_examples=100, deadline=None)
    def test_parse_iso_format(self, d: date):
        """Parse date in ISO format (YYYY-MM-DD)."""
        date_str = d.isoformat()
        parsed = parse_date(date_str)
        assert parsed == d, f"Failed to parse {date_str}"
    
    @given(d=date_strategy)
    @hyp_settings(max_examples=100, deadline=None)
    def test_parse_datetime_format(self, d: date):
        """Parse date in datetime format (YYYY-MM-DDTHH:MM:SS)."""
        date_str = f"{d.isoformat()}T12:30:45"
        parsed = parse_date(date_str)
        assert parsed == d, f"Failed to parse {date_str}"
    
    def test_parse_empty_string(self):
        """Empty string should return None."""
        assert parse_date("") is None
    
    def test_parse_invalid_format(self):
        """Invalid format should return None."""
        assert parse_date("not-a-date") is None
        assert parse_date("01/02/2024") is None  # Wrong format
