# AllCart

**Everything You Love, All in One Place.**

AllCart is a Flask and MySQL store with public browsing, a customer account area and a separate administration area. The sample catalog includes 18 products across the six departments.

## Prerequisites

- Python 3.11 or newer and VS Code with its Python extension
- MySQL Server 8.0.22 or newer and the MySQL command-line client or Workbench
- Internet access for the initial Python dependency installation and the CDN-hosted icons, fonts and charts

The Flask and Werkzeug versions are pinned to support the requested Flask-MySQL-Connector extension.

## Set up MySQL

Open the extracted project folder in VS Code. From its terminal, connect to the local MySQL server using a MySQL administrator.

```powershell
mysql -h 127.0.0.1 -u root -p
```

From the MySQL prompt, run the following. Choose a unique database password before running the `CREATE USER` statement and use that same password in the Flask environment. In MySQL Workbench, you can open and execute `schema.sql` directly.

```sql
SOURCE schema.sql;
CREATE USER 'shopsphere'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_YOUR_DATABASE_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON shopsphere_db.* TO 'shopsphere'@'127.0.0.1';
EXIT;
```

## Install and launch

Run these commands in the VS Code PowerShell terminal.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "shopsphere"
$env:MYSQL_PASSWORD = "REPLACE_WITH_YOUR_DATABASE_PASSWORD"
$env:SHOPSPHERE_SECRET_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))")
$env:SHOPSPHERE_CONTACT_EMAIL = "support@your-domain.example"
.\.venv\Scripts\python.exe -m flask --app app seed
.\.venv\Scripts\python.exe -m flask --app app create-admin
.\.venv\Scripts\python.exe -m flask --app app run
```

The admin command prompts for an email, phone and password. It requires a password of at least 12 characters. Open http://127.0.0.1:5000/ to shop or register. Use the same login page for admins and customers. Flask redirects each role to its dashboard. Keep the secret in private configuration and reuse it across launches where you want sessions to survive. Set `COOKIE_SECURE=1` when serving over HTTPS.

PowerShell variables apply to the current terminal. On macOS/Linux, use `python3 -m venv .venv`, invoke `.venv/bin/python`, and set the same environment variables with `export`. To use a different MySQL host or port, update the environment variables and MySQL account grants. The application database name is `shopsphere_db`.

## Store behaviour

- Prices use INR. Delivery costs ₹49 on orders below ₹999 and is free at or above ₹999.
- Checkout offers cash on delivery and a simulation. The simulation never collects or processes real payment details.
- Orders store a snapshot of item prices, product and category names, and delivery details. Checkout locks stock and commits the order and inventory changes together. Cancellation restores inventory once.
- Customers can cancel Pending or Confirmed orders. Admins can also cancel Processing orders. Shipped orders can progress to Delivered.
- Delivered orders count toward sales. Monthly totals group orders by the month they were placed and include delivery. Category sales use merchandise revenue. Best sellers use units sold on delivered orders.
- Product removal hides the product and retains its history. Categories referenced by products must be kept or have their products reassigned. Inventory marks 1–5 units as low stock.
- A customer can write or update a review after delivery. Admins can remove reviews.
- The About and Contact pages are public. Set SHOPSPHERE_CONTACT_EMAIL to your actual support address to enable the email link.
- Newsletter sign-ups are stored in MySQL. There is no email campaign service in this project.
- The storefront uses bundled illustrative product photography. Replacing a product or category image is available from its admin edit page.

## Project layout

```text
app.py                   Application factory and setup commands
config.py                Environment configuration
database.py              Flask-MySQL Connector query helpers
routes/                  Storefront, account and administration blueprints
templates/               Shared Jinja templates and pages
static/css/              Responsive styles
static/js/               Form interactions and Chart.js configuration
static/images/           Sample catalog images and runtime uploads
schema.sql               MySQL database and all tables
seed.sql                 Sample categories, products and offers
requirements.txt         Python dependencies
```

Back up `shopsphere_db` together with `static/images/uploads` if you want to preserve admin-uploaded images. The Flask development server is intended for local development.

## Manual verification

1. Confirm all six categories appear. Search by name, filter by price and sort by price or popularity.
2. Register and sign in. Update your profile, save an address, add a product to the wishlist, move it to the cart, then adjust its quantity.
3. Checkout with a saved address. Verify order details and stock, then cancel and confirm the stock is restored.
4. Create another order using Buy now and the simulated payment option. Sign in as admin and progress it through Confirmed, Processing, Shipped and Delivered.
5. Review the delivered product as the customer and moderate the review as admin. Check dashboard totals and the reports.
6. Test product and category management, stock updates and account deactivation. Verify a customer cannot visit admin routes or another customer's orders.
