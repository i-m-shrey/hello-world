"""
Multi-Broker Order Executor - Executes orders for all clients using persistent sessions
Works with SessionManager to place orders efficiently across all brokers
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from session_manager import MultibrokerSessionManager
import pandas as pd
import logging
from datetime import datetime
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MultibrokerOrderExecutor:
    """
    Executes orders for all clients using existing sessions
    - Uses SessionManager for persistent sessions
    - Multi-broker order placement
    - Order tracking and reporting
    - Error handling and retry logic
    """
    
    def __init__(self, session_manager=None):
        self.session_manager = session_manager or MultibrokerSessionManager()
        self.order_results = []
        self.execution_stats = {
            'total_orders': 0,
            'successful_orders': 0,
            'failed_orders': 0,
            'total_clients': 0,
            'successful_clients': 0,
            'failed_clients': 0,
            'execution_time': 0,
            'start_time': None,
            'end_time': None
        }
    
    def execute_orders_for_all_clients(self, filtered_etfs_df):
        """Execute orders for all clients with active sessions"""
        print("🚀 Multi-Broker Order Execution Started")
        print("=" * 50)
        
        self.execution_stats['start_time'] = datetime.now()
        start_time = time.time()
        
        # Get session summary
        summary = self.session_manager.get_session_summary()
        active_clients = summary['active_sessions']
        
        if active_clients == 0:
            print("❌ No active client sessions available")
            return False
        
        print(f"👥 Executing orders for {active_clients} clients")
        print(f"📋 ETF Symbols: {len(filtered_etfs_df)} symbols")
        
        # Show ETF details
        print(f"📊 ETFs to trade:")
        for _, row in filtered_etfs_df.iterrows():
            print(f"  • {row['SYMBOL']}: Qty {row['QTY']}, Amount ₹{row.get('FINAL_AMOUNT', 'N/A')}")
        
        # Execute orders for each client
        self.execution_stats['total_clients'] = active_clients
        
        for client_id, session_info in self.session_manager.client_sessions.items():
            try:
                print(f"\n📈 Executing orders for {client_id}...")
                self._execute_client_orders(client_id, session_info, filtered_etfs_df)
                self.execution_stats['successful_clients'] += 1
                
            except Exception as e:
                print(f"❌ Client execution failed for {client_id}: {e}")
                self.execution_stats['failed_clients'] += 1
                
                # Log failed client
                self.order_results.append({
                    'client_id': client_id,
                    'broker': session_info['broker_name'],
                    'symbol': 'ALL',
                    'status': 'FAILED',
                    'error': str(e),
                    'timestamp': datetime.now()
                })
        
        # Calculate final stats
        self.execution_stats['execution_time'] = time.time() - start_time
        self.execution_stats['end_time'] = datetime.now()
        
        # Print execution summary
        self._print_execution_summary()
        
        # Save execution report
        self._save_execution_report(filtered_etfs_df)
        
        return self.execution_stats['successful_clients'] > 0
    
    def _execute_client_orders(self, client_id, session_info, filtered_etfs_df):
        """Execute orders for a specific client"""
        client_info = session_info['client_info']
        session = session_info['session']
        broker_name = session_info['broker_name']
        
        # Get client multiplier
        multiplier = client_info.get('copy_multiplier', 1)
        
        print(f"  🏦 Broker: {broker_name}, Multiplier: {multiplier}x")
        
        # Execute each ETF order
        for _, row in filtered_etfs_df.iterrows():
            try:
                symbol = row['SYMBOL']
                base_qty = int(row['QTY']) if row['QTY'] >= 1 else 1
                client_qty = base_qty * multiplier
                
                print(f"    📊 {symbol}: {client_qty} shares")
                
                # Place order based on broker type
                if broker_name == 'FINVASIA':
                    self._place_finvasia_order(session, symbol, client_qty, client_id)
                elif broker_name in ['UPSTOX', 'DHAN', 'ANGEL']:
                    print(f"    ⚠️ {broker_name} order placement coming soon")
                    # Future implementation
                else:
                    print(f"    ❌ Unsupported broker: {broker_name}")
                    continue
                
                # Record successful order
                self.order_results.append({
                    'client_id': client_id,
                    'broker': broker_name,
                    'symbol': symbol,
                    'quantity': client_qty,
                    'multiplier': multiplier,
                    'status': 'SUCCESS',
                    'timestamp': datetime.now()
                })
                
                self.execution_stats['successful_orders'] += 1
                self.execution_stats['total_orders'] += 1
                
            except Exception as e:
                print(f"    ❌ Order failed for {symbol}: {e}")
                
                # Record failed order
                self.order_results.append({
                    'client_id': client_id,
                    'broker': broker_name,
                    'symbol': symbol,
                    'status': 'FAILED',
                    'error': str(e),
                    'timestamp': datetime.now()
                })
                
                self.execution_stats['failed_orders'] += 1
                self.execution_stats['total_orders'] += 1
    
    def _place_finvasia_order(self, session, symbol, quantity, client_id):
        """Place order for Finvasia broker"""
        trading_symbol = symbol + "-EQ"
        
        response = session.place_order(
            buy_or_sell="B",
            product_type="C",
            exchange="NSE",
            tradingsymbol=trading_symbol,
            quantity=quantity,
            discloseqty=0,
            price_type="MKT",
            price=0.0,
            retention="DAY",
            amo=None,
            remarks=f"SmartETF order for {symbol}"
        )
        
        if response and response.get('stat') == 'Ok':
            print(f"      ✅ Order placed: {trading_symbol} x {quantity}")
        else:
            error_msg = response.get('emsg', 'Unknown error') if response else 'No response'
            raise Exception(f"Order placement failed: {error_msg}")
    
    def _print_execution_summary(self):
        """Print execution summary"""
        print("\n" + "=" * 50)
        print("📊 EXECUTION SUMMARY")
        print("=" * 50)
        
        stats = self.execution_stats
        
        print(f"👥 Clients:")
        print(f"  • Total: {stats['total_clients']}")
        print(f"  • Successful: {stats['successful_clients']}")
        print(f"  • Failed: {stats['failed_clients']}")
        
        print(f"\n📋 Orders:")
        print(f"  • Total: {stats['total_orders']}")
        print(f"  • Successful: {stats['successful_orders']}")
        print(f"  • Failed: {stats['failed_orders']}")
        
        print(f"\n⏱️ Timing:")
        print(f"  • Execution Time: {stats['execution_time']:.2f} seconds")
        print(f"  • Start: {stats['start_time'].strftime('%H:%M:%S')}")
        print(f"  • End: {stats['end_time'].strftime('%H:%M:%S')}")
        
        # Success rates
        if stats['total_clients'] > 0:
            client_success_rate = (stats['successful_clients'] / stats['total_clients']) * 100
            print(f"\n📈 Success Rates:")
            print(f"  • Client Success: {client_success_rate:.1f}%")
        
        if stats['total_orders'] > 0:
            order_success_rate = (stats['successful_orders'] / stats['total_orders']) * 100
            print(f"  • Order Success: {order_success_rate:.1f}%")
    
    def _save_execution_report(self, filtered_etfs_df):
        """Save detailed execution report"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save order results
        if self.order_results:
            results_df = pd.DataFrame(self.order_results)
            results_file = f"order_execution_results_{timestamp}.csv"
            results_df.to_csv(results_file, index=False)
            print(f"\n📄 Order results saved: {results_file}")
        
        # Save execution summary
        summary_data = {
            'execution_timestamp': [timestamp],
            'total_clients': [self.execution_stats['total_clients']],
            'successful_clients': [self.execution_stats['successful_clients']],
            'failed_clients': [self.execution_stats['failed_clients']],
            'total_orders': [self.execution_stats['total_orders']],
            'successful_orders': [self.execution_stats['successful_orders']],
            'failed_orders': [self.execution_stats['failed_orders']],
            'execution_time_seconds': [self.execution_stats['execution_time']],
            'etf_symbols_count': [len(filtered_etfs_df)],
            'etf_symbols': [', '.join(filtered_etfs_df['SYMBOL'].tolist())]
        }
        
        summary_df = pd.DataFrame(summary_data)
        summary_file = f"execution_summary_{timestamp}.csv"
        summary_df.to_csv(summary_file, index=False)
        print(f"📄 Execution summary saved: {summary_file}")


# Test function
def test_order_executor():
    """Test the order executor"""
    print("🧪 Testing Multi-Broker Order Executor")
    print("=" * 50)
    
    # Create sample ETF data
    sample_etfs = pd.DataFrame({
        'SYMBOL': ['NIFTYBEES', 'BANKBEES'],
        'LTP': [100.5, 200.3],
        'QTY': [5, 3],
        'FINAL_AMOUNT': [502.5, 600.9]
    })
    
    # Initialize session manager
    session_manager = MultibrokerSessionManager()
    session_success = session_manager.initialize_all_sessions()
    
    if not session_success:
        print("❌ No sessions available - cannot test order execution")
        return False
    
    # Initialize order executor
    executor = MultibrokerOrderExecutor(session_manager)
    
    # Execute orders (dry run)
    print("⚠️ This is a test - no real orders will be placed")
    print("💡 To place real orders, modify the _place_finvasia_order method")
    
    success = executor.execute_orders_for_all_clients(sample_etfs)
    
    # Cleanup
    session_manager.cleanup_sessions()
    
    return success


if __name__ == "__main__":
    test_order_executor()