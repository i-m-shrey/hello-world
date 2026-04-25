from app import app, db, PaymentMethod
import datetime

# Create test payment method
with app.app_context():
    payment = PaymentMethod(
        name="Test Payment",
        description="Test payment method entry",
        is_active=True,
        created_at=datetime.datetime.utcnow(),
        amount_paid=100.0,
        payment_date="Test data",
        payment_method="Credit Card",
        payment_id="TEST-12345",
        customer_id=None,
        payment_status="Active"
    )

    try:
        db.session.add(payment)
        db.session.commit()
        print(f"Test payment method created with ID: {payment.id}")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating payment method: {str(e)}")