from flask import jsonify, request, Blueprint, session
from models import db, Plan, User, DiscountCode, Campaign, CampaignRegistration
import datetime


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


@api_bp.route('/api/apply-discount-code', methods=['POST'])
def apply_discount_code():
    data = request.get_json()
    code = (data.get('code') or '').strip().upper()
    plan_id = data.get('plan_id')
    billing_cycle = data.get('billing_cycle')
    original_price = float(data.get('original_price', 0))
    user_id = session.get('user_id')

    if not code:
        return jsonify({'success': False, 'message': 'Please enter a discount code.'})

    if not user_id:
        return jsonify({'success': False, 'message': 'Please log in first.'})

    dc = DiscountCode.query.filter_by(code=code).first()
    if not dc:
        return jsonify({'success': False, 'message': 'Invalid discount code.'})

    if not dc.is_active:
        return jsonify({'success': False, 'message': 'This discount code is no longer active.'})

    if dc.valid_from and datetime.datetime.now() < dc.valid_from:
        return jsonify({'success': False, 'message': 'This discount code is not yet valid.'})

    if dc.valid_until and datetime.datetime.now() > dc.valid_until:
        return jsonify({'success': False, 'message': 'This discount code has expired.'})

    if dc.max_uses > 0 and dc.times_used >= dc.max_uses:
        return jsonify({'success': False, 'message': 'This discount code has reached its usage limit.'})

    if dc.assigned_user_id and dc.assigned_user_id != user_id:
        return jsonify({'success': False, 'message': 'This discount code is not valid for your account.'})

    if dc.applicable_plan_ids:
        allowed_plans = [int(x.strip()) for x in dc.applicable_plan_ids.split(',') if x.strip().isdigit()]
        if plan_id and int(plan_id) not in allowed_plans:
            return jsonify({'success': False, 'message': 'This code is not applicable to the selected plan.'})

    if dc.applicable_billing_cycles:
        allowed_cycles = [x.strip().lower() for x in dc.applicable_billing_cycles.split(',') if x.strip()]
        if billing_cycle and billing_cycle.lower() not in allowed_cycles:
            return jsonify({'success': False, 'message': 'This code is not applicable to the selected billing cycle.'})

    if dc.campaign_id:
        campaign = Campaign.query.get(dc.campaign_id)
        if campaign and (not campaign.is_active or (campaign.end_date and datetime.datetime.now() > campaign.end_date)):
            return jsonify({'success': False, 'message': 'The campaign for this code has ended.'})

    if dc.discount_type == 'percentage':
        discount_amount = round(original_price * dc.discount_value / 100, 2)
    else:
        discount_amount = min(dc.discount_value, original_price)

    final_price = round(max(original_price - discount_amount, 0), 2)

    session['applied_discount_code'] = dc.code
    session['applied_discount_amount'] = discount_amount

    return jsonify({
        'success': True,
        'message': f'Code applied! You save \u20b9{discount_amount:.0f}',
        'discount_amount': discount_amount,
        'final_price': final_price,
        'discount_type': dc.discount_type,
        'discount_value': dc.discount_value
    })


@api_bp.route('/api/remove-discount-code', methods=['POST'])
def remove_discount_code():
    session.pop('applied_discount_code', None)
    session.pop('applied_discount_amount', None)
    return jsonify({'success': True, 'message': 'Discount code removed.'})


@api_bp.route('/api/active-campaigns', methods=['GET'])
def get_active_campaigns():
    user_id = session.get('user_id')
    campaigns = Campaign.query.filter_by(is_active=True).filter(
        (Campaign.end_date == None) | (Campaign.end_date > datetime.datetime.now())
    ).all()

    result = []
    for c in campaigns:
        seats_left = c.total_seats - c.seats_taken
        is_registered = False
        user_code = None
        if user_id:
            reg = CampaignRegistration.query.filter_by(campaign_id=c.id, user_id=user_id).first()
            if reg:
                is_registered = True
                user_code = reg.discount_code

        result.append({
            'id': c.id,
            'name': c.name,
            'description': c.description,
            'total_seats': c.total_seats,
            'seats_left': seats_left,
            'discount_type': c.discount_type,
            'discount_value': c.discount_value,
            'is_registered': is_registered,
            'user_code': user_code,
            'end_date': c.end_date.strftime('%Y-%m-%d') if c.end_date else None
        })

    return jsonify(result)