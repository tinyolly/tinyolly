"""
Demo Backend Service for eBPF Zero-Code Instrumentation

This service has NO tracing instrumentation - traces are automatically
captured by the OpenTelemetry eBPF agent running alongside.
"""
import random
import time
import logging
import json
from flask import Flask, jsonify, request

# Configure structured JSON logging with stdout handler
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',  # Just the message, structured logging will handle the rest
    handlers=[
        logging.StreamHandler(sys.stdout)  # Ensure logs go to stdout
    ]
)
logger = logging.getLogger(__name__)

# Helper for structured logging
def log_json(level, message, **kwargs):
    """Log a structured JSON message"""
    log_data = {
        'message': message,
        **kwargs
    }
    getattr(logger, level)(json.dumps(log_data))

app = Flask(__name__)
app.config['SERVER_NAME'] = 'ebpf-backend:5000'

@app.route('/check-inventory', methods=['POST'])
def check_inventory():
    """Check if items are in stock"""
    data = request.get_json()
    item_count = data.get('items', 1)
    
    log_json('info', "Checking inventory", 
             item_count=item_count, 
             operation="inventory_check")
    
    # Simulate database query
    time.sleep(random.uniform(0.05, 0.12))
    
    in_stock = random.choice([True, True, True, False])  # 75% success
    
    if not in_stock:
        log_json('warning', "Items out of stock", 
                item_count=item_count, 
                status="checking_alternatives")
        time.sleep(random.uniform(0.03, 0.08))
    
    log_json('info', "Inventory check complete", 
             item_count=item_count, 
             available=in_stock,
             status="available" if in_stock else "out_of_stock")
    
    return jsonify({
        "available": in_stock,
        "checked_items": item_count
    })

@app.route('/calculate-price', methods=['POST'])
def calculate_price():
    """Calculate pricing with discounts and tax"""
    data = request.get_json()
    item_count = data.get('items', 1)
    base_price = data.get('base_price', 50.0)
    
    log_json('info', "Calculating price", 
             item_count=item_count, 
             base_price=round(base_price, 2),
             operation="price_calculation")
    
    # Fetch pricing rules
    time.sleep(random.uniform(0.02, 0.05))
    
    # Apply discount
    discount_rate = random.choice([0, 0, 0.1, 0.15, 0.2])
    discount_amount = base_price * discount_rate
    logger.info(f"Applied {discount_rate*100}% discount: ${discount_amount:.2f}")
    time.sleep(random.uniform(0.01, 0.03))
    
    # Calculate tax
    tax_rate = 0.08
    subtotal = base_price - discount_amount
    tax_amount = subtotal * tax_rate
    total = subtotal + tax_amount
    
    logger.info(f"Price calculation complete: ${total:.2f}")
    time.sleep(random.uniform(0.01, 0.02))
    
    return jsonify({
        "base_price": round(base_price, 2),
        "discount": round(discount_amount, 2),
        "tax": round(tax_amount, 2),
        "total": round(total, 2)
    })

@app.route('/process-payment', methods=['POST'])
def process_payment():
    """Process payment for order"""
    data = request.get_json()
    amount = data.get('amount', 0)
    
    logger.info(f"Processing payment for ${amount:.2f}")
    
    # Validate card
    time.sleep(random.uniform(0.03, 0.06))
    logger.info("Card validated")
    
    # Charge card (simulate payment gateway)
    time.sleep(random.uniform(0.1, 0.25))
    
    # Occasional failure
    success = random.random() > 0.1  # 90% success
    
    if success:
        logger.info(f"Payment of ${amount:.2f} processed successfully")
        receipt_id = random.randint(10000, 99999)
        
        # Generate receipt
        time.sleep(random.uniform(0.02, 0.04))
        
        return jsonify({
            "success": True,
            "receipt_id": receipt_id,
            "amount": round(amount, 2)
        })
    else:
        logger.error("Payment declined by gateway")
        return jsonify({
            "success": False,
            "error": "Payment declined"
        }), 402

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "backend"})

if __name__ == '__main__':
    logger.info("Starting demo backend service")
    app.run(host='0.0.0.0', port=5000)
