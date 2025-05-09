import os
import json
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from datetime import datetime
from dotenv import load_dotenv
from flask_socketio import SocketIO, emit, join_room
from PIL import Image

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")
app.secret_key = os.getenv('SECRET_KEY')

# Configure upload folder
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')
mail = Mail(app)

# Products database file
PRODUCTS_DB = 'products.json'

# Admin credentials
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# Helper Functions
def resize_image(image_path):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((500, 500))
            img.save(image_path)
    except Exception as e:
        logger.error(f"Error resizing image: {e}")

def load_products():
    try:
        with open(PRODUCTS_DB, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_products(products):
    with open(PRODUCTS_DB, 'w') as f:
        json.dump(products, f, indent=2)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_image(file):
    try:
        img = Image.open(file)
        img.verify()
        file.seek(0)
        return True
    except Exception:
        return False

# WebSocket Handlers
@socketio.on('connect')
def handle_connect():
    if request.namespace == '/admin' and not session.get('logged_in'):
        return False
    emit('connection_response', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('join_admin')
def handle_join_admin():
    if session.get('logged_in'):
        join_room('admin_room')
        emit('admin_status', {'status': 'joined'})

@socketio.on('request_products')
def handle_products_request():
    try:
        products = load_products()
        emit('products_update', {
            'products': [{
                'id': p['id'],
                'title': p['title'],
                'price': p['price'],
                'originalPrice': p.get('original_price', p['price']),
                'image': p.get('image', '')
            } for p in products]
        })
    except Exception as e:
        emit('error', {'message': str(e)})

# Routes
@app.route('/')
def index():
    products = load_products()
    return render_template('index.html', products=products)

@app.route('/debug/uploads')
def debug_uploads():
    uploads = os.listdir(app.config['UPLOAD_FOLDER'])
    return jsonify({
        'upload_folder': app.config['UPLOAD_FOLDER'],
        'exists': os.path.exists(app.config['UPLOAD_FOLDER']),
        'files': uploads
    })

@app.route('/test-email')
def test_email():
    try:
        msg = Message(
            subject="Test Email from Flask",
            recipients=["kevinshimanjala@gmail.com"],  
            body="This is a test email from your Flask application."
        )
        mail.send(msg)
        return "Test email sent successfully!"
    except Exception as e:
        return f"Failed to send email: {str(e)}"

@app.route('/place-order', methods=['POST'])
def place_order():
    try:
        data = request.json
        logger.info(f"Received order data: {data}")
        order_number = datetime.now().strftime("%Y%m%d%H%M%S")

        # Build itemized order list with quantities and prices
        order_items_text = "\n".join(
            f"{item['title']} x {item['quantity']} @ KSh {item['price']:,} = KSh {item['total']:,}"
            for item in data['orderItems']
        )

        order_summary = f"""
        ORDER #{order_number}
        ======================
        Customer Details:
        Name: {data['name']}
        Phone: {data['phone']}
        Email: {data.get('email', 'Not provided')}
        Delivery Location: {data['deliveryLocation']}
        Delivery Address: {data['address']}
        Customer Notes: {data['notes']}
        
        Order Items:
        ----------------------
        {order_items_text}
        ----------------------
        Subtotal: KSh {data['subtotal']:,}
        + Delivery Fee: KSh {data['deliveryFee']:,}
        ----------------------
        TOTAL: KSh {data['total']:,}
        
        Payment Method:
        {data['paymentMethod']} - {data['paymentDetails']}
        
        Order Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        """

        # HTML version for customer email
        order_summary_html = f"""
        <h2>ORDER #{order_number}</h2>
        <h3>Customer Details</h3>
        <p><strong>Name:</strong> {data['name']}</p>
        <p><strong>Phone:</strong> {data['phone']}</p>
        <p><strong>Email:</strong> {data.get('email', 'Not provided')}</p>
        <p><strong>Delivery Location:</strong> {data['deliveryLocation']}</p>
        <p><strong>Delivery Address:</strong> {data['address']}</p>
        <p><strong>Notes:</strong> {data['notes']}</p>
        
        <h3>Order Items</h3>
        <ul>
            {"".join(
                f"<li>{item['title']} x {item['quantity']} @ KSh {item['price']:,} = KSh {item['total']:,}</li>" 
                for item in data['orderItems']
            )}
        </ul>
        
        <table style="width: 100%; border-top: 1px solid #eee; margin: 15px 0;">
            <tr>
                <td style="padding: 5px 0;"><strong>Subtotal:</strong></td>
                <td style="text-align: right;">KSh {data['subtotal']:,}</td>
            </tr>
            <tr>
                <td style="padding: 5px 0;"><strong>Delivery Fee:</strong></td>
                <td style="text-align: right;">KSh {data['deliveryFee']:,}</td>
            </tr>
            <tr style="border-top: 1px solid #eee;">
                <td style="padding: 5px 0;"><strong>TOTAL:</strong></td>
                <td style="text-align: right;"><strong>KSh {data['total']:,}</strong></td>
            </tr>
        </table>
        
        <h3>Payment Method</h3>
        <p>{data['paymentMethod']} - {data['paymentDetails']}</p>
        
        <p>Order Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        """

        # Send email to admin
        admin_msg = Message(
            subject=f"New Order #{order_number} from {data['name']}",
            recipients=['kevinshimanjala@gmail.com'],
            body=order_summary
        )
        mail.send(admin_msg)

        # Send email to customer if email provided
        if data.get('email'):
            customer_msg = Message(
                subject=f"Your HomiQ Essentials Order #{order_number}",
                recipients=[data['email']],
                html=order_summary_html
            )
            mail.send(customer_msg)

        return jsonify({
            'success': True,
            'message': 'Order received successfully',
            'order_number': order_number,
            'email_sent': bool(data.get('email'))
        })
    except Exception as e:
        logger.error(f"Order processing failed: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.template_filter('basename')
def basename_filter(path):
    return os.path.basename(path)

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    products = load_products()
    return render_template('admin.html', products=products)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/add-product', methods=['POST'])
def add_product():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    try:
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price = float(request.form.get('price', 0))
        original_price = float(request.form.get('original_price', price))

        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('admin_dashboard'))

        image_url, video_url = '', ''
        for media_type in ['image', 'video']:
            file = request.files.get(media_type)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                if media_type == 'image':
                    resize_image(filepath)
                    image_url = url_for('static', filename=f'uploads/{filename}')
                else:
                    video_url = url_for('static', filename=f'uploads/{filename}')

        products = load_products()
        new_id = max((p['id'] for p in products), default=0) + 1 if products else 1

        new_product = {
            'id': new_id,
            'title': title,
            'description': description,
            'price': price,
            'original_price': original_price,
            'image': image_url,
            'video': video_url,
            'created_at': datetime.now().isoformat()
        }
        products.append(new_product)
        save_products(products)
        
        socketio.emit('product_update', {
            'action': 'add',
            'product': {
                'id': new_id,
                'title': title,
                'price': price,
                'originalPrice': original_price,
                'image': image_url
            }
        }, room='admin_room')
        
        flash('Product added successfully!', 'success')
    except Exception as e:
        logger.error(f"Error adding product: {e}")
        socketio.emit('error', {'message': f'Add product failed: {str(e)}'}, room='admin_room')
        flash('Error adding product', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    try:
        products = load_products()
        deleted_product = next((p for p in products if p['id'] == product_id), None)
        products = [p for p in products if p['id'] != product_id]
        save_products(products)
        
        if deleted_product and deleted_product.get('image'):
            try:
                image_path = os.path.join(app.static_folder, deleted_product['image'].lstrip('/'))
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception as e:
                logger.error(f"Error deleting image file: {e}")
        
        socketio.emit('product_update', {
            'action': 'delete',
            'productId': product_id
        }, room='admin_room')
        
        flash('Product deleted successfully!', 'success')
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        socketio.emit('error', {'message': f'Delete product failed: {str(e)}'}, room='admin_room')
        flash('Error deleting product', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/products')
def api_products():
    products = load_products()
    return jsonify([{
        'id': p['id'],
        'title': p['title'],
        'description': p.get('description', ''),
        'price': p['price'],
        'originalPrice': p.get('original_price', p['price']),
        'image': p.get('image', '')
    } for p in products])

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)



        