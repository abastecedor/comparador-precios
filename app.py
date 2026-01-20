from flask import Flask, render_template, request, jsonify, Response, send_file, make_response
import pandas as pd
import threading
import queue
import logging
import json
import time
import os
from comparador_completo import run_scraper, OUTPUT_FILE

app = Flask(__name__)

# Queue for inter-thread communication (logs)
log_queue = queue.Queue()

# Thread handling
scraper_thread = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_scraper():
    global scraper_thread
    
    if scraper_thread and scraper_thread.is_alive():
        return jsonify({'status': 'error', 'message': 'El proceso ya está en ejecución.'}), 400

    # Handle Flask FormData
    data = request.form
    selection = {
        'nini': data.get('nini') == 'on',
        'carrefour': data.get('carrefour') == 'on',
        'vea': data.get('vea') == 'on',
        'disco': data.get('disco') == 'on'
    }
    ignore_cache = data.get('ignore_cache') == 'on'
    
    # Handle File Upload
    file = request.files.get('file')
    input_df = None
    
    if file and file.filename != '':
        try:
            filename = file.filename.lower()
            df = None
            
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(file, dtype=str)
            elif filename.endswith('.csv'):
                # Intentar leer con detección automática, si falla probar comúnes
                try:
                    file.seek(0)
                    df = pd.read_csv(file, sep=None, engine='python', dtype=str)
                except:
                    file.seek(0)
                    try:
                        df = pd.read_csv(file, sep=';', dtype=str)
                    except:
                        file.seek(0)
                        df = pd.read_csv(file, sep=',', dtype=str)
            else:
                return jsonify({'status': 'error', 'message': 'Formato de archivo no soportado. Use CSV o Excel.'}), 400

            if df is None:
                 return jsonify({'status': 'error', 'message': 'No se pudo leer el archivo.'}), 400

            # Normalize columns helper
            import unicodedata
            def normalize(text):
                if not isinstance(text, str): return str(text)
                return "".join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).lower().strip()

            # Create a map of normalized -> original
            valid_cols_map = {normalize(c): c for c in df.columns}
            
            required_cols = ['codigo', 'ean', 'descripcion']
            missing = [req for req in required_cols if req not in valid_cols_map]

            if missing:
                 found_cols = ", ".join(df.columns.tolist())
                 return jsonify({'status': 'error', 'message': f'Faltan columnas: {", ".join(missing)}. Columnas encontradas: {found_cols}'}), 400
            
            # Rename recognized columns to standard names if needed, but for now just use the map to get data
            # We need to construct a clean DF with 'SKU' (from ean), 'codigo', 'descripcion'
            
            # Usar los nombres originales que mapean a los requeridos
            col_ean = valid_cols_map['ean']
            
            df['SKU'] = df[col_ean]
            input_df = df
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error al leer el archivo: {str(e)}'}), 400

    # Clear queue
    with log_queue.mutex:
        log_queue.queue.clear()

    # If a file is uploaded, implicitly we should probably ignore cache 
    # unless logic dictates otherwise, but to be safe and avoid "stale data" confusion:
    if input_df is not None:
         ignore_cache = True
    
    # Start scraper in a separate thread
    scraper_thread = threading.Thread(
        target=run_scraper,
        args=(selection, log_queue, input_df, ignore_cache)
    )
    scraper_thread.start()

    return jsonify({'status': 'success', 'message': 'Escaneo iniciado'})

@app.route('/stream_logs')
def stream_logs():
    def generate():
        while True:
            try:
                # Wait for log message, timeout allows checking connection status
                record = log_queue.get(timeout=1)
                
                if record == "STOP_SIGNAL":
                     yield f"data: {json.dumps({'message': 'STOP_SIGNAL', 'level': 'INFO'})}\n\n"
                     break

                # Format log record
                if isinstance(record, logging.LogRecord):
                    msg = record.getMessage()
                    level = record.levelname
                else:
                    msg = str(record)
                    level = "INFO"
                
                yield f"data: {json.dumps({'message': msg, 'level': level})}\n\n"
            
            except queue.Empty:
                # Send heartbeat
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"
                continue
            except Exception as e:
                # In case of broken pipe or other errors
                break
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/download')
def download_file():
    if os.path.exists(OUTPUT_FILE):
        # Usar send_file pero asegurar que no se cachee
        response = make_response(send_file(OUTPUT_FILE, as_attachment=True))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return "Archivo no encontrado", 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
