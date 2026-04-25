"""
Client Monthly Investment Tracker
Tracks each client's monthly investment progress and generates daily summary reports
"""
import os
import pandas as pd
from datetime import datetime as dt
from collections import defaultdict
import logging


TRACKING_FOLDER = "tracking"
ENABLE_TRACKING = os.getenv('ENABLE_CLIENT_TRACKING', '1').lower() in ('1', 'true', 'yes')


def ensure_tracking_folder():
    """Create tracking folder if it doesn't exist"""
    os.makedirs(TRACKING_FOLDER, exist_ok=True)


def get_tracking_csv_path(year_month=None):
    """Get path for tracking CSV (current month or specific month)"""
    if year_month is None:
        year_month = dt.now().strftime('%Y-%m')
    filename = f"{year_month}-client_summary.csv"
    return os.path.join(TRACKING_FOLDER, filename)


def get_month_end_flag_path(year_month):
    """Get path for month-end summary flag file"""
    filename = f"{year_month}-month_end_sent.flag"
    return os.path.join(TRACKING_FOLDER, filename)


def read_existing_summary():
    """Read existing summary CSV for current month"""
    csv_path = get_tracking_csv_path()
    
    if not os.path.exists(csv_path):
        return pd.DataFrame(columns=[
            'date', 'customer_id', 'customer_name', 'execution_count', 
            'month_invested', 'monthly_target', 'progress_percent', 
            'remaining_budget', 'status'
        ])
    
    try:
        return pd.read_csv(csv_path)
    except Exception as e:
        logging.warning(f"Error reading tracking CSV: {e}")
        return pd.DataFrame(columns=[
            'date', 'customer_id', 'customer_name', 'execution_count', 
            'month_invested', 'monthly_target', 'progress_percent', 
            'remaining_budget', 'status'
        ])


def update_client_tracking(execution_summary, user_multipliers):
    """
    Update client tracking CSV after each execution
    
    Args:
        execution_summary: Result from execute_etf_orders
        user_multipliers: User multiplier data with monthly targets
    """
    if not ENABLE_TRACKING:
        return
    
    try:
        ensure_tracking_folder()
        
        # Read existing summary
        summary_df = read_existing_summary()
        
        # Get current data
        today = dt.now().strftime('%Y-%m-%d')
        
        # Import here to avoid circular dependency
        try:
            import sys
            sys.path.insert(0, os.path.dirname(__file__))
            from app import app, User
            from etf_automated import read_monthly_invested
        except Exception as e:
            logging.error(f"Cannot import required modules for tracking: {e}")
            return
        
        # Collect data for each customer
        new_rows = []
        
        with app.app_context():
            for customer_id, data in user_multipliers.items():
                try:
                    # Get user info
                    user = User.query.filter_by(customer_id=customer_id).first()
                    customer_name = user.full_name if user else customer_id
                    
                    # Get month-to-date investment
                    month_invested = read_monthly_invested(customer_id)
                    
                    # Get monthly target
                    monthly_target = data.get('monthly_target', 0)
                    
                    # Calculate progress
                    progress_percent = (month_invested / monthly_target * 100) if monthly_target > 0 else 0
                    remaining_budget = max(0, monthly_target - month_invested)
                    
                    # Determine status
                    if progress_percent >= 100:
                        status = 'TARGET_MET'
                    elif progress_percent >= 80:
                        status = 'ON_TRACK'
                    elif progress_percent >= 50:
                        status = 'MODERATE'
                    else:
                        status = 'LOW'
                    
                    # Count executions for this customer today
                    today_executions = summary_df[
                        (summary_df['customer_id'] == customer_id) & 
                        (summary_df['date'] == today)
                    ]
                    execution_count = len(today_executions) + 1 if not today_executions.empty else 1
                    
                    new_rows.append({
                        'date': today,
                        'customer_id': customer_id,
                        'customer_name': customer_name,
                        'execution_count': execution_count,
                        'month_invested': round(month_invested, 2),
                        'monthly_target': round(monthly_target, 2),
                        'progress_percent': round(progress_percent, 2),
                        'remaining_budget': round(remaining_budget, 2),
                        'status': status
                    })
                
                except Exception as e:
                    logging.warning(f"Error tracking customer {customer_id}: {e}")
                    continue
        
        if new_rows:
            # Append new rows to existing summary
            new_df = pd.DataFrame(new_rows)
            summary_df = pd.concat([summary_df, new_df], ignore_index=True)
            
            # Save to CSV
            csv_path = get_tracking_csv_path()
            summary_df.to_csv(csv_path, index=False)
            logging.info(f"Updated client tracking: {csv_path}")
            
            return csv_path
        
    except Exception as e:
        logging.error(f"Error in update_client_tracking: {e}")
        return None


