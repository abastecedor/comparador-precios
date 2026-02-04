from flask import Flask, render_template, request, jsonify, Response, send_file, make_response
import pandas as pd
import threading
import queue
import logging
import logging.handlers
import json
import time
import os
from comparador_completo import run_scraper, OUTPUT_FILE

app = Flask(__name__)

# Queue for inter-thread communication (logs)
log_queue = queue.Queue()

# Queue for product updates (real-time monitoring)
product_queue = queue.Queue()

# Thread handling
scraper_thread = None
pause_event = threading.Event()
pause_event.set() # Inicialmente en estado "Ejecutando"

@app.route('/')
def index():
    print("DEBUG: Accediendo a la ruta principal (index)")
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_scraper():
    global scraper_thread
    
    # VERSION MARKER - CÓDIGO NUEVO CARGADO
    print("=" * 80)
    print(">>> VERSIÓN NUEVA DEL CÓDIGO ACTIVA - CON RESET FUNCTIONALITY <<<")
    print("=" * 80)
    logging.warning("🔍 start_scraper llamado - VERSION NUEVA con thread timeout")
    
    # Verificar si hay un thread activo
    if scraper_thread and scraper_thread.is_alive():
        # DEBUG: Log thread state
        logging.warning(f"DEBUG: Thread detected as alive. Thread ID: {scraper_thread.ident}")
        
        # Verificar si el thread tiene más de 10 minutos (probablemente zombie)
        import time as time_module
        thread_start = getattr(scraper_thread, 'start_time', None)
        current_time = time_module.time()
        
        if thread_start is not None:
            thread_age = current_time - thread_start
            logging.warning(f"DEBUG: Thread has start_time. Age: {thread_age:.0f}s")
        else:
            thread_age = 0
            logging.warning(f"DEBUG: Thread missing start_time attribute! Setting age to 0")
        
        if thread_age > 600:  # 10 minutos
            logging.warning(f"Thread zombie detectado (edad: {thread_age:.0f}s). Permitiendo override.")
            # Marcar como None para permitir nuevo thread
            scraper_thread = None
        else:
            error_msg = f'El proceso ya está en ejecución. Tiempo transcurrido: {int(thread_age)}s. Si el proceso está colgado, espera unos minutos o reinicia el servidor.'
            logging.warning(f"DEBUG: Returning error: {error_msg}")
            return jsonify({
                'status': 'error', 
                'message': error_msg
            }), 400

    # Handle Flask FormData
    data = request.form
    selection = {
        'nini': data.get('nini') == 'on',
        'carrefour': data.get('carrefour') == 'on',
        'vea': data.get('vea') == 'on',
        'disco': data.get('disco') == 'on'
    }
    ignore_cache = data.get('ignore_cache') == 'on'
    
    # Handle Individual EAN
    individual_ean = data.get('individual_ean', '').strip()
    
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
            
            # Get the original column names for all required columns
            col_codigo = valid_cols_map['codigo']
            col_ean = valid_cols_map['ean']
            col_descripcion = valid_cols_map['descripcion']
            
            # Create a clean DataFrame with standardized column names
            # This ensures consistency with individual EAN search behavior
            input_df = pd.DataFrame({
                'codigo': df[col_codigo],
                'ean': df[col_ean],
                'descripcion': df[col_descripcion],
                'SKU': df[col_ean]  # SKU is set from EAN
            })
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error al leer el archivo: {str(e)}'}), 400
    
    # Priority to individual EAN
    if individual_ean:
        input_df = pd.DataFrame([{
            'codigo': '9999',
            'ean': individual_ean,
            'descripcion': 'Búsqueda Individual',
            'SKU': individual_ean
        }])
        ignore_cache = True
        logging.info(f"Procesando búsqueda individual para EAN: {individual_ean}")

    # Clear queues
    with log_queue.mutex:
        log_queue.queue.clear()
    with product_queue.mutex:
        product_queue.queue.clear()

    # If a file is uploaded, implicitly we should probably ignore cache 
    # unless logic dictates otherwise, but to be safe and avoid "stale data" confusion:
    if input_df is not None:
         ignore_cache = True
    
    # Configurar logger para capturar logs en la cola de forma limpia
    root_logger = logging.getLogger()
    
    # Eliminar handlers antiguos de tipo QueueHandler para evitar duplicados
    for h in root_logger.handlers[:]:
        if isinstance(h, logging.handlers.QueueHandler):
            root_logger.removeHandler(h)
            
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.INFO)
    
    # Reset pause event
    pause_event.set()
    
    # Start scraper in a separate thread
    scraper_thread = threading.Thread(
        target=run_scraper,
        args=(selection, log_queue, input_df, ignore_cache, pause_event, product_queue)
    )
    # Marcar tiempo de inicio para detectar threads zombies
    import time as time_module
    scraper_thread.start_time = time_module.time()
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
                     # Enviar señal de fin limpia
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

@app.route('/stream_products')
def stream_products():
    """Stream product updates in real-time for monitoring tab"""
    def generate():
        while True:
            try:
                # Wait for product update
                product_data = product_queue.get(timeout=1)
                
                if product_data == "STOP_SIGNAL":
                    yield f"data: {json.dumps({'type': 'stop'})}\n\n"
                    break
                
                # Send product update
                yield f"data: {json.dumps(product_data)}\n\n"
            
            except queue.Empty:
                # Send heartbeat
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            except Exception as e:
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

@app.route('/pause', methods=['POST'])
def pause_scraper():
    pause_event.clear()
    return jsonify({'status': 'success', 'message': 'Scraper pausado'})

@app.route('/continue', methods=['POST'])
def continue_scraper():
    pause_event.set()
    return jsonify({'status': 'success', 'message': 'Scraper reanudado'})

@app.route('/reset', methods=['POST'])
def reset_scraper():
    """Endpoint para forzar reset del scraper en caso de thread zombie"""
    global scraper_thread
    
    try:
        # Intentar limpiar procesos chrome
        import subprocess
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'], 
                          capture_output=True, timeout=5)
            subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'], 
                          capture_output=True, timeout=5)
        except:
            pass
        
        # Resetear el thread
        scraper_thread = None
        
        # Limpiar colas
        with log_queue.mutex:
            log_queue.queue.clear()
        with product_queue.mutex:
            product_queue.queue.clear()
        
        logging.info("🔄 Sistema reseteado manualmente")
        return jsonify({'status': 'success', 'message': 'Sistema reseteado. Puedes iniciar un nuevo escaneo.'})
    
    except Exception as e:
        logging.error(f"Error al resetear: {e}")
        return jsonify({'status': 'error', 'message': f'Error al resetear: {str(e)}'}), 500

if __name__ == '__main__':
    print("🚀 Iniciando servidor Flask en http://localhost:5000")
    app.run(debug=False, port=5000, host='0.0.0.0')
