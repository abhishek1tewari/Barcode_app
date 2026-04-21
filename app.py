from flask import Flask, render_template, request, url_for
import barcode
from barcode.writer import ImageWriter
import os
import re
import pandas as pd
import zipfile
import uuid

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
os.makedirs(STATIC_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='/static')


# =========================
# HOME
# =========================
@app.route('/')
def index():
    return render_template('index.html')


# =========================
# HELPERS
# =========================
def extract_quantity(value):
    if not value:
        return 1
    match = re.search(r'\d+', str(value))
    return int(match.group()) if match else 1


def numeric_only(text):
    return re.sub(r'\D', '', text)


def normalize_data(row):
    return {
        "brand": row.get('brand_name') or row.get('brand'),
        "product": row.get('product_name') or row.get('product'),
        "sku": row.get('sku no.') or row.get('sku') or row.get('sku_number'),
        "size": row.get('size'),
        "gender": row.get('gender'),
        "quantity": row.get('quantity'),
        "mrp": row.get('mrp'),
        "mfg_date": row.get('manufacture_month_year') or row.get('mfg date'),
        "manufacturer": row.get('manufactured_by') or row.get('manufacturer'),
        "customer_care": row.get('customer_care')
    }


# =========================
# CSV UPLOAD
# =========================
@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    file = request.files.get('csv_file')

    if not file or file.filename == '':
        return render_template('index.html', error='Upload CSV file')

    try:
        # Safe CSV reading
        try:
            df = pd.read_csv(file, encoding='utf-8')
        except:
            file.seek(0)
            df = pd.read_csv(file, encoding='latin1')

        df.columns = df.columns.str.strip().str.lower()

        results = []
        errors = []

        for idx, row in df.iterrows():
            raw_data = {k: str(v).strip() for k, v in row.items() if pd.notna(v)}
            data = normalize_data(raw_data)

            sku = (data.get('sku') or '').strip()

            if not sku:
                errors.append(f'Row {idx+2}: Missing SKU')
                continue

            quantity = extract_quantity(data.get('quantity'))
            data['quantity'] = quantity

            safe_sku = re.sub(r'[^A-Za-z0-9_-]', '_', sku)
            unique_id = uuid.uuid4().hex

            filename = f'barcode_{safe_sku}_{unique_id}.png'
            filepath = os.path.join(STATIC_FOLDER, filename)

            try:
                code = barcode.get('code128', sku, writer=ImageWriter())
                code.save(filepath.replace('.png', ''))
            except Exception as e:
                errors.append(f'Row {idx+2}: {str(e)}')
                continue

            results.append({
                'data': data,
                'barcode_path': filename,
                'barcode_value': sku,
                'numeric_sku': numeric_only(sku),
                'quantity': quantity,
                'row_number': idx + 2
            })

        if not results:
            return render_template('index.html', error='No valid rows', row_errors=errors)

        # =========================
        # ZIP FILE
        # =========================
        zip_filename = f'barcodes_{uuid.uuid4().hex}.zip'
        zip_path = os.path.join(STATIC_FOLDER, zip_filename)

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for r in results:
                full = os.path.join(STATIC_FOLDER, r['barcode_path'])
                if os.path.exists(full):
                    zipf.write(full, r['barcode_path'])

        # =========================
        # PDF FILE
        # =========================
        pdf_filename = f'labels_{uuid.uuid4().hex}.pdf'
        pdf_path = os.path.join(STATIC_FOLDER, pdf_filename)

        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4

        cols = 2
        rows = 6

        label_width = width / cols
        label_height = height / rows

        for item in results:
            barcode_path = os.path.join(STATIC_FOLDER, item['barcode_path'])

            if not os.path.exists(barcode_path):
                continue

            data = item['data']

            for i in range(12):
                col = i % cols
                row = i // cols

                x = col * label_width
                y = height - ((row + 1) * label_height)

                # Border
                c.rect(x + 5, y + 5, label_width - 10, label_height - 10)

                text_x = x + 10
                text_y = y + label_height - 15

                c.setFont("Helvetica", 7)

                def draw(label, value):
                    nonlocal text_y
                    if value:
                        c.drawString(text_x, text_y, f"{label}: {value}")
                        text_y -= 9

                draw("Brand", data.get('brand'))
                draw("Product", data.get('product'))
                draw("SKU", data.get('sku'))
                draw("Size", data.get('size'))
                draw("Gender", data.get('gender'))
                draw("Qty", data.get('quantity'))
                draw("MRP", data.get('mrp'))
                draw("Mfg", data.get('mfg_date'))
                draw("Manufacturer", data.get('manufacturer'))
                draw("Customer Care", data.get('customer_care'))

                # Barcode image
                c.drawImage(
                    barcode_path,
                    x + 10,
                    y + 10,
                    width=label_width - 20,
                    height=35
                )

            c.showPage()

        c.save()

        return render_template(
            'index.html',
            bulk_results=results,
            row_errors=errors,
            pdf_path=url_for('static', filename=pdf_filename),
            zip_path=url_for('static', filename=zip_filename)
        )

    except Exception as e:
        return render_template('index.html', error=str(e))


# =========================
# SINGLE BARCODE
# =========================
@app.route('/generate', methods=['POST'])
def generate():
    data = request.form.to_dict()
    data = normalize_data(data)

    sku = (data.get('sku') or '').strip()

    if not sku:
        return render_template('index.html', error='Enter SKU')

    quantity = extract_quantity(data.get('quantity'))
    data['quantity'] = quantity

    safe_sku = re.sub(r'[^A-Za-z0-9_-]', '_', sku)
    unique_id = uuid.uuid4().hex

    filename = f'barcode_{safe_sku}_{unique_id}.png'
    filepath = os.path.join(STATIC_FOLDER, filename)

    code = barcode.get('code128', sku, writer=ImageWriter())
    code.save(filepath.replace('.png', ''))

    return render_template(
        'index.html',
        barcode_path=url_for('static', filename=filename),
        barcode_value=sku,
        numeric_sku=numeric_only(sku),
        data=data,
        copies=quantity
    )


# =========================
# MAIN
# =========================
if __name__ == '__main__':
    app.run(debug=True)
