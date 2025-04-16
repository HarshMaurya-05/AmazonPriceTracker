from flask import Flask, render_template, request, redirect, url_for, flash, session
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import csv
import os
import re
from datetime import datetime
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

from datetime import datetime

@app.context_processor
def inject_now():
    return {'now': datetime.now}
# File to store products and their prices
DATA_FILE = 'product_prices.csv'

# Sender email configuration
SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_password"

# Create the data file if it doesn't exist
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['URL of Product', 'Product Name', 'Current Price', 'Target Price', 'Last Checked', 'Recipient Email'])

def is_valid_email(email):
    """Validate an email address format"""
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def get_product_details(url):
    # Custom headers to mimic a browser request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return None, None, None
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Extract product name
    product_name = soup.find("span", attrs={"id": 'productTitle'})
    if product_name:
        product_name = product_name.text.strip()
    else:
        product_name = "Product name not found"
    
    # Extract product price - Amazon's HTML structure can change, so multiple selectors are tried
    price = None
    price_selectors = [
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
        ".a-price-whole",
        ".a-size-medium.a-color-price"
    ]
    
    for selector in price_selectors:
        price_element = soup.select_one(selector)
        if price_element:
            price_text = price_element.text.strip()
            # Extract only the number from the price text
            price = ''.join(filter(lambda x: x.isdigit() or x == '.', price_text))
            try:
                price = float(price)
                break
            except ValueError:
                price = None
    
    # Try to find an image
    image_url = None
    image_element = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"id": "imgBlkFront"})
    if image_element and 'src' in image_element.attrs:
        image_url = image_element['src']
    
    return product_name, price, response.url, image_url

