from flask import jsonify, request, Blueprint
from models import db, Plan, User


api_bp = Blueprint('api_bp', __name__)

print("API ROUTES")

@api_bp.route('/api/plans', methods=['GET'])
def get_plans():
    # print("In get_plans")
    plans = Plan.query.filter_by(is_active=True).all()
    order_map = {'Basic': 1, 'Growth': 2, 'Premium': 3}
    plans.sort(key=lambda p: order_map.get(p.name, 99))
    plan_list = [{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'monthly_price': p.monthly_price,
        'quarterly_price': p.quarterly_price,
        'half_yearly_price': p.half_yearly_price,
        'annually_price': p.annually_price,
        'features': p.features,
        'max_sip_amount': p.max_sip_amount,
        'has_copy_trading': bool(p.has_copy_trading)
    } for p in plans]
    return jsonify(plan_list)


@api_bp.route('/api/subscribe', methods=['POST'])
def subscribe():
    data = request.json
    # Extract user & plan data from request
    name = data.get('name')
    email = data.get('email')
    plan_id = data.get('plan_id')
    
    # Basic user creation or fetch logic
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, name=name)
        db.session.add(user)
        db.session.commit()

    # Here you can link user to subscription table logic
    # ...

    return jsonify({'success': True, 'message': 'Subscription successful. User registered.'})


@api_bp.route('/api/check_email', methods=['POST'])
def check_email():
    email = request.json.get('email')
    exists = User.query.filter_by(email=email).first() is not None
    return jsonify({'exists': exists})


@api_bp.route('/api/check_username', methods=['POST'])
def check_username():
    data = request.get_json()
    exists = User.query.filter_by(username=data.get('username')).first() is not None
    return jsonify({'exists': exists})


@api_bp.route('/api/check_mobile', methods=['POST'])
def check_mobile():
    data = request.get_json()
    exists = User.query.filter_by(mobile=data.get('mobile')).first() is not None
    return jsonify({'exists': exists})