def generate_tracking_email_content(csv_path=None):
    """
    Generate email content for admin with client tracking summary
    
    Returns:
        dict: {'subject': '...', 'html_body': '...', 'text_body': '...', 'csv_path': '...'}
    """
    if not ENABLE_TRACKING:
        return None
    
    try:
        if not csv_path:
            csv_path = get_tracking_csv_path()
        
        if not os.path.exists(csv_path):
            return None
        
        # Read summary
        summary_df = pd.read_csv(csv_path)
        
        if summary_df.empty:
            return None
        
        # Get today's date
        today = dt.now().strftime('%Y-%m-%d')
        current_month = dt.now().strftime('%Y-%m')
        
        # Get latest entry per customer
        latest_df = summary_df.groupby('customer_id').last().reset_index()
        
        # Sort by progress percent (lowest first - needs attention)
        latest_df = latest_df.sort_values('progress_percent', ascending=True)
        
        # Calculate summary stats
        total_clients = len(latest_df)
        target_met = len(latest_df[latest_df['status'] == 'TARGET_MET'])
        on_track = len(latest_df[latest_df['status'] == 'ON_TRACK'])
        needs_attention = len(latest_df[latest_df['status'].isin(['LOW', 'MODERATE'])])
        
        total_target = latest_df['monthly_target'].sum()
        total_invested = latest_df['month_invested'].sum()
        overall_progress = (total_invested / total_target * 100) if total_target > 0 else 0
        
        # Build HTML email
        html_body = f"""
<div style='font-family:Inter,Arial,sans-serif;'>
  <h2 style='margin:0 0 10px 0;'>📊 Client Monthly Investment Tracker</h2>
  <p style='margin:5px 0;color:#666;'><b>Month:</b> {current_month} &nbsp;|&nbsp; <b>Report Date:</b> {today}</p>
  
  <div style='margin:20px 0; padding:15px; background:#f6f8fa; border-radius:5px;'>
    <h3 style='margin:0 0 10px 0;'>Overall Summary</h3>
    <table style='width:100%; border-collapse:collapse;'>
      <tr>
        <td style='padding:5px 0;'><b>Total Clients:</b></td>
        <td style='padding:5px 0; text-align:right;'>{total_clients}</td>
      </tr>
      <tr>
        <td style='padding:5px 0;'><b>Target Met:</b></td>
        <td style='padding:5px 0; text-align:right; color:#0a8a0a;'>{target_met} ({target_met/total_clients*100:.1f}%)</td>
      </tr>
      <tr>
        <td style='padding:5px 0;'><b>On Track:</b></td>
        <td style='padding:5px 0; text-align:right; color:#ff8c00;'>{on_track} ({on_track/total_clients*100:.1f}%)</td>
      </tr>
      <tr>
        <td style='padding:5px 0;'><b>Needs Attention:</b></td>
        <td style='padding:5px 0; text-align:right; color:#c00;'>{needs_attention} ({needs_attention/total_clients*100:.1f}%)</td>
      </tr>
      <tr style='border-top:1px solid #ddd;'>
        <td style='padding:10px 0 5px 0;'><b>Total Monthly Target:</b></td>
        <td style='padding:10px 0 5px 0; text-align:right;'><b>₹{total_target:,.0f}</b></td>
      </tr>
      <tr>
        <td style='padding:5px 0;'><b>Total Invested (MTD):</b></td>
        <td style='padding:5px 0; text-align:right;'><b>₹{total_invested:,.0f}</b></td>
      </tr>
      <tr>
        <td style='padding:5px 0;'><b>Overall Progress:</b></td>
        <td style='padding:5px 0; text-align:right;'><b>{overall_progress:.1f}%</b></td>
      </tr>
    </table>
  </div>
  
  <h3 style='margin:20px 0 10px 0;'>Client Details</h3>
  <table cellspacing='0' cellpadding='0' style='border-collapse:collapse; width:100%; font-size:13px;'>
    <thead>
      <tr style='background:#f6f8fa;'>
        <th style='padding:8px; border:1px solid #ddd; text-align:left;'>Client</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Target (₹)</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Invested (₹)</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Progress</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Remaining</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:center;'>Status</th>
      </tr>
    </thead>
    <tbody>
"""
        
        # Add rows
        for _, row in latest_df.iterrows():
            status_color = {
                'TARGET_MET': '#0a8a0a',
                'ON_TRACK': '#28a745',
                'MODERATE': '#ff8c00',
                'LOW': '#c00'
            }.get(row['status'], '#666')
            
            html_body += f"""
      <tr>
        <td style='padding:8px; border:1px solid #ddd;'>{row['customer_name']}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right;'>{row['monthly_target']:,.0f}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right;'>{row['month_invested']:,.0f}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right; font-weight:600;'>{row['progress_percent']:.1f}%</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right;'>{row['remaining_budget']:,.0f}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:center; color:{status_color}; font-weight:600;'>{row['status']}</td>
      </tr>
"""
        
        html_body += """
    </tbody>
  </table>
  
  <p style='margin-top:20px; color:#666; font-size:12px;'>
    💡 <b>Note:</b> This report tracks month-to-date progress. Attached CSV contains full history for {month}.
  </p>
  
  <p style='color:gray; font-size:11px; margin-top:20px;'>SmartETF Client Tracking System</p>
</div>
""".format(month=current_month)
        
        # Build text email
        text_body = f"""
📊 Client Monthly Investment Tracker
Month: {current_month} | Report Date: {today}

OVERALL SUMMARY
===============
Total Clients: {total_clients}
Target Met: {target_met} ({target_met/total_clients*100:.1f}%)
On Track: {on_track} ({on_track/total_clients*100:.1f}%)
Needs Attention: {needs_attention} ({needs_attention/total_clients*100:.1f}%)

Total Monthly Target: ₹{total_target:,.0f}
Total Invested (MTD): ₹{total_invested:,.0f}
Overall Progress: {overall_progress:.1f}%

CLIENT DETAILS
==============
"""
        
        for _, row in latest_df.iterrows():
            text_body += f"""
{row['customer_name']}
  Target: ₹{row['monthly_target']:,.0f}
  Invested: ₹{row['month_invested']:,.0f}
  Progress: {row['progress_percent']:.1f}%
  Remaining: ₹{row['remaining_budget']:,.0f}
  Status: {row['status']}
"""
        
        text_body += f"\n\nAttached CSV contains full history for {current_month}."
        
        return {
            'subject': f"📊 Client Investment Tracker - {current_month} ({today})",
            'html_body': html_body,
            'text_body': text_body,
            'csv_path': csv_path
        }
    
    except Exception as e:
        logging.error(f"Error generating tracking email: {e}")
        return None


