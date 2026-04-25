from app import db
from models import User, Plan
from app import Broker, Subscription
from datetime import datetime

def get_active_clients():
    """
    Return a list of users with valid subscriptions and broker setup
    """
    today = datetime.utcnow()

    results = (
        db.session.query(User, Broker, Subscription)
        .join(Broker, User.id == Broker.user_id)
        .join(Subscription, User.customer_id == Subscription.customer_id)
        .filter(
            User.is_active == True,
            Subscription.payment_status == 'Successful',
            Subscription.expiry_date >= today,
            Broker.is_master != True,
            Broker.subscription_status == 'Active',
            Broker.subscription_expiry >= today
        )
        .all()
    )

    # Convert to dictionary list for easy usage in strategy
    client_data = []
    for user, broker, subscription in results:
        client_data.append({
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "broker_name": broker.broker_name,
            "api_key": broker.api_key,
            "totp_secret": broker.totp_secret,
            "access_token": broker.access_token,
            "subscription_plan": subscription.plan_name,
            "subscription_expiry": subscription.expiry_date
        })

    return client_data
