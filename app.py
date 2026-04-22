from flask import Flask, render_template, request, url_for, send_from_directory
import barcode
from barcode.writer import ImageWriter
import os
import re
import pandas as pd
import zipfile

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
os.makedirs(STATIC_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='/static')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(STATIC_FOLDER, filename)


# =========================
# HELPERS
# =========================
def numeric_only(text):
    return re.sub(r'\D', '', text)


def normalize_data(row):
    return {
        "brand": row.get('brand_name') or row.get('brand'),
        "product": row.get('product_name') or row.get('product'),
        "sku": row.get('sku no.') or row.get('sku') or row.get('sku_number'),
        "size": row.get('size'),
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

    try:
        top_gap = float(request.form.get('top_gap')) * mm if request.form.get('top_gap') else 10 * mm
    except:
        top_gap = 10 * mm

    try:
        bottom_gap = float(request.form.get('bottom_gap')) * mm if request.form.get('bottom_gap') else 10 * mm
    except:
        bottom_gap = 10 * mm

    if not file or file.filename == '':
        return render_template('index.html', error='Upload CSV file')

    try:
        try:
            df = pd.read_csv(file, encoding='utf-8-sig')
        except:
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

            safe_sku = re.sub(r'[^A-Za-z0-9_-]', '_', sku)
            filename = f'barcode_{safe_sku}_{idx}.png'
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
                'row_number': idx + 2
            })

        if not results:
            return render_template('index.html', error='No valid rows', row_errors=errors)

        # ZIP
        zip_path = os.path.join(STATIC_FOLDER, 'barcodes.zip')
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for r in results:
                full = os.path.join(STATIC_FOLDER, r['barcode_path'])
                if os.path.exists(full):
                    zipf.write(full, r['barcode_path'])

        # PDF
        pdf_path = os.path.join(STATIC_FOLDER, 'labels_12_per_page.pdf')

        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4

        cols = 2
        rows = 6

        vertical_gap = 7 * mm
        side_margin = 5 * mm

        usable_height = height - top_gap - bottom_gap - (vertical_gap * (rows - 1))
        usable_width = width - (side_margin * 2)

        label_width = usable_width / cols
        label_height = usable_height / rows

        for item in results:

            barcode_path = os.path.join(STATIC_FOLDER, item['barcode_path'])

            if not os.path.exists(barcode_path):
                continue

            data = item['data']

            for i in range(12):

                col = i % cols
                row = i // cols

                x = side_margin + col * label_width
                y = height - top_gap - (row + 1) * label_height - row * vertical_gap

                c.rect(x + 5, y + 5, label_width - 10, label_height - 10)

                text_x = x + 10
                text_y = y + label_height - 15

                c.setFont("Helvetica", 7)

                # ✅ ALWAYS PRINT ALL FIELDS
                def draw(label, value):
                    nonlocal text_y
                    display_value = value if value else "-"
                    c.drawString(text_x, text_y, f"{label}: {display_value}")
                    text_y -= 9

                draw("Brand", data.get('brand'))
                draw("Product", data.get('product'))
                draw("SKU", data.get('sku'))
                draw("Size", data.get('size'))
                draw("MRP", data.get('mrp'))
                draw("Mfg", data.get('mfg_date'))
                draw("Manufacturer", data.get('manufacturer'))
                draw("Customer Care", data.get('customer_care'))

                # ✅ DYNAMIC BARCODE (NO OVERLAP)
                barcode_top = text_y - 5
                barcode_bottom = y + 10
                barcode_height = barcode_top - barcode_bottom

                if barcode_height < 20:
                    barcode_height = 20

                c.drawImage(
                    barcode_path,
                    x + 10,
                    barcode_bottom,
                    width=label_width - 20,
                    height=barcode_height
                )

            c.showPage()

        c.save()

        return render_template(
            'index.html',
            bulk_results=results,
            row_errors=errors,
            pdf_path=url_for('static', filename='labels_12_per_page.pdf'),
            zip_path=url_for('static', filename='barcodes.zip')
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

    safe_sku = re.sub(r'[^A-Za-z0-9_-]', '_', sku)
    filename = f'barcode_{safe_sku}.png'
    filepath = os.path.join(STATIC_FOLDER, filename)

    code = barcode.get('code128', sku, writer=ImageWriter())
    code.save(filepath.replace('.png', ''))

    return render_template(
        'index.html',
        barcode_path=url_for('static', filename=filename),
        barcode_value=sku,
        numeric_sku=numeric_only(sku),
        data=data,
        copies=1
    )


if __name__ == '__main__':
    app.run(debug=True)