def generate_month_end_summary(year_month):
    """Generate month-end summary for a completed month"""
    try:
        csv_path = get_tracking_csv_path(year_month)
        
        if not os.path.exists(csv_path):
            return None
        
        # Read monthly data
        summary_df = pd.read_csv(csv_path)
        
        if summary_df.empty:
            return None
        
        # Get final entry per customer (last execution of the month)
        final_df = summary_df.groupby('customer_id').last().reset_index()
        final_df = final_df.sort_values('progress_percent', ascending=True)
        
        # Calculate stats
        total_clients = len(final_df)
        target_met = len(final_df[final_df['progress_percent'] >= 100])
        above_80 = len(final_df[final_df['progress_percent'] >= 80])
        below_80 = len(final_df[final_df['progress_percent'] < 80])
        
        total_target = final_df['monthly_target'].sum()
        total_invested = final_df['month_invested'].sum()
        overall_progress = (total_invested / total_target * 100) if total_target > 0 else 0
        
        # Build HTML
        html_body = f"""
<div style='font-family:Inter,Arial,sans-serif;'>
  <h2 style='margin:0 0 10px 0; color:#0a8a0a;'>📅 Month-End Summary: {year_month}</h2>
  <p style='margin:5px 0; color:#666;'>Final investment report for the completed month</p>
  
  <div style='margin:20px 0; padding:15px; background:#e8f5e9; border-left:4px solid #0a8a0a; border-radius:5px;'>
    <h3 style='margin:0 0 10px 0;'>Final Results</h3>
    <table style='width:100%; border-collapse:collapse;'>
      <tr><td style='padding:5px 0;'><b>Total Clients:</b></td><td style='text-align:right;'>{total_clients}</td></tr>
      <tr><td style='padding:5px 0;'><b>100%+ Target Met:</b></td><td style='text-align:right; color:#0a8a0a;'><b>{target_met}</b> ({target_met/total_clients*100:.1f}%)</td></tr>
      <tr><td style='padding:5px 0;'><b>80-99% On Track:</b></td><td style='text-align:right; color:#ff8c00;'>{above_80 - target_met}</td></tr>
      <tr><td style='padding:5px 0;'><b>&lt;80% Below Target:</b></td><td style='text-align:right; color:#c00;'>{below_80}</td></tr>
      <tr style='border-top:1px solid #666;'><td style='padding:10px 0 5px 0;'><b>Total Target:</b></td><td style='text-align:right;'><b>₹{total_target:,.0f}</b></td></tr>
      <tr><td style='padding:5px 0;'><b>Total Invested:</b></td><td style='text-align:right;'><b>₹{total_invested:,.0f}</b></td></tr>
      <tr><td style='padding:5px 0;'><b>Overall Achievement:</b></td><td style='text-align:right; font-size:18px; color:{'#0a8a0a' if overall_progress >= 80 else '#c00'};'><b>{overall_progress:.1f}%</b></td></tr>
    </table>
  </div>
  
  <h3 style='margin:20px 0 10px 0;'>Final Client Standings</h3>
  <table cellspacing='0' cellpadding='0' style='border-collapse:collapse; width:100%; font-size:13px;'>
    <thead>
      <tr style='background:#f6f8fa;'>
        <th style='padding:8px; border:1px solid #ddd; text-align:left;'>Client</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Target (₹)</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Invested (₹)</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Achievement</th>
        <th style='padding:8px; border:1px solid #ddd; text-align:right;'>Variance</th>
      </tr>
    </thead>
    <tbody>
"""
        
        for _, row in final_df.iterrows():
            variance = row['month_invested'] - row['monthly_target']
            variance_color = '#0a8a0a' if variance >= 0 else '#c00'
            progress_color = '#0a8a0a' if row['progress_percent'] >= 100 else ('#ff8c00' if row['progress_percent'] >= 80 else '#c00')
            
            html_body += f"""
      <tr>
        <td style='padding:8px; border:1px solid #ddd;'>{row['customer_name']}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right;'>{row['monthly_target']:,.0f}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right;'>{row['month_invested']:,.0f}</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right; color:{progress_color}; font-weight:600;'>{row['progress_percent']:.1f}%</td>
        <td style='padding:8px; border:1px solid #ddd; text-align:right; color:{variance_color};'>{variance:+,.0f}</td>
      </tr>
"""
        
        html_body += f"""
    </tbody>
  </table>
  
  <p style='margin-top:20px; padding:10px; background:#fff3e0; border-left:4px solid #ff8c00; border-radius:5px;'>
    💡 <b>Note:</b> Monthly SIP targets are dynamic based on market conditions. Month-over-month variance is expected and healthy for value investing strategy.
  </p>
  
  <p style='color:gray; font-size:11px; margin-top:20px;'>SmartETF Month-End Report</p>
</div>
"""
        
        # Text body
        text_body = f"""
📅 MONTH-END SUMMARY: {year_month}
{'='*60}

FINAL RESULTS
=============
Total Clients: {total_clients}
100%+ Target Met: {target_met} ({target_met/total_clients*100:.1f}%)
80-99% On Track: {above_80 - target_met}
<80% Below Target: {below_80}

Total Target: ₹{total_target:,.0f}
Total Invested: ₹{total_invested:,.0f}
Overall Achievement: {overall_progress:.1f}%

CLIENT STANDINGS
================
"""
        
        for _, row in final_df.iterrows():
            variance = row['month_invested'] - row['monthly_target']
            text_body += f"""
{row['customer_name']}
  Target: ₹{row['monthly_target']:,.0f}
  Invested: ₹{row['month_invested']:,.0f}
  Achievement: {row['progress_percent']:.1f}%
  Variance: {variance:+,.0f}
"""
        
        return {
            'subject': f"📅 Month-End Summary: {year_month} - Final Investment Report",
            'html_body': html_body,
            'text_body': text_body,
            'csv_path': csv_path
        }
    
    except Exception as e:
        logging.error(f"Error generating month-end summary: {e}")
        return None


