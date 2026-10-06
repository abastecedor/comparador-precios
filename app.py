from flask import Flask, render_template, request, jsonify, Response, send_file, make_response, send_from_directory
import pandas as pd
import threading
import queue
import logging
import logging.handlers
import json
import time
import os
import sys
from utils_config import configurar_logging_shared, get_singleton_lock
from comparador_completo import run_scraper, OUTPUT_FILE, STOP_EVENT

# Configurar logging centralizado
configurar_logging_shared()

app = Flask(__name__)

# Queue for inter-thread communication (logs)
log_queue = queue.Queue()

# Queue for product updates (real-time monitoring)
product_queue = queue.Queue()

# Thread handling
scraper_thread = None
pause_event = threading.Event()
pause_event.set() # Inicialmente en estado "Ejecutando"

# Heartbeat variables for auto-shutdown when browser tab is closed
last_heartbeat = time.time()
heartbeat_active = False

def heartbeat_monitor():
    global last_heartbeat, heartbeat_active
    while True:
        time.sleep(5)
        # Aumentamos el margen a 120 segundos para evitar que Chrome mate el proceso
        # si el usuario minimiza o cambia de pestaña (los navegadores limitan setInterval en background)
        if heartbeat_active and (time.time() - last_heartbeat > 120):
            print("🛑 El navegador se cerró o se perdió conexión prolongada. Apagando el servidor...")
            STOP_EVENT.set()
            time.sleep(1)
            os._exit(0)

threading.Thread(target=heartbeat_monitor, daemon=True).start()

@app.route('/heartbeat', methods=['POST'])
def handle_heartbeat():
    global last_heartbeat, heartbeat_active
    last_heartbeat = time.time()
    heartbeat_active = True
    return jsonify({"status": "ok"})

