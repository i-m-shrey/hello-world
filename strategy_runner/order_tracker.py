"""
Order Tracking - Log order results to file
"""
import os
import json
from datetime import datetime


def log_order_result(customer_id, broker_name, result, log_dir='logs'):
    """
    Log order result to file
    
    result = {
        'symbol': 'GOLDSHARE',
        'status': 'SUCCESS/FAILED/REPLACED',
        'actual_symbol': 'GOLDBEES',
        'original_qty': 2,
        'actual_qty': 3,
        'original_price': 150,
        'actual_price': 100,
        'reason': 'Symbol not found, used alternative',
        'order_id': '123456',
        'error': None
    }
    """
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = f"{log_dir}/order_execution_{datetime.now().strftime('%Y%m%d')}.log"
    
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'customer_id': customer_id,
        'broker': broker_name,
        **result
    }
    
    with open(log_file, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')


def get_failed_orders(log_file):
    """Parse log file and return failed/replaced orders"""
    if not os.path.exists(log_file):
        return []
    
    failed_orders = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get('status') in ['FAILED', 'REPLACED']:
                    failed_orders.append(entry)
            except:
                continue
    
    return failed_orders