def add_product(url, target_price, recipient_email):
    # Validate recipient email
    if not is_valid_email(recipient_email):
        return False, "Invalid email format"
        
    product_name, current_price, final_url, image_url = get_product_details(url)
    
    if not product_name or not current_price:
        return False, "Failed to get product details"
    
    # Add to CSV file - using utf-8 encoding to handle special characters
    with open(DATA_FILE, 'a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([final_url, product_name, current_price, target_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), recipient_email])
    
    # Check if current price is already below target, send immediate notification
    if current_price <= float(target_price):
        send_notification({
            'name': product_name,
            'url': final_url,
            'old_price': current_price + 100,  # Just for display purposes
            'current_price': current_price,
            'target_price': float(target_price),
            'recipient_email': recipient_email
        })
        return True, f"Product added and notification sent! Current price (₹{current_price}) is already below your target price!"
    
    return True, f"Product added successfully! You will be notified when price drops below ₹{target_price}"

def get_all_products():
    products = []
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        return products
    
    with open(DATA_FILE, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # Skip header
        
        for row in reader:
            if len(row) >= 6:  # Make sure we have all required fields
                url, product_name, current_price, target_price, last_checked, recipient_email = row
                products.append({
                    'url': url,
                    'name': product_name,
                    'current_price': float(current_price),
                    'target_price': float(target_price),
                    'last_checked': last_checked,
                    'recipient_email': recipient_email
                })
    
    return products

def check_prices():
    updated_rows = []
    products_to_notify = []
    
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        return "No products to check."
    
    with open(DATA_FILE, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip header
        
        for row in reader:
            if len(row) < 6:  # Make sure we have all required fields
                continue
                
            url, product_name, old_price, target_price, last_checked, recipient_email = row
            
            # Convert to appropriate types
            old_price = float(old_price)
            target_price = float(target_price)
            
            product_name, current_price, _, _ = get_product_details(url)
            
            if not current_price:
                updated_rows.append(row)
                continue
            
            # Update the row with current price and timestamp
            updated_row = [url, product_name, current_price, target_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), recipient_email]
            updated_rows.append(updated_row)
            
            # Check if price dropped below target AND is lower than previous price
            if current_price <= target_price and current_price < old_price:
                products_to_notify.append({
                    'name': product_name,
                    'url': url,
                    'old_price': old_price,
                    'current_price': current_price,
                    'target_price': target_price,
                    'recipient_email': recipient_email
                })
    
    # Update the CSV file with new prices
    with open(DATA_FILE, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['URL Of Product', 'Product Name', 'Current Price', 'Target Price', 'Last Checked', 'Recipient Email'])
        writer.writerows(updated_rows)
    
    # Send notifications for products with price drops
    notification_sent = False
    for product in products_to_notify:
        if send_notification(product):
            notification_sent = True
    
    if notification_sent:
        return "Price check completed. Notifications sent for products with price drops!"
    else:
        return "Price check completed. No price drops detected."

def send_notification(product):
    # Check if sender email and password are configured
    global SENDER_EMAIL, SENDER_PASSWORD
    if SENDER_EMAIL == "your_email@gmail.com" or SENDER_PASSWORD == "your_app_password":
        return False
    
    # Create email content
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = product['recipient_email']
    msg['Subject'] = f"Price Alert: {product['name']}"
    
    body = f"""
    <html>
      <body>
        <h2>Amazon Price Alert!</h2>
        <p>Good news! The product you're tracking is available at your target price or lower.</p>
        <p><b>Product:</b> {product['name']}</p>
        <p><b>Current price:</b> ₹{product['current_price']:.2f}</p>
        <p><b>Your target price:</b> ₹{product['target_price']:.2f}</p>
        <p><b>You're saving:</b> ₹{product['old_price'] - product['current_price']:.2f}</p>
        <p><a href="{product['url']}">Click here to view the product</a></p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(body, 'html'))
    
    try:
        # Connect to Gmail SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        # Send email
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        return False

def send_test_email(recipient_email):
    """Send a test email to verify email configuration"""
    global SENDER_EMAIL, SENDER_PASSWORD
    
    if not is_valid_email(recipient_email):
        return False, "Invalid email format"
        
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    msg['Subject'] = "Amazon Price Tracker - Test Email"
    
    body = """
    <html>
      <body>
        <h2>Test Email from Amazon Price Tracker</h2>
        <p>This is a test email to confirm that your Amazon Price Tracker email notifications are working correctly.</p>
        <p>You will receive similar emails when prices drop for your tracked products.</p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(body, 'html'))
    
    try:
        # Connect to Gmail SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        # Send email
        server.send_message(msg)
        server.quit()
        return True, "Test email sent successfully!"
    except Exception as e:
        return False, f"Failed to send test email: {str(e)}"

def configure_sender_email(email, password):
    global SENDER_EMAIL, SENDER_PASSWORD
    
    if not is_valid_email(email):
        return False, "Invalid email format"
    
    SENDER_EMAIL = email
    SENDER_PASSWORD = password
    return True, "Email configuration saved successfully!"

def delete_product(index):
    products = get_all_products()
    
    if 0 <= index < len(products):
        # Remove the product at the specified index
        del products[index]
        
        # Write back the updated products list
        with open(DATA_FILE, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['URL', 'Product Name', 'Current Price', 'Target Price', 'Last Checked', 'Recipient Email'])
            
            for product in products:
                writer.writerow([
                    product['url'],
                    product['name'],
                    product['current_price'],
                    product['target_price'],
                    product['last_checked'],
                    product['recipient_email']
                ])
        
        return True
    
    return False

@app.route('/')
def index():
    products = get_all_products()
    return render_template('index.html', products=products, email_configured=(SENDER_EMAIL != "your_email@gmail.com"))

@app.route('/add_product', methods=['GET', 'POST'])
def add_product_route():
    if request.method == 'POST':
        url = request.form.get('url')
        target_price = request.form.get('target_price')
        recipient_email = request.form.get('recipient_email')
        
        success, message = add_product(url, target_price, recipient_email)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
        
        return redirect(url_for('index'))
    
    return render_template('add_product.html')

@app.route('/check_prices')
def check_prices_route():
    message = check_prices()
    flash(message, 'info')
    return redirect(url_for('index'))

@app.route('/configure_email', methods=['GET', 'POST'])
def configure_email_route():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        success, message = configure_sender_email(email, password)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
        
        return redirect(url_for('index'))
    
    return render_template('configure_email.html')

@app.route('/send_test_email', methods=['GET', 'POST'])
def test_email_route():
    if request.method == 'POST':
        recipient_email = request.form.get('recipient_email')
        
        success, message = send_test_email(recipient_email)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
        
        return redirect(url_for('index'))
    
    return render_template('test_email.html')

@app.route('/delete_product/<int:index>')
def delete_product_route(index):
    if delete_product(index):
        flash('Product deleted successfully!', 'success')
    else:
        flash('Failed to delete product.', 'danger')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