def check_and_send_month_end_summary():
    """Check if previous month ended and send month-end summary if not sent yet"""
    if not ENABLE_TRACKING:
        return
    
    try:
        ensure_tracking_folder()
        
        current_date = dt.now()
        current_month = current_date.strftime('%Y-%m')
        
        # Calculate previous month
        first_of_current_month = current_date.replace(day=1)
        last_month_date = first_of_current_month - pd.Timedelta(days=1)
        previous_month = last_month_date.strftime('%Y-%m')
        
        # Check if we're in a new month (day 1-5 of current month)
        if current_date.day > 5:
            return  # Too late in month, skip check
        
        # Check if month-end summary already sent for previous month
        flag_path = get_month_end_flag_path(previous_month)
        if os.path.exists(flag_path):
            logging.info(f"Month-end summary already sent for {previous_month}")
            return
        
        # Check if previous month's CSV exists
        prev_csv_path = get_tracking_csv_path(previous_month)
        if not os.path.exists(prev_csv_path):
            logging.info(f"No tracking data for previous month {previous_month}")
            return
        
        # Generate month-end summary
        logging.info(f"Generating month-end summary for {previous_month}")
        email_content = generate_month_end_summary(previous_month)
        
        if not email_content:
            logging.warning(f"Could not generate month-end summary for {previous_month}")
            return
        
        # Import notify_admin
        try:
            from notify_admin import notify_admin
        except:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'strategy_runner'))
                from notify_admin import notify_admin
            except Exception as e:
                logging.error(f"Cannot import notify_admin: {e}")
                return
        
        # Send month-end email
        notify_admin(
            subject=email_content['subject'],
            html_body=email_content['html_body'],
            text_body=email_content['text_body']
        )
        
        # Create flag file to prevent re-sending
        with open(flag_path, 'w') as f:
            f.write(f"Month-end summary sent at {dt.now().isoformat()}")
        
        logging.info(f"✅ Month-end summary sent for {previous_month}")
        
    except Exception as e:
        logging.error(f"Error in check_and_send_month_end_summary: {e}")