@app.route('/')
def index():
    logging.info(">>> Accediendo a la ruta principal / (index.html)")
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
    
    # Detener cualquier thread anterior
    STOP_EVENT.set()
    time.sleep(1)
    STOP_EVENT.clear()
    
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
        'disco': data.get('disco') == 'on',
        'maxiconsumo': data.get('maxiconsumo') == 'on',
        'coto': data.get('coto') == 'on'
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
            
            # Get optional plu column if it exists
            col_plu = valid_cols_map.get('plu')  # None si no existe en el archivo
            
            # Create a clean DataFrame with standardized column names
            # This ensures consistency with individual EAN search behavior
            input_df = pd.DataFrame({
                'codigo': df[col_codigo],
                'ean': df[col_ean],
                'descripcion': df[col_descripcion],
                'plu': df[col_plu] if col_plu else '',  # PLU para Coto (opcional)
            })
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error al leer el archivo: {str(e)}'}), 400
    
    # Priority to individual EAN
    if individual_ean:
        input_df = pd.DataFrame([{
            'codigo': '9999',
            'ean': individual_ean,
            'plu': individual_ean,   # Coto usa PLU para buscar
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
    for h in list(root_logger.handlers):
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
    setattr(scraper_thread, 'start_time', time_module.time())
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

# =====================================================
# SCRAPING DE IMÁGENES
# =====================================================

# Cola para actualizaciones de progreso de imágenes
image_progress_queue = queue.Queue()
image_scraper_thread = None
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagenes_productos")


def _fetch_image_for_ean(session, ean):
    """Intenta obtener la URL de imagen de un EAN desde múltiples fuentes.
    Devuelve la URL de imagen o None si no se encuentra."""
    ean_str = str(ean).strip()

    # Fuentes VTEX (Carrefour, Vea, Disco)
    vtex_sources = [
        f"https://www.carrefour.com.ar/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean_str}",
        f"https://www.vea.com.ar/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean_str}",
        f"https://www.disco.com.ar/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean_str}",
    ]

    for url in vtex_sources:
        try:
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    images = data[0].get("items", [{}])[0].get("images", [])
                    if images:
                        img_url = images[0].get("imageUrl", "")
                        if img_url:
                            return img_url
        except Exception:
            continue

    # Fallback: Open Food Facts
    try:
        off_url = f"https://world.openfoodfacts.org/api/v0/product/{ean_str}.json"
        resp = session.get(off_url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == 1:
                img_url = data.get("product", {}).get("image_url", "")
                if img_url:
                    return img_url
    except Exception:
        pass

    return None


# Ruta del Excel de resultados de imágenes
IMAGE_RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagenes_resultados.xlsx")


def _run_image_scraper(productos, progress_queue):
    """Worker thread: descarga imágenes para cada EAN.
    productos: dict {ean_str: {"sku": str, "codigo": str}} con los productos a procesar.
    Las imágenes se guardan con el nombre del campo 'codigo' (fallback: ean).
    """
    import requests
    os.makedirs(IMAGES_DIR, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    })

    eans = list(productos.keys())
    total = len(eans)
    encontradas = 0
    no_encontradas = 0

    # Lista para armar el Excel resultante
    resultados = []

    progress_queue.put({"type": "start", "total": total})

    for i, ean_str in enumerate(eans):
        info = productos.get(ean_str, {})
        sku_str = info.get("sku", "")
        codigo_str = info.get("codigo", "") or ean_str  # fallback al EAN si no hay codigo

        # El archivo se nombra con el codigo
        dest_path = os.path.join(IMAGES_DIR, f"{codigo_str}.jpg")

        # Si ya existe, saltar
        if os.path.exists(dest_path):
            progress_queue.put({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "ean": ean_str,
                "status": "exists",
                "msg": f"Ya existe ({codigo_str}.jpg)"
            })
            encontradas += 1
            resultados.append({"Codigo": codigo_str, "SKU": sku_str, "EAN": ean_str, "Estado": "Ya existía"})
            continue

        img_url = _fetch_image_for_ean(session, ean_str)

        if img_url:
            try:
                img_resp = session.get(img_url, timeout=15)
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    with open(dest_path, "wb") as f:
                        f.write(img_resp.content)
                    encontradas += 1
                    progress_queue.put({
                        "type": "progress",
                        "current": i + 1,
                        "total": total,
                        "ean": ean_str,
                        "status": "ok",
                        "msg": f"✅ Guardada como {codigo_str}.jpg"
                    })
                    resultados.append({"Codigo": codigo_str, "SKU": sku_str, "EAN": ean_str, "Estado": "Descargada"})
                else:
                    raise ValueError("Imagen inválida o muy pequeña")
            except Exception:
                no_encontradas += 1
                progress_queue.put({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "ean": ean_str,
                    "status": "error",
                    "msg": f"Error al descargar ({codigo_str})"
                })
                resultados.append({"Codigo": codigo_str, "SKU": sku_str, "EAN": ean_str, "Estado": "Error al descargar"})
        else:
            no_encontradas += 1
            progress_queue.put({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "ean": ean_str,
                "status": "not_found",
                "msg": f"❌ No encontrada ({codigo_str})"
            })
            resultados.append({"Codigo": codigo_str, "SKU": sku_str, "EAN": ean_str, "Estado": "No encontrada"})

        # Pequeña pausa para no saturar las APIs
        time.sleep(0.1)

    # Generar Excel con resultados (Codigo / SKU / EAN / Estado)
    try:
        df_result = pd.DataFrame(resultados, columns=["Codigo", "SKU", "EAN", "Estado"])
        df_result.to_excel(IMAGE_RESULTS_FILE, index=False)
        excel_generado = True
    except Exception as e:
        logging.error(f"Error generando Excel de imágenes: {e}")
        excel_generado = False

    progress_queue.put({
        "type": "done",
        "total": total,
        "encontradas": encontradas,
        "no_encontradas": no_encontradas,
        "carpeta": IMAGES_DIR,
        "excel_generado": excel_generado
    })


@app.route('/scrape_images', methods=['POST'])
def scrape_images():
    """Inicia el proceso de scraping de imágenes."""
    global image_scraper_thread

    # Limpiar la cola
    with image_progress_queue.mutex:
        image_progress_queue.queue.clear()

    # Obtener productos como dict {ean: {"sku": ..., "codigo": ...}}
    productos = {}  # preserva orden

    def _extraer_productos(df):
        """Extrae dict {ean: {sku, codigo}} de un DataFrame."""
        col_map = {c.strip().lower(): c for c in df.columns}
        col_ean = col_map.get('ean')
        if not col_ean:
            return None, 'El archivo no tiene columna "ean"'
        col_sku = col_map.get('sku')
        col_codigo = col_map.get('codigo')
        result = {}
        for _, row in df.iterrows():
            ean_val = str(row[col_ean]).strip()
            if not ean_val or ean_val == 'nan':
                continue
            sku_val = str(row[col_sku]).strip() if col_sku and pd.notna(row[col_sku]) else ""
            cod_val = str(row[col_codigo]).strip() if col_codigo and pd.notna(row[col_codigo]) else ""
            result.setdefault(ean_val, {"sku": sku_val, "codigo": cod_val})
        return result, None

    file = request.files.get('file')
    if file and file.filename:
        try:
            filename = file.filename.lower()
            if filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file, dtype=str)
            elif filename.endswith('.csv'):
                df = pd.read_csv(file, sep=None, engine='python', dtype=str)
            else:
                return jsonify({'status': 'error', 'message': 'Formato no soportado'}), 400
            productos, err = _extraer_productos(df)
            if err:
                return jsonify({'status': 'error', 'message': err}), 400
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error leyendo archivo: {str(e)}'}), 400
    elif os.path.exists(OUTPUT_FILE):
        try:
            df = pd.read_excel(OUTPUT_FILE, dtype=str)
            productos, _ = _extraer_productos(df)
            productos = productos or {}
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error leyendo resultados: {str(e)}'}), 400

    if not productos:
        return jsonify({'status': 'error', 'message': 'No se encontraron EANs. Sube un archivo o realiza un escaneo primero.'}), 400

    image_scraper_thread = threading.Thread(
        target=_run_image_scraper,
        args=(productos, image_progress_queue),
        daemon=True
    )
    image_scraper_thread.start()

    return jsonify({'status': 'success', 'message': f'Iniciando descarga de {len(productos)} imágenes...', 'total': len(productos)})


@app.route('/stream_image_progress')
def stream_image_progress():
    """SSE stream para el progreso de descarga de imágenes."""
    def generate():
        while True:
            try:
                data = image_progress_queue.get(timeout=1)
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("type") == "done":
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            except Exception:
                break
    return Response(generate(), mimetype='text/event-stream')


@app.route('/open_images_folder', methods=['POST'])
def open_images_folder():
    """Abre la carpeta de imágenes en el explorador de Windows."""
    import subprocess
    os.makedirs(IMAGES_DIR, exist_ok=True)
    try:
        subprocess.Popen(['explorer', IMAGES_DIR])
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/download_image_results')
def download_image_results():
    """Descarga el Excel de resultados de la búsqueda de imágenes."""
    if os.path.exists(IMAGE_RESULTS_FILE):
        response = make_response(send_file(IMAGE_RESULTS_FILE, as_attachment=True))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return "Archivo no encontrado", 404


if __name__ == '__main__':
    import webbrowser
    import socket
    import subprocess
    import os
    
    def kill_zombie_python_ports(start_port=8080, end_port=8099):
        """Busca puertos ocupados por procesos 'python.exe' colgados y los mata"""
        try:
            for port in range(start_port, end_port + 1):
                if os.name == 'nt': # Windows
                    try:
                        # Identificar PIDs escuchando en este puerto
                        output = subprocess.check_output(f'netstat -aon | findstr :{port} | findstr LISTENING', shell=True).decode()
                        for line in output.splitlines():
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                pid = parts[-1]
                                if int(pid) > 0 and int(pid) != os.getpid():
                                    # Asegurarnos de que el proceso colgado sea Python antes de matarlo (para no romper otras apps del sistema)
                                    try:
                                        tasklist_out = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /NH', shell=True).decode().lower()
                                        if "python" in tasklist_out:
                                            logging.warning(f"Matando instancia zombie de Python (PID {pid}) que bloqueaba el puerto {port}")
                                            subprocess.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
                                    except Exception:
                                        pass
                    except subprocess.CalledProcessError:
                        pass # No hay nada escuchando en ese puerto
        except Exception as e:
            logging.error(f"Error durante la limpieza de puertos zombie: {e}")

    def find_free_port(start_port=8080, max_port=8099):
        for port in range(start_port, max_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', port))
                    return port
                except OSError:
                    continue
        return None

    # 1. Limpiar procesos de python atorados en los puertos que usamos
    kill_zombie_python_ports()
    
    # 2. Buscar el primer puerto dinámico verdaderamente libre
    free_port = find_free_port()
    if not free_port:
        print("❌ CRÍTICO: No se encontraron puertos libres entre 8080 y 8099. El servidor no puede arrancar.")
        sys.exit(1)

    print("="*60)
    print(f"  COMPARADOR DE PRECIOS - Iniciando en http://127.0.0.1:{free_port}")
    print("="*60)
    
    # Abrir el navegador apuntando al puerto que encontramos
    def _open_browser():
        import time as _t
        _t.sleep(3)
        webbrowser.open(f'http://127.0.0.1:{free_port}')
        
    import threading as _th
    _th.Thread(target=_open_browser, daemon=True).start()
    
    # Arrancar el servidor Flask en el puerto libre
    app.run(debug=False, port=free_port, host='127.0.0.1', use_reloader=False)