def send_tracking_email(email_content=None):
    """Send tracking email to admin"""
    if not ENABLE_TRACKING:
        return
    
    try:
        # Check and send month-end summary first (if new month)
        check_and_send_month_end_summary()
        
        # Then send regular daily tracking email
        if not email_content:
            email_content = generate_tracking_email_content()
        
        if not email_content:
            logging.info("No tracking email content to send")
            return
        
        # Import notify_admin
        try:
            from notify_admin import notify_admin
        except:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'strategy_runner'))
                from notify_admin import notify_admin
            except Exception as e:
                logging.error(f"Cannot import notify_admin: {e}")
                return
        
        # Send email
        notify_admin(
            subject=email_content['subject'],
            html_body=email_content['html_body'],
            text_body=email_content['text_body']
        )
        
        logging.info(f"Client tracking email sent successfully")
        
    except Exception as e:
        logging.error(f"Error sending tracking email: {e}")


if __name__ == "__main__":
    # Test tracking email generation
    print("Testing Client Monthly Tracker...")
    
    # Mock data for testing
    mock_user_multipliers = {
        'user_001': {'monthly_target': 20000, 'multiplier': 2.5},
        'user_002': {'monthly_target': 10000, 'multiplier': 1.25},
        'user_003': {'monthly_target': 50000, 'multiplier': 6.25},
    }
    
    mock_execution_summary = {
        'total_clients': 3,
        'successful_orders': 3,
        'total_investment': 15000
    }
    
    print("✅ Client tracking module loaded successfully")
