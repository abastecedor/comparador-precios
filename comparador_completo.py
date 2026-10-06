import time
import os
import threading
import pandas as pd
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import logging
from utils_config import configurar_logging_shared

# Configurar logging centralizado
configurar_logging_shared("scraper_debug.log")

# Evento global para detener threads huérfanos
STOP_EVENT = threading.Event()

# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================

HEADLESS = True

# Usar rutas relativas para compatibilidad con Railway
import os as _os
BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
INPUT_FILE = _os.path.join(BASE_DIR, "planilla_ofertas.xlsx")
OUTPUT_FILE = _os.path.join(BASE_DIR, "precios_resultados.xlsx")

print("🚀 Scraper automático de precios")

# =====================================================
# DRIVER
# =====================================================

_DRIVER_DOWNLOAD_LOCK = threading.Lock()

def configurar_driver(optimized=True):
    import random
    import threading
    
    logging.info("Iniciando configuración del driver...")
    options = Options()
    
    # Detectar si estamos en Railway/Docker (Linux)
    is_railway = os.environ.get('RAILWAY_ENVIRONMENT') or os.path.exists('/.dockerenv')
    
    # Optimizaciones de velocidad
    if optimized:
        logging.info("🚀 Modo optimizado: Bloqueando imágenes, CSS y contenido innecesario")
        prefs = {
            "profile.managed_default_content_settings.images": 2,  # Bloquear imágenes
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.stylesheets": 2,  # Bloquear CSS
            "profile.managed_default_content_settings.javascript": 1,  # Permitir JS (necesario)
            "profile.managed_default_content_settings.plugins": 2,
            "profile.managed_default_content_settings.popups": 2,
            "profile.managed_default_content_settings.geolocation": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")
    
    if HEADLESS or is_railway:
        logging.info("Modo Headless activado")
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
    else:
         logging.info("Modo Headless desactivado - Abriendo navegador")
         options.add_argument("--start-maximized")

    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--log-level=3")
    
    # Parches Anti-Bot avanzados para bypass Azion CDN (Maxiconsumo)
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    
    # Opciones adicionales para Railway/Docker
    if is_railway:
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--remote-debugging-port=9222")
        
        # CRÍTICO: Prevenir "unable to connect to renderer"
        options.add_argument("--single-process")  # Ejecutar en proceso único
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-setuid-sandbox")
        
        # Flags para reducir consumo de memoria y evitar crashes
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-crash-reporter")
        options.add_argument("--disable-oopr-debug-crash-dump")
        options.add_argument("--no-crash-upload")
        options.add_argument("--memory-pressure-off")
        options.add_argument("--mute-audio")
        
        logging.info("Configuración Railway/Docker optimizada aplicada")


    # Retry logic para evitar conflictos de archivos en multithreading
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Crear un Service único para este thread con un puerto aleatorio
            # Esto evita conflictos cuando múltiples threads intentan usar el mismo chromedriver
            
            # ========================================================================
            # SOLUCIÓN DEFINITIVA: Descarga DIRECTA desde Chrome for Testing API
            # webdriver-manager está desactualizado y descarga driver v114
            # Esta función detecta Chrome y descarga el driver correcto para Chrome 144+
            # ========================================================================
            try:
                import shutil
                import sys
                import subprocess
                import zipfile
                import urllib.request
                import json
                
                # Detectar versión de Chrome instalado
                chrome_version = None
                try:
                    # Intentar leer desde registro de Windows
                    result = subprocess.run(
                        'reg query "HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon" /v version',
                        shell=True, capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        chrome_version = result.stdout.split()[-1].strip()
                        logging.info(f"🔍 Chrome detectado (USER): {chrome_version}")
                except:
                    try:
                        # Intentar desde HKEY_LOCAL_MACHINE
                        result = subprocess.run(
                            'reg query "HKEY_LOCAL_MACHINE\\SOFTWARE\\Google\\Chrome\\BLBeacon" /v version',
                            shell=True, capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            chrome_version = result.stdout.split()[-1].strip()
                            logging.info(f"🔍 Chrome detectado (MACHINE): {chrome_version}")
                    except:
                        pass
                
                if not chrome_version:
                    # Si no se detecta, asumir versión reciente
                    chrome_version = "144.0.7559.133"
                    logging.warning(f"⚠️ No se detectó Chrome, asumiendo versión: {chrome_version}")
                
                # Detectar arquitectura del sistema (32-bit vs 64-bit)
                import platform
                is_64bit = sys.maxsize > 2**32
                architecture = platform.machine().lower()
                
                # Determinar qué versión descargar
                if is_64bit and ('amd64' in architecture or 'x86_64' in architecture):
                    platform_suffix = "win64"
                    folder_name = "chromedriver-win64"
                    logging.info("🖥️ Sistema detectado: Windows 64-bit")
                else:
                    platform_suffix = "win32"
                    folder_name = "chromedriver-win32"
                    logging.info("🖥️ Sistema detectado: Windows 32-bit")
                
                # Directorio de descarga (incluye arquitectura en la ruta)
                driver_dir = os.path.expanduser(f"~/.chrome_drivers/{chrome_version}_{platform_suffix}")
                driver_exe = os.path.join(driver_dir, "chromedriver.exe")
                
                # Si ya existe el driver para esta versión, usarlo
                if os.path.exists(driver_exe):
                    logging.info(f"✅ ChromeDriver ya descargado: {driver_exe}")
                    chromedriver_path = driver_exe
                else:
                    with _DRIVER_DOWNLOAD_LOCK:
                        # Double-check inside the lock
                        if os.path.exists(driver_exe):
                            logging.info(f"✅ ChromeDriver ya descargado (por otro thread): {driver_exe}")
                            chromedriver_path = driver_exe
                        else:
                            # Descargar desde Chrome for Testing API
                            logging.warning(f"⬇️ Descargando ChromeDriver {chrome_version} ({platform_suffix}) desde Chrome for Testing...")
                            
                            # URL de descarga oficial de Chrome for Testing
                            download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{chrome_version}/{platform_suffix}/chromedriver-{platform_suffix}.zip"
                            zip_path = os.path.join(os.path.expanduser("~"), f"chromedriver_{threading.current_thread().ident}_{random.randint(1000, 9999)}.zip")
                            
                            try:
                                # Descargar
                                urllib.request.urlretrieve(download_url, zip_path)
                                logging.info(f"✅ ChromeDriver descargado: {zip_path}")
                                
                                # Crear directorio y extraer
                                os.makedirs(driver_dir, exist_ok=True)
                                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                    zip_ref.extractall(driver_dir)
                                
                                # Mover chromedriver.exe al directorio raíz
                                extracted_exe = os.path.join(driver_dir, folder_name, "chromedriver.exe")
                                if os.path.exists(extracted_exe):
                                    shutil.move(extracted_exe, driver_exe)
                                    # Limpiar carpeta temporal
                                    shutil.rmtree(os.path.join(driver_dir, folder_name), ignore_errors=True)
                               
                                # Eliminar ZIP
                                os.remove(zip_path)
                                
                                chromedriver_path = driver_exe
                                logging.info(f"✅ ChromeDriver instalado: {chromedriver_path}")
                        
                            except Exception as download_error:
                                logging.error(f"❌ Error descargando ChromeDriver: {download_error}")
                                # Fallback a webdriver-manager
                                logging.warning("⚠️ Intentando con webdriver-manager como fallback...")
                                from webdriver_manager.chrome import ChromeDriverManager
                                chromedriver_path = ChromeDriverManager().install()
                
            except Exception as cdm_error:
                error_str = str(cdm_error)
                # Si es un error de ZIP corrupto, limpiar caché y reintentar
                if "EOFError" in str(type(cdm_error).__name__) or "tuple index out of range" in error_str or "IndexError" in str(type(cdm_error).__name__):
                    logging.warning(f"⚠️ ChromeDriver corrupto detectado. Limpiando caché...")
                    try:
                        import shutil
                        cache_path = os.path.expanduser("~/.wdm")
                        if os.path.exists(cache_path):
                            shutil.rmtree(cache_path)
                            logging.info(f"✅ Caché limpiado: {cache_path}")
                    except Exception as cache_error:
                        logging.warning(f"No se pudo limpiar caché: {cache_error}")
                    
                    # Reintentar instalación después de limpiar caché
                    if attempt < max_retries - 1:
                        logging.info(f"Reintentando instalación de ChromeDriver (intento {attempt + 2}/{max_retries})...")
                        time.sleep(1)
                        continue
                    else:
                        raise
                else:
                    raise
            
            # Generar un puerto único basado en thread ID y número aleatorio
            thread_id = threading.current_thread().ident
            base_port = 9500 + (thread_id % 100)
            port = base_port + random.randint(0, 100)
            
            service = Service(
                executable_path=chromedriver_path,
                port=port
            )
            
            # Pequeño delay aleatorio para evitar race conditions
            if attempt > 0:
                delay = random.uniform(0.5, 2.0)
                logging.info(f"Intento {attempt + 1}/{max_retries} - Esperando {delay:.1f}s antes de reintentar...")
                time.sleep(delay)
            
            driver = webdriver.Chrome(
                service=service,
                options=options
            )

            # Timeout implícito corto para evitar esperas infinitas si el navegador falla
            driver.set_page_load_timeout(30)

            # PARCHE CRÍTICO PARA AZION / CLOUDFLARE: 
            # 1. Eliminar variables webdriver y devolver plugins falsos
            # 2. Eliminar variables window.cdc_ado..., window.cdc_... (firma de ChromeDriver)
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3]
                    });
                    
                    for (const key of Object.keys(window)) {
                        if (key.startsWith('cdc_') || key.startsWith('$cdc_')) {
                            delete window[key];
                        }
                    }
                """
            })

            logging.info(f"✅ Driver configurado exitosamente en puerto {port}")
            return driver
            
        except Exception as e:
            error_msg = str(e)
            if "WinError 32" in error_msg or "permission" in error_msg.lower():
                logging.warning(f"⚠️ Intento {attempt + 1}/{max_retries} falló por conflicto de archivos: {e}")
                if attempt < max_retries - 1:
                    continue  # Reintentar
                else:
                    logging.critical(f"❌ Error fatal al configurar driver después de {max_retries} intentos: {e}", exc_info=True)
                    raise
            else:
                # Otro tipo de error, no reintentar
                logging.critical(f"Error fatal al configurar driver: {e}", exc_info=True)
                raise


# =====================================================
# COTO (API via Constructor.io)
# =====================================================

COTO_API_KEY = "key_r6xzz4IAoTWcipni"
COTO_BASE_URL = "https://ac.cnstrc.com/search/"

def _normalizar_texto(texto):
    """Convierte a minúsculas y quita caracteres especiales para comparar mejor."""
    if not texto: return ""
    import re
    texto = texto.lower()
    texto = texto.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    texto = re.sub(r'[^a-z0-9\s]', ' ', texto)
    return " ".join(texto.split())

def _calcular_similitud_coto(busqueda, resultado):
    """Calcula similitud basada en intersección de palabras clave y sequence matcher."""
    from difflib import SequenceMatcher
    s1 = _normalizar_texto(busqueda)
    s2 = _normalizar_texto(resultado)
    
    seq_ratio = SequenceMatcher(None, s1, s2).ratio() * 100
    
    palabras_buscadas = set(s1.split())
    palabras_resultado = set(s2.split())
    palabras_buscadas = {p for p in palabras_buscadas if len(p) > 1}
    
    if not palabras_buscadas:
        return seq_ratio
        
    coincidencias = palabras_buscadas.intersection(palabras_resultado)
    match_palabras = (len(coincidencias) / len(palabras_buscadas)) * 100
    
    return (seq_ratio * 0.4) + (match_palabras * 0.6)

def buscar_precio_coto_api(descripcion, is_plu=False):
    """
    Busca el precio en la API de Coto. Si is_plu es True, asume que 'descripcion' es el PLU interno.
    """
    import requests
    import urllib.parse
    
    if not descripcion:
        return "No encontrado", "", ""
        
    query = str(descripcion).strip()
    if not is_plu and len(query) < 3:
        logging.warning("COTO API: Descripción demasiado corta para buscar")
        return "No encontrado", "", ""
        
    if not is_plu:
        logging.info(f"COTO API: Buscando descripcion '{query}'")
    else:
        logging.info(f"COTO API: Buscando PLU exacto '{query}'")
    
    params = {
        'key': COTO_API_KEY,
        'page': 1,
        'num_results_per_page': 1
    }
    
    try:
        r = requests.get(f"{COTO_BASE_URL}{urllib.parse.quote(query)}", params=params, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            resultados = data.get('response', {}).get('results', [])
            
            if not resultados:
                print(f"COTO API | {query[:30]}... | No encontrado")
                return "No encontrado", ""
                
            item = resultados[0]
            nombre_coto = item.get('value', '')
            
            # Chequear similitud solo si no es PLU exacto
            if not is_plu:
                similitud = _calcular_similitud_coto(query, nombre_coto)
                
                if similitud < 70:
                    logging.warning(f"COTO API: Similitud baja ({similitud:.1f}%) entre '{query}' y '{nombre_coto}'. Ignorando.")
                    print(f"COTO API | Ignorado por similitud baja ({similitud:.1f}%) -> {nombre_coto}")
                    return "No encontrado", "", ""
            else:
                similitud = 100.0  # Si lo encontró por PLU, es el correcto 100% aseguro.
            
            # Verificar disponibilidad en sucursales
            store_avail = item.get('data', {}).get('store_availability', [])
            if not store_avail:
                logging.warning(f"COTO API: Producto '{nombre_coto}' encontrado pero NO DISPONIBLE (store_availability vacío)")
                print(f"🔴 COTO API | {nombre_coto} | No disponible en ninguna sucursal")
                return "No disponible", "", ""
            
            # Obtener precio
            precio = item.get('data', {}).get('product_list_price')
            sku_plu = item.get('data', {}).get('sku_plu', 'N/A')
            
            if precio is None:
                logging.warning(f"COTO API: Producto encontrado pero sin precio ({nombre_coto})")
                return "No encontrado", "", ""
                
            # Formatear precio regular
            try:
                precio_float = float(precio)
                precio_fmt = str(int(precio_float)) if precio_float == int(precio_float) else f"{precio_float:.2f}".replace('.', ',')
            except:
                precio_fmt = str(precio)
            
            # Extraer oferta si existe
            oferta_txt = ''
            discounts = item.get('data', {}).get('discounts', [])
            if discounts and isinstance(discounts, list) and len(discounts) > 0:
                first_discount = discounts[0]
                d_price = first_discount.get('discountPrice', '')
                d_text = first_discount.get('discountText', '')
                t_text = first_discount.get('takingText', '')
                
                parts = []
                if t_text: parts.append(str(t_text))
                if d_text: parts.append(str(d_text))
                desc_texto = ' '.join(parts).strip()
                
                if d_price:
                    try:
                        dp_val = float(str(d_price).replace('$', '').replace(',', '.'))
                        oferta_fmt = str(int(dp_val)) if dp_val == int(dp_val) else f"{dp_val:.2f}".replace('.', ',')
                    except:
                        oferta_fmt = str(d_price).replace('$', '')
                        
                    if desc_texto:
                        oferta_txt = f"{oferta_fmt} ({desc_texto})"
                    else:
                        oferta_txt = oferta_fmt
                else:
                     oferta_txt = desc_texto

            logging.info(f"COTO API: {nombre_coto} | Reg: {precio_fmt} | Oferta: {oferta_txt} (Similitud: {similitud:.1f}%)")
            print(f"COTO API | Match ({similitud:.1f}%) | {nombre_coto} | Reg: {precio_fmt} | Oferta: {oferta_txt}")
            
            return precio_fmt, oferta_txt, sku_plu
        else:
            logging.error(f"COTO API: Error HTTP {r.status_code}")
            return "No encontrado", ""
    except Exception as e:
        logging.error(f"COTO API: Error buscando '{query}': {e}", exc_info=True)
        return "No encontrado", ""

# =====================================================
# NINI (API - tienda.nini.com.ar)
# =====================================================

# Cache global del catálogo de NINI para evitar descargarlo en cada búsqueda
_nini_catalogo_cache = None  # dict: ean -> producto
_nini_jwt_token = None
_nini_session = None

NINI_BASE_URL = "https://tienda.nini.com.ar"
NINI_USERNAME = "1109044"
NINI_PASSWORD = "Abastecedor2025."

def _get_nini_session():
    """Devuelve una sesión HTTP reutilizable para Nini."""
    global _nini_session
    if _nini_session is None:
        import requests
        _nini_session = requests.Session()
        _nini_session.headers.update({
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        })
    return _nini_session

def login_nini_api():
    """
    Realiza login en la API de Nini y devuelve el JWT token.
    Endpoint: POST /api/login
    Body: {"username": "...", "password": "..."}
    Respuesta: {"Id": ..., "Jwt": "eyJ...", "Client": {...}, ...}
    """
    global _nini_jwt_token
    import requests
    
    try:
        logging.info("NINI API: Intentando login...")
        session = _get_nini_session()
        
        resp = session.post(
            f"{NINI_BASE_URL}/api/login",
            json={"username": NINI_USERNAME, "password": NINI_PASSWORD},
            timeout=15
        )
        
        if resp.status_code == 200:
            data = resp.json()
            _nini_jwt_token = data.get("Jwt")
            if _nini_jwt_token:
                # Actualizar headers de la sesión con el token
                session.headers["Authorization"] = f"Bearer {_nini_jwt_token}"
                client_name = data.get("Client", {}).get("Address", "")
                logging.info(f"NINI API: Login OK - User: {data.get('Name', 'N/A')} - Cliente: {client_name}")
                print(f"NINI API: Login OK")
                return _nini_jwt_token
            else:
                logging.error("NINI API: Login exitoso pero no se encontro JWT en la respuesta")
                return None
        else:
            logging.error(f"NINI API: Login fallido - Status: {resp.status_code} - {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"NINI API: Error en login: {e}", exc_info=True)
        return None

def cargar_catalogo_nini():
    """
    Descarga el catálogo completo de productos de Nini y construye
    un diccionario de búsqueda por EAN (Barcode).
    
    El catálogo tiene ~8500 productos y pesa ~6MB.
    Se descarga UNA sola vez y se cachea en memoria.
    
    Returns:
        dict: {ean_string: producto_dict} o None si falla
    """
    global _nini_catalogo_cache
    import requests
    
    # Si ya está cacheado, devolver directamente
    if _nini_catalogo_cache is not None:
        logging.info(f"NINI API: Usando catalogo cacheado ({len(_nini_catalogo_cache)} EANs)")
        return _nini_catalogo_cache
    
    try:
        logging.info("NINI API: Descargando catalogo completo de productos...")
        session = _get_nini_session()
        
        start_time = time.time()
        resp = session.get(
            f"{NINI_BASE_URL}/api/productos",
            timeout=60
        )
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            productos = resp.json()
            if isinstance(productos, list):
                # Construir índice por EAN (Barcode)
                ean_index = {}
                for prod in productos:
                    barcodes = prod.get("Barcode", [])
                    if barcodes:
                        for barcode in barcodes:
                            if barcode and isinstance(barcode, str):
                                # Normalizar: quitar ceros a la izquierda si es necesario
                                ean_index[barcode] = prod
                                # También indexar sin ceros a la izquierda
                                stripped = barcode.lstrip('0')
                                if stripped != barcode:
                                    ean_index[stripped] = prod
                
                _nini_catalogo_cache = ean_index
                size_mb = len(resp.content) / 1024 / 1024
                logging.info(f"NINI API: Catalogo descargado OK - {len(productos)} productos, {len(ean_index)} EANs indexados, {size_mb:.1f}MB en {elapsed:.1f}s")
                print(f"NINI API: {len(productos)} productos cargados en {elapsed:.1f}s")
                return ean_index
            else:
                logging.error(f"NINI API: Respuesta inesperada (no es array): {type(productos)}")
                return None
        elif resp.status_code == 401:
            logging.warning("NINI API: Token expirado, reintentando login...")
            # Token expirado, intentar re-login
            token = login_nini_api()
            if token:
                return cargar_catalogo_nini()  # Reintentar con nuevo token
            return None
        else:
            logging.error(f"NINI API: Error descargando catalogo - Status: {resp.status_code}")
            return None
    except Exception as e:
        logging.error(f"NINI API: Error descargando catalogo: {e}", exc_info=True)
        return None

def buscar_precio_nini_api(ean):
    """
    Busca el precio de un producto en Nini por EAN usando el catálogo cacheado.
    
    Args:
        ean: Código EAN/barcode del producto
    
    Returns:
        tuple: (precio_regular, oferta) donde:
            - precio_regular: Precio de lista formateado como string (ej: "$4956.51")
            - oferta: Precio con descuento si difiere del de lista, o "" si no hay oferta
    """
    try:
        ean_str = str(ean).strip()
        logging.info(f"NINI API: Buscando EAN {ean_str}")
        
        # Cargar catálogo si no está en cache
        catalogo = cargar_catalogo_nini()
        if catalogo is None:
            logging.error("NINI API: No se pudo cargar el catalogo")
            return "No encontrado", ""
        
        # Buscar por EAN
        producto = catalogo.get(ean_str)
        
        # Si no se encuentra, intentar sin ceros a la izquierda
        if not producto:
            producto = catalogo.get(ean_str.lstrip('0'))
        
        # Si no se encuentra, intentar buscando con EAN-13 padding
        if not producto and len(ean_str) < 13:
            padded = ean_str.zfill(13)
            producto = catalogo.get(padded)
        
        if not producto:
            logging.warning(f"NINI API: EAN {ean_str} no encontrado en catalogo")
            print(f"NINI API | {ean_str} | No encontrado")
            return "No encontrado", ""
        
        # Extraer precios
        price_data = producto.get("Price", {})
        list_price = price_data.get("ListPrice")
        price = price_data.get("Price")
        desc = producto.get("Description", "")
        
        if list_price is None and price is None:
            logging.warning(f"NINI API: Producto {ean_str} sin precios")
            return "No encontrado", ""
        
        # Formatear precios
        def fmt_price(p):
            if p is None:
                return ""
            try:
                pf = float(p)
                return str(int(pf)) if pf == int(pf) else f"{pf:.2f}".replace('.', ',')
            except:
                return str(p)
        
        precio_regular = fmt_price(list_price)
        precio_oferta = ""
        
        # Si Price != ListPrice, hay oferta
        if price is not None and list_price is not None and abs(price - list_price) > 0.01:
            precio_oferta = fmt_price(price)
        
        # Si solo hay Price sin ListPrice
        if not precio_regular and price is not None:
            precio_regular = fmt_price(price)
        
        logging.info(f"NINI API: {ean_str} -> {desc} | Regular: {precio_regular} | Oferta: {precio_oferta}")
        print(f"NINI API | {ean_str} | {desc} | Regular: {precio_regular} | Oferta: {precio_oferta}")
        return precio_regular, precio_oferta
        
    except Exception as e:
        logging.error(f"NINI API: Error buscando {ean}: {e}", exc_info=True)
        return "No encontrado", ""

# =====================================================
# CARREFOUR
# =====================================================

# Session HTTP reutilizable para sitios VTEX (evita overhead de conexión en cada búsqueda)
_vtex_session = None

def _get_vtex_session():
    """Devuelve una sesión HTTP reutilizable con headers para VTEX."""
    global _vtex_session
    if _vtex_session is None:
        import requests
        _vtex_session = requests.Session()
        _vtex_session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Headers para parecer un navegador real
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        })
    return _vtex_session

def buscar_precio_carrefour(driver, ean):
    """
    Busca precio en Carrefour usando la API de VTEX IO (sin Selenium).
    El parámetro `driver` se mantiene por compatibilidad con el worker pero no se usa.
    """
    import requests

    BASE_URL = "https://www.carrefour.com.ar"
    TIMEOUT = 10  # segundos por request HTTP

    try:
        logging.info(f"Buscando en CARREFOUR (API) - EAN: {ean}")
        session = _get_vtex_session()

        search_url = f"{BASE_URL}/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean}"

        for attempt in range(3):
            try:
                time.sleep(0.3 * (attempt + 1))  # delay progresivo: 0.3s, 0.6s, 0.9s
                resp = session.get(search_url, timeout=TIMEOUT)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    logging.warning(f"CARREFOUR: Rate limit (429), esperando {wait}s antes de reintentar...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                search_data = resp.json()
                break
            except Exception as e:
                if attempt == 2:
                    logging.error(f"CARREFOUR: Error en búsqueda API para {ean}: {e}")
                    return "No encontrado", "", ""
                logging.warning(f"CARREFOUR: Intento {attempt+1} fallido: {e}. Reintentando...")
                time.sleep(3)
        else:
            logging.error(f"CARREFOUR: Agotados los reintentos para {ean}")
            return "No encontrado", "", ""

        if not search_data or len(search_data) == 0:
            logging.warning(f"CARREFOUR: Producto {ean} no encontrado en API")
            print(f"🔴 CARREFOUR | {ean} | No encontrado")
            return "No encontrado", "", ""

        # Extraer precios del primer item y seller
        try:
            item = search_data[0]['items'][0]
            
            # VERIFICACIÓN DE EAN: Asegurar que el producto devuelto coincida con el buscado
            # (A veces VTEX devuelve productos similares si no hay match exacto en algunos índices)
            if str(ean) not in item.get('ean', ''):
                logging.warning(f"CARREFOUR: EAN devuelto ({item.get('ean')}) no coincide con buscado ({ean})")
                return "No encontrado", "", ""
                
            commertial_offer = item['sellers'][0]['commertialOffer']
            
            # VERIFICACIÓN DE STOCK: Si no hay stock, el precio puede ser basura o estar desactualizado
            if commertial_offer.get('AvailableQuantity', 0) <= 0:
                logging.info(f"CARREFOUR: {ean} - Sin stock (AvailableQuantity: 0)")
                return "No encontrado", "", ""
            
            # Formatear el precio quitando .0 al final si es entero
            def fmt_price(p):
                if p is None: return ""
                try:
                    pf = float(p)
                    return str(int(pf)) if pf == int(pf) else f"{pf:.2f}".replace('.', ',')
                except:
                    return str(p)

            precio_regular = fmt_price(commertial_offer.get('PriceWithoutDiscount'))
            precio_oferta = fmt_price(commertial_offer.get('Price'))
            
            dinamica_txt = ""

            if not precio_regular and not precio_oferta:
                return "No encontrado", "", ""

            # Si son iguales, no hay oferta
            if precio_regular == precio_oferta:
                precio_oferta = ""

            # Si solo vino Price pero no ListPrice
            if not precio_regular and precio_oferta:
                precio_regular = precio_oferta
                precio_oferta = ""

            logging.info(f"✅ CARREFOUR: {ean} - Regular: {precio_regular} | Oferta: {precio_oferta}")
            print(f"🟢 CARREFOUR | {ean} | Regular: {precio_regular} | Oferta: {precio_oferta} | {dinamica_txt}")
            return precio_regular, precio_oferta, dinamica_txt

        except (KeyError, IndexError) as e:
            logging.warning(f"CARREFOUR: Estructura de json inesperada para {ean}: {e}")
            print(f"🔴 CARREFOUR | {ean} | Error procesando precio")
            return "No encontrado", "", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en CARREFOUR: {e}", exc_info=True)
        print(f"❌ CARREFOUR | {ean} | Error")
        return "No encontrado", "", ""
# =====================================================
# VEA
# =====================================================

def extract_price_value(text):
    """
    Extrae el valor del precio de un texto que puede contener labels.
    Ejemplo: "PRECIO SIN IMPUESTOS NACIONALES: $4.173,55" -> "$4.173,55"
    """
    import re
    if not text:
        return text
    
    # Buscar patrón de precio: $ seguido de números, puntos y comas
    price_pattern = r'\$[\d.,]+'
    matches = re.findall(price_pattern, text)
    
    if matches:
        # Retornar el primer precio encontrado
        return matches[0].replace('$', '').strip()
    
    return text

def buscar_precio_vea(driver, ean):
    """
    Busca precio en Vea usando la API de VTEX IO (sin Selenium).
    El parámetro `driver` se mantiene por compatibilidad con el worker pero no se usa.
    """
    import requests

    BASE_URL = "https://www.vea.com.ar"
    TIMEOUT = 10  # segundos por request HTTP

    try:
        logging.info(f"Buscando en VEA (API) - EAN: {ean}")
        session = _get_vtex_session()

        search_url = f"{BASE_URL}/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean}"

        try:
            resp = session.get(search_url, timeout=TIMEOUT)
            resp.raise_for_status()
            search_data = resp.json()
        except Exception as e:
            logging.error(f"VEA: Error en búsqueda API para {ean}: {e}")
            return "No encontrado", "", ""

        if not search_data or len(search_data) == 0:
            logging.warning(f"VEA: Producto {ean} no encontrado en API")
            print(f"🔴 VEA | {ean} | No encontrado")
            return "No encontrado", "", ""

        # Extraer precios del primer item y seller
        try:
            item = search_data[0]['items'][0]
            
            # VERIFICACIÓN DE EAN
            if str(ean) not in item.get('ean', ''):
                logging.warning(f"VEA: EAN devuelto no coincide con buscado ({ean})")
                return "No encontrado", "", ""

            commertial_offer = item['sellers'][0]['commertialOffer']
            
            # VERIFICACIÓN DE STOCK
            if commertial_offer.get('AvailableQuantity', 0) <= 0:
                logging.info(f"VEA: {ean} - Sin stock")
                return "No encontrado", "", ""
            
            # Formatear el precio quitando .0 al final si es entero
            def fmt_price(p):
                if p is None: return ""
                try:
                    pf = float(p)
                    return str(int(pf)) if pf == int(pf) else f"{pf:.2f}".replace('.', ',')
                except:
                    return str(p)

            precio_regular = fmt_price(commertial_offer.get('PriceWithoutDiscount'))
            precio_oferta = fmt_price(commertial_offer.get('Price'))
            
            # TODO: Add logic for 'dinamica' if available in VTEX payload for VEA
            dinamica_txt = ""

            if not precio_regular and not precio_oferta:
                return "No encontrado", "", ""

            # Si son iguales, no hay oferta
            if precio_regular == precio_oferta:
                precio_oferta = ""

            # Si solo vino Price pero no ListPrice
            if not precio_regular and precio_oferta:
                precio_regular = precio_oferta
                precio_oferta = ""

            logging.info(f"✅ VEA: {ean} - Regular: {precio_regular} | Oferta: {precio_oferta}")
            print(f"🟢 VEA | {ean} | Regular: {precio_regular} | Oferta: {precio_oferta} | {dinamica_txt}")
            return precio_regular, precio_oferta, dinamica_txt

        except (KeyError, IndexError) as e:
            logging.warning(f"VEA: Estructura de json inesperada para {ean}: {e}")
            print(f"🔴 VEA | {ean} | Error procesando precio")
            return "No encontrado", "", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en VEA: {e}", exc_info=True)
        print(f"❌ VEA | {ean} | Error")
        return "No encontrado", "", ""

# =====================================================
# DISCO
# =====================================================

def buscar_precio_disco(driver, ean):
    """
    Busca precio en Disco usando la API de VTEX IO (sin Selenium).
    El parámetro `driver` se mantiene por compatibilidad con el worker pero no se usa.
    """
    import requests

    BASE_URL = "https://www.disco.com.ar"
    TIMEOUT = 10  # segundos por request HTTP

    try:
        logging.info(f"Buscando en DISCO (API) - EAN: {ean}")
        session = _get_vtex_session()

        search_url = f"{BASE_URL}/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean}"

        try:
            resp = session.get(search_url, timeout=TIMEOUT)
            resp.raise_for_status()
            search_data = resp.json()
        except Exception as e:
            logging.error(f"DISCO: Error en búsqueda API para {ean}: {e}")
            return "No encontrado", "", ""

        if not search_data or len(search_data) == 0:
            logging.warning(f"DISCO: Producto {ean} no encontrado en API")
            print(f"🔴 DISCO | {ean} | No encontrado")
            return "No encontrado", "", ""

        # Extraer precios del primer item y seller
        try:
            item = search_data[0]['items'][0]
            
            # VERIFICACIÓN DE EAN
            if str(ean) not in item.get('ean', ''):
                logging.warning(f"DISCO: EAN devuelto no coincide con buscado ({ean})")
                return "No encontrado", "", ""

            commertial_offer = item['sellers'][0]['commertialOffer']
            
            # VERIFICACIÓN DE STOCK
            if commertial_offer.get('AvailableQuantity', 0) <= 0:
                logging.info(f"DISCO: {ean} - Sin stock")
                return "No encontrado", "", ""
            
            # Formatear el precio quitando .0 al final si es entero
            def fmt_price(p):
                if p is None: return ""
                try:
                    pf = float(p)
                    return str(int(pf)) if pf == int(pf) else f"{pf:.2f}".replace('.', ',')
                except:
                    return str(p)

            precio_regular = fmt_price(commertial_offer.get('PriceWithoutDiscount'))
            precio_oferta = fmt_price(commertial_offer.get('Price'))
            
            # TODO: Add logic for 'dinamica' if available in VTEX payload for DISCO
            dinamica_txt = ""

            if not precio_regular and not precio_oferta:
                return "No encontrado", "", ""

            # Si son iguales, no hay oferta
            if precio_regular == precio_oferta:
                precio_oferta = ""

            # Si solo vino Price pero no ListPrice
            if not precio_regular and precio_oferta:
                precio_regular = precio_oferta
                precio_oferta = ""

            logging.info(f"✅ DISCO: {ean} - Regular: {precio_regular} | Oferta: {precio_oferta}")
            print(f"🟢 DISCO | {ean} | Regular: {precio_regular} | Oferta: {precio_oferta} | {dinamica_txt}")
            return precio_regular, precio_oferta, dinamica_txt

        except (KeyError, IndexError) as e:
            logging.warning(f"DISCO: Estructura de json inesperada para {ean}: {e}")
            print(f"🔴 DISCO | {ean} | Error procesando precio")
            return "No encontrado", "", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en DISCO: {e}", exc_info=True)
        print(f"❌ DISCO | {ean} | Error")
        return "No encontrado", "", ""

# =====================================================
# MAXICONSUMO
# =====================================================

def configurar_driver_uc():
    """Configura y retorna una instancia de undetected_chromedriver aislada por thread"""
    import undetected_chromedriver as uc
    import os
    import shutil
    import tempfile
    import threading
    import time
    import subprocess
    import sys
    
    # ─── DETECTAR VERSIÓN DE CHROME INSTALADA ───
    chrome_version = None
    try:
        result = subprocess.run(
            'reg query "HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon" /v version',
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0:
            chrome_version = result.stdout.split()[-1].strip()
    except:
        pass
    if not chrome_version:
        try:
            result = subprocess.run(
                'reg query "HKEY_LOCAL_MACHINE\\SOFTWARE\\Google\\Chrome\\BLBeacon" /v version',
                shell=True, capture_output=True, text=True
            )
            if result.returncode == 0:
                chrome_version = result.stdout.split()[-1].strip()
        except:
            pass
    
    if chrome_version:
        logging.info(f"MAXICONSUMO UC: Chrome detectado v{chrome_version}")
    else:
        chrome_version = "146.0.7680.165"
        logging.warning(f"MAXICONSUMO UC: No se detectó Chrome, asumiendo v{chrome_version}")
    
    # ─── BUSCAR CHROMEDRIVER COMPATIBLE CON LA VERSIÓN DETECTADA ───
    is_64bit = sys.maxsize > 2**32
    import platform
    architecture = platform.machine().lower()
    platform_suffix = "win64" if (is_64bit and ('amd64' in architecture or 'x86_64' in architecture)) else "win32"
    
    chrome_driver_path = os.path.expanduser("~/.chrome_drivers")
    driver_dir = os.path.join(chrome_driver_path, f"{chrome_version}_{platform_suffix}")
    original_exe = os.path.join(driver_dir, "chromedriver.exe")
    
    if not os.path.exists(original_exe):
        # El driver para esta versión no existe. Descargarlo usando configurar_driver()
        logging.warning(f"MAXICONSUMO UC: ChromeDriver v{chrome_version} no encontrado. Descargando via configurar_driver()...")
        temp_driver = configurar_driver(optimized=True)
        temp_driver.quit()
        logging.info("MAXICONSUMO UC: Driver descargado exitosamente")
        
        # Verificar nuevamente si ahora existe
        if not os.path.exists(original_exe):
            # Buscar cualquier chromedriver que contenga la versión mayor
            major_ver = chrome_version.split('.')[0]
            for root, dirs, files in os.walk(chrome_driver_path):
                if "chromedriver.exe" in files and major_ver in root:
                    original_exe = os.path.join(root, "chromedriver.exe")
                    logging.info(f"MAXICONSUMO UC: Usando driver encontrado en {root}")
                    break
        
        if not os.path.exists(original_exe):
            logging.error("MAXICONSUMO: ChromeDriver base no encontrado para UC.")
            raise FileNotFoundError("ChromeDriver base no encontrado")
        
    thread_id = threading.current_thread().ident
    temp_dir = os.path.join(tempfile.gettempdir(), "uc_drivers")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Ruta única para este thread
    temp_driver_path = os.path.join(temp_dir, f"chromedriver_uc_{thread_id}_{int(time.time())}.exe")
    shutil.copy2(original_exe, temp_driver_path)

    # Configurar opciones de UC
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Iniciar UC con el ejecutable thread-safe
    uc_driver = uc.Chrome(
        options=options, 
        driver_executable_path=temp_driver_path,
        use_subprocess=True # Crítico para estabilidad de proceso
    )
    # Timeout optimizado
    uc_driver.set_page_load_timeout(20)
    
    # Agregar atributo parar poder limpiar el temp `.exe` al cerrar
    uc_driver.temp_exe_path = temp_driver_path
    
    return uc_driver


def _formatear_precio_maxi(valor_float):
    """Convierte un float de precio a texto plano (sin miles)"""
    if valor_float is None:
        return ""
    try:
        if valor_float == int(valor_float):
            return str(int(valor_float))
        return f"{valor_float:.2f}".replace(".", ",")
    except Exception:
        return str(valor_float)

# Sesión HTTP reutilizable para Maxiconsumo (búsqueda HTML)
_maxi_session = None

def _get_maxi_session():
    """Devuelve una sesión HTTP reutilizable para Maxiconsumo (HTML scraping)."""
    global _maxi_session
    if _maxi_session is None:
        import requests
        _maxi_session = requests.Session()
        _maxi_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9",
            "Store": "sucursal_moreno",
        })
    return _maxi_session

def buscar_precio_maxiconsumo(driver, ean):
    """
    Busca precio en Maxiconsumo usando la página de búsqueda del catálogo (HTML parsing).
    El parámetro `driver` se mantiene por compatibilidad con el worker pero no se usa.

    Usa el mismo motor de búsqueda que el sitio web, que indexa por EAN correctamente.
    Extrae el precio del bloque JSON x-magento-init incrustado en la página de resultados.
    """
    import re as _re
    import json as _json

    BASE_URL = "https://maxiconsumo.com/sucursal_moreno"
    TIMEOUT = 15

    try:
        logging.info(f"Buscando en MAXICONSUMO (HTML) - EAN: {ean}")
        session = _get_maxi_session()

        search_url = f"{BASE_URL}/catalogsearch/result/?q={ean}"

        for attempt in range(3):
            try:
                time.sleep(0.3 * (attempt + 1))  # delay progresivo
                resp = session.get(search_url, timeout=TIMEOUT)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    logging.warning(f"MAXICONSUMO: Rate limit (429), esperando {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                html = resp.text
                break
            except Exception as e:
                if attempt == 2:
                    logging.error(f"MAXICONSUMO: Error en búsqueda HTML para {ean}: {e}")
                    return "No encontrado", ""
                logging.warning(f"MAXICONSUMO: Intento {attempt+1} fallido: {e}. Reintentando...")
                time.sleep(2)
        else:
            return "No encontrado", ""

        # Extraer bloques x-magento-init que contienen los datos de precios
        script_blocks = _re.findall(
            r'<script[^>]*type=["\']text/x-magento-init["\'][^>]*>(.*?)</script>',
            html, _re.DOTALL
        )

        old_price = None
        final_price = None

        for block_text in script_blocks:
            try:
                block = _json.loads(block_text.strip())
                for selector, components in block.items():
                    # Solo bloques de precio de productos (no minicart ni otros)
                    if 'priceBox' in components and 'product-id-' in selector:
                        price_config = components['priceBox'].get('priceConfig', {})
                        prices_data = price_config.get('prices', {})
                        old_price = prices_data.get('oldPrice', {}).get('amount')
                        final_price = prices_data.get('finalPrice', {}).get('amount')
                        if old_price is not None:
                            break  # Tomar el primer producto encontrado
            except Exception:
                continue
            if old_price is not None:
                break

        if old_price is None:
            logging.warning(f"MAXICONSUMO: EAN {ean} no encontrado en página de búsqueda")
            print(f"\U0001f534 MAXICONSUMO | {ean} | No encontrado")
            return "No encontrado", ""

        precio_regular = _formatear_precio_maxi(old_price)
        precio_oferta = ""

        # Si el precio final difiere del regular, hay oferta
        if final_price is not None and abs(final_price - old_price) > 0.01:
            precio_oferta = _formatear_precio_maxi(final_price)

        logging.info(f"\u2705 MAXICONSUMO: {ean} - Regular: {precio_regular} | Oferta: {precio_oferta}")
        print(f"\U0001f7e2 MAXICONSUMO | {ean} | Regular: {precio_regular} | Oferta: {precio_oferta}")
        return precio_regular, precio_oferta

    except Exception as e:
        logging.error(f"MAXICONSUMO (error buscando {ean}): {e}")
        return "No encontrado", ""

# =====================================================
# MENÚ INTERACTIVO PARA SELECCIÓN DE PÁGINAS
# =====================================================

def menu_seleccion_paginas():
    print("\n" + "="*50)
    print("📋 SELECCIÓN DE PÁGINAS PARA BUSCAR")
    print("="*50)
    print("\n1. Buscar en TODAS las páginas (NINI, CARREFOUR, VEA, DISCO)")
    print("2. Seleccionar páginas individuales")
    print("3. Salir")
    
    while True:
        try:
            opcion = input("\n👉 Selecciona una opción (1-3): ").strip()
            
            if opcion == "1":
                print("\n✅ Seleccionado: TODAS las páginas")
                return {
                    "nini": True,
                    "carrefour": True,
                    "vea": True,
                    "disco": True,
                    "maxiconsumo": True,
                    "coto": True
                }
            
            elif opcion == "2":
                seleccion = {
                    "nini": False,
                    "carrefour": False,
                    "vea": False,
                    "disco": False,
                    "maxiconsumo": False,
                    "coto": False
                }
                
                print("\n📝 Selecciona las páginas que deseas buscar (s/n):")
                
                respuesta = input("  🔹 NINI (s/n): ").strip().lower()
                seleccion["nini"] = respuesta == "s"
                
                respuesta = input("  🔹 COTO (s/n): ").strip().lower()
                seleccion["coto"] = respuesta == "s"
                
                respuesta = input("  🔹 CARREFOUR (s/n): ").strip().lower()
                seleccion["carrefour"] = respuesta == "s"
                
                respuesta = input("  🔹 VEA (s/n): ").strip().lower()
                seleccion["vea"] = respuesta == "s"
                
                respuesta = input("  🔹 DISCO (s/n): ").strip().lower()
                seleccion["disco"] = respuesta == "s"

                respuesta = input("  🔹 MAXICONSUMO (s/n): ").strip().lower()
                seleccion["maxiconsumo"] = respuesta == "s"
                
                # Verificar que al menos una opción fue seleccionada
                if not any(seleccion.values()):
                    print("\n⚠️  Debes seleccionar al menos una página. Intenta de nuevo.")
                    continue
                
                print("\n✅ Selección confirmada:")
                for pagina, activa in seleccion.items():
                    if activa:
                        print(f"   ✓ {pagina.upper()}")
                
                return seleccion
            
            elif opcion == "3":
                print("\n👋 Saliendo del programa...")
                exit(0)
            
            else:
                print("❌ Opción no válida. Por favor selecciona 1, 2 o 3.")
        
        except KeyboardInterrupt:
            print("\n\n👋 Programa cancelado por el usuario.")
            exit(0)

# =====================================================
# UTILIDAD PARA GUARDAR EXCEL DE FORMA SEGURA
# =====================================================

def _guardar_excel_seguro(df, filepath, max_reintentos=5, espera=3):
    """
    Intenta guardar el DataFrame como Excel. Si el archivo está abierto
    en otra aplicación (PermissionError), reintenta varias veces y
    finalmente guarda con un nombre alternativo.
    """
    for intento in range(1, max_reintentos + 1):
        try:
            df.to_excel(filepath, index=False)
            return filepath
        except PermissionError:
            if intento < max_reintentos:
                logging.warning(
                    f"⚠️ No se pudo guardar '{os.path.basename(filepath)}' "
                    f"(¿está abierto en Excel?). Reintento {intento}/{max_reintentos} "
                    f"en {espera}s..."
                )
                print(
                    f"⚠️ El archivo '{os.path.basename(filepath)}' está abierto. "
                    f"Cerralo e intentaré de nuevo en {espera} segundos..."
                )
                time.sleep(espera)
            else:
                # Último intento fallido: guardar con nombre alternativo
                from datetime import datetime
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                base, ext = os.path.splitext(filepath)
                alt_path = f"{base}_{ts}{ext}"
                logging.warning(
                    f"❌ No se pudo guardar en '{os.path.basename(filepath)}' "
                    f"después de {max_reintentos} intentos. "
                    f"Guardando como: {os.path.basename(alt_path)}"
                )
                print(
                    f"❌ No se pudo acceder al archivo original. "
                    f"Resultados guardados como: {os.path.basename(alt_path)}"
                )
                df.to_excel(alt_path, index=False)
                return alt_path

# =====================================================
# EJECUCIÓN PRINCIPAL
# =====================================================

def worker_site(site_name, df, results_dict, selection, log_queue=None, pause_event=None, product_queue=None):
    """
    Worker que procesa un sitio completo en un thread separado.
    
    Args:
        site_name: Nombre del sitio ('nini', 'carrefour', 'vea', 'disco')
        df: DataFrame con productos a buscar
        results_dict: Diccionario compartido para guardar resultados
        selection: Dict con configuración de búsqueda
        log_queue: Cola para logs (opcional)
        pause_event: Evento para pausar/reanudar (opcional)
        product_queue: Cola para actualizaciones de productos en tiempo real (opcional)
    """
    driver = None
    try:
        logging.info(f"[{site_name.upper()}] 🚀 Iniciando worker thread...")
        
        # Intentar configurar driver con retry
        max_driver_retries = 2
        for attempt in range(max_driver_retries):
            try:
                if site_name in ("maxiconsumo", "nini", "coto", "vea", "disco", "carrefour"):
                    # Estos sitios usan API directa, no necesitan driver Selenium
                    driver = None
                    logging.info(f"[{site_name.upper()}] Modo API (sin driver) inicializado")
                    break
                else:
                    driver = configurar_driver(optimized=True)
                logging.info(f"[{site_name.upper()}] ✅ Driver inicializado correctamente")
                break
            except Exception as driver_error:
                if attempt < max_driver_retries - 1:
                    logging.warning(f"[{site_name.upper()}] ⚠️ Error al iniciar driver (intento {attempt + 1}/{max_driver_retries}): {driver_error}")
                    import time
                    time.sleep(2)
                else:
                    logging.error(f"[{site_name.upper()}] ❌ Error fatal al iniciar driver después de {max_driver_retries} intentos: {driver_error}")
                    raise
        
        
        # Función para chequear pausa
        def check_pause():
            if pause_event and not pause_event.is_set():
                logging.info(f"[{site_name.upper()}] ⏸️ Pausado")
                pause_event.wait()
                logging.info(f"[{site_name.upper()}] ▶️ Reanudado")
        
        # Función helper para emitir actualizaciones de producto
        def emit_product_update(idx, sku, codigo, descripcion, precio, oferta="", dinamica=""):
            if product_queue:
                try:
                    product_queue.put({
                        'type': 'update',
                        'index': int(idx),
                        'sku': str(sku),
                        'codigo': str(codigo),
                        'descripcion': str(descripcion),
                        'site': site_name,
                        'precio': str(precio),
                        'oferta': str(oferta),
                        'dinamica': str(dinamica)
                    })
                except:
                    pass
        
        site_results = []
        
        # Procesar según sitio
        if site_name == "nini":
            # NINI usa API directa (sin Selenium)
            token = login_nini_api()
            if token:
                # Pre-cargar catálogo completo (se cachea para todas las búsquedas)
                catalogo = cargar_catalogo_nini()
                if catalogo:
                    for idx, row in df.iterrows():
                        if STOP_EVENT.is_set():
                            logging.info(f"[{site_name.upper()}] Detencion solicitada. Saliendo...")
                            break
                        check_pause()
                        # Verificar si ya tiene resultado válido
                        if str(row.get("Precio NINI", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                            continue
                        
                        res = buscar_precio_nini_api(row["ean"])
                        if isinstance(res, tuple):
                            precio, oferta = res[0], res[1]
                            site_results.append({
                                'idx': idx,
                                'SKU': row['ean'],
                                'Precio': precio,
                                'Oferta': oferta
                            })
                            emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta)
                        else:
                            site_results.append({
                                'idx': idx,
                                'SKU': row['ean'],
                                'Precio': res,
                                'Oferta': ''
                            })
                            emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), res)
                else:
                    logging.error(f"[{site_name.upper()}] No se pudo cargar el catalogo de productos")
            else:
                logging.error(f"[{site_name.upper()}] Fallo en login API")
        
        elif site_name == "coto":
            # COTO usa API directa (Constructor.io) buscando por PLU exacto.
            # Si el producto no tiene PLU asignado, se saltea.
            for idx, row in df.iterrows():
                if STOP_EVENT.is_set():
                    logging.info(f"[{site_name.upper()}] Detencion solicitada. Saliendo...")
                    break
                check_pause()
                if str(row.get("Precio COTO", "Pendiente")) not in ["Pendiente", "No encontrado", "Error", "Sin PLU", "No disponible"]:
                    continue
                
                # Obtener PLU de la planilla
                codigo_coto = str(row.get("plu", "")).strip()
                
                # Si no tiene PLU, salteamos sin hacer ninguna búsqueda
                if not codigo_coto or codigo_coto in ("nan", "None", ""):
                    logging.info(f"[COTO] Producto sin PLU, salteando: {str(row.get('descripcion', ''))[:40]}")
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': 'Sin PLU',
                        'Oferta': ''
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), 'Sin PLU')
                    continue
                
                # Buscar por PLU exacto
                try:
                    parsed_plu = str(int(float(codigo_coto)))  # limpiar el .0 de pandas
                except ValueError:
                    parsed_plu = codigo_coto
                
                desc = row.get("descripcion", "")
                res = buscar_precio_coto_api(parsed_plu, is_plu=True)
                    
                if isinstance(res, tuple) and len(res) == 3:
                    precio, oferta, plu_match = res
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': precio,
                        'Oferta': oferta,
                        'PLU': plu_match
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), desc, precio, oferta)
                elif isinstance(res, tuple):
                    precio, oferta = res[0], res[1]
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': precio,
                        'Oferta': oferta
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), desc, precio, oferta)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': res,
                        'Oferta': ''
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), desc, res)

        elif site_name == "carrefour":
            for idx, row in df.iterrows():
                if STOP_EVENT.is_set():
                    logging.info(f"[{site_name.upper()}] 🛑 Detención solicitada. Saliendo...")
                    break
                check_pause()
                if str(row.get("Precio CARREFOUR", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                res = buscar_precio_carrefour(driver, row["ean"])
                if isinstance(res, tuple):
                    precio, oferta, dinamica = res[0], res[1], res[2] if len(res) > 2 else ''
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': precio,
                        'Oferta': oferta,
                        'Dinamica': dinamica
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta, dinamica)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': res,
                        'Oferta': '',
                        'Dinamica': ''
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), res)
        
        elif site_name == "vea":
            for idx, row in df.iterrows():
                if STOP_EVENT.is_set():
                    logging.info(f"[{site_name.upper()}] 🛑 Detención solicitada. Saliendo...")
                    break
                check_pause()
                if str(row.get("Precio VEA", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                res = buscar_precio_vea(driver, row["ean"])
                if isinstance(res, tuple):
                    precio, oferta, dinamica = res[0], res[1], res[2] if len(res) > 2 else ''
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': precio,
                        'Oferta': oferta,
                        'Dinamica': dinamica
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta, dinamica)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio': res,
                        'Oferta': '',
                        'Dinamica': ''
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), res)
        
        elif site_name == "disco":
            for idx, row in df.iterrows():
                if STOP_EVENT.is_set():
                    logging.info(f"[{site_name.upper()}] 🛑 Detención solicitada. Saliendo...")
                    break
                check_pause()
                if str(row.get("Precio DISCO", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                try:
                    res = buscar_precio_disco(driver, row["ean"])
                    if isinstance(res, tuple):
                        precio, oferta, dinamica = res[0], res[1], res[2] if len(res) > 2 else ''
                        site_results.append({
                            'idx': idx,
                            'SKU': row['ean'],
                            'Precio': precio,
                            'Oferta': oferta,
                            'Dinamica': dinamica
                        })
                        emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta, dinamica)
                    else:
                        site_results.append({
                            'idx': idx,
                            'SKU': row['ean'],
                            'Precio': res,
                            'Oferta': '',
                            'Dinamica': ''
                        })
                        emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), res)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "tab crashed" in error_msg or "session deleted" in error_msg:
                        logging.error(f"[{site_name.upper()}] ⚠️ Navegador crasheó. Reiniciando...")
                        try:
                            driver.quit()
                        except:
                            pass
                        driver = configurar_driver(optimized=True)
                        site_results.append({
                            'idx': idx,
                            'SKU': row['ean'],
                            'Precio': 'Error',
                            'Oferta': '',
                            'Dinamica': ''
                        })
                    else:
                        logging.error(f"[{site_name.upper()}] Error procesando {row['ean']}: {e}")
                        site_results.append({
                            'idx': idx,
                            'SKU': row['ean'],
                            'Precio': 'No encontrado',
                            'Oferta': '',
                            'Dinamica': ''
                        })

        elif site_name == "maxiconsumo":
            for idx, row in df.iterrows():
                if STOP_EVENT.is_set():
                    logging.info(f"[{site_name.upper()}] 🛑 Detención solicitada. Saliendo...")
                    break
                check_pause()
                if str(row.get("Precio Bulto MAXICONSUMO", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue

                res = buscar_precio_maxiconsumo(driver, row["ean"])
                if isinstance(res, tuple):
                    precio_bulto, precio_unit = res[0], res[1]
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio Bulto': precio_bulto,
                        'Precio Unitario': precio_unit
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), precio_unit)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['ean'],
                        'Precio Bulto': res,
                        'Precio Unitario': ''
                    })
                    emit_product_update(idx, row['ean'], row.get('codigo', ''), row.get('descripcion', ''), res)
        
        results_dict[site_name] = site_results
        logging.info(f"[{site_name.upper()}] ✅ Worker finalizado - {len(site_results)} productos procesados")
        
    except Exception as e:
        logging.error(f"[{site_name.upper()}] ❌ Error crítico en worker: {e}", exc_info=True)
        results_dict[site_name] = []
    finally:
        if driver:
            try:
                driver.quit()
                logging.info(f"[{site_name.upper()}] Navegador cerrado")
            except:
                pass
            
            # Limpieza especial de temp exe para UC driver de Maxiconsumo
            if site_name == "maxiconsumo" and hasattr(driver, "temp_exe_path"):
                temp_driver_path = driver.temp_exe_path
                import os
                import time as _time
                if temp_driver_path and os.path.exists(temp_driver_path):
                    for _ in range(5):
                        try:
                            os.remove(temp_driver_path)
                            break
                        except Exception:
                            _time.sleep(1)

def run_scraper(selection, log_queue=None, input_df=None, ignore_cache=False, pause_event=None, product_queue=None):
    """
    Función principal para ejecutar el scraper.
    Puede ser llamada desde la CLI o desde la web app.
    
    Args:
        selection (dict): Diccionario con las páginas a buscar
                          {'nini': bool, 'carrefour': bool, ...}
        log_queue (Queue, optional): Cola para enviar logs a la web app.
        input_df (DataFrame, optional): DataFrame con los datos de entrada. 
                                        Si se provee, se usa en lugar de INPUT_FILE.
        ignore_cache (bool): Si es True, no lée el archivo de salida existente.
        pause_event (threading.Event, optional): Evento para pausar/reanudar.
        product_queue (Queue, optional): Cola para enviar actualizaciones de productos en tiempo real.
    """
    
    def check_pause():
        if pause_event and not pause_event.is_set():
            logging.info("⏸️ Scraper pausado. Esperando reanudación...")
            pause_event.wait()
            logging.info("▶️ Scraper reanudado.")
    
    # El logging se configura ahora centralizadamente en app.py para la web app
    # o via basicConfig en la CLI. No agregamos handlers aqui para evitar duplicados.
    
    driver = None
    try:
        logging.info("Inicio del script de scraping")
        logging.info(f"Páginas seleccionadas: {selection}")
        if ignore_cache:
            logging.info("⚠️ MODO FORZAR RE-ESCANEO ACTIVADO: Se ignorarán resultados anteriores.")

        buscar_nini = selection.get("nini", False)
        buscar_carrefour = selection.get("carrefour", False)
        buscar_vea = selection.get("vea", False)
        buscar_disco = selection.get("disco", False)
        buscar_maxiconsumo = selection.get("maxiconsumo", False)

        df = None
        
        if input_df is not None:
             logging.info("Usando datos del archivo CSV subido")
             df = input_df
        else:
            logging.info(f"Leyendo archivo de entrada: {INPUT_FILE}")
            # Verificar si existe el archivo de entrada antes de leer
            if not os.path.exists(INPUT_FILE):
                 msg = f"No se encuentra el archivo de entrada: {INPUT_FILE}"
                 logging.critical(msg)
                 if log_queue: logging.critical("STOP_SIGNAL")
                 return
            df = pd.read_excel(INPUT_FILE, dtype={"ean": str, "plu": str, "codigo": str})

        # Loguear primeros 5 SKUs para que el usuario verifique
        if df is not None:
             first_eans = df['ean'].head(5).tolist()
             logging.info(f"Cargados {len(df)} productos. Primeros EANs: {first_eans}")

        # Todas las columnas de precio que manejamos
        PRICE_COLS = [
            "Precio NINI", "Oferta NINI",
            "Precio CARREFOUR", "Oferta CARREFOUR", "Dinamica CARREFOUR",
            "Precio VEA", "Oferta VEA", "Dinamica VEA",
            "Precio DISCO", "Oferta DISCO", "Dinamica DISCO",
            "Precio Bulto MAXICONSUMO", "Precio Unitario MAXICONSUMO",
            "Precio COTO", "Oferta COTO"
        ]

        if not ignore_cache and os.path.exists(OUTPUT_FILE):
            logging.info(f"Leyendo archivo de salida existente: {OUTPUT_FILE}")
            df_old = pd.read_excel(OUTPUT_FILE, dtype={"ean": str, "plu": str, "codigo": str})
            df = df.merge(df_old, on="ean", how="left", suffixes=("", "_old"))

            for col in PRICE_COLS:
                if f"{col}_old" in df.columns:
                    # Traer valor viejo sólo si no es NaN ni cadena vacía
                    old_vals = df[f"{col}_old"].fillna("Pendiente").astype(str).str.strip()
                    old_vals = old_vals.replace("", "Pendiente")
                    df[col] = old_vals

            df = df[df.columns.drop(list(df.filter(regex="_old")))]
        else:
            if ignore_cache and os.path.exists(OUTPUT_FILE):
                logging.info("Ignorando archivo de salida existente (Force Rescan).")
            else:
                logging.info("Creando nuevo archivo de resultados")

        # Inicializar columnas faltantes y reemplazar NaN/vacío por 'Pendiente'
        for col in PRICE_COLS:
            if col not in df.columns:
                df[col] = "Pendiente"
            df[col] = df[col].fillna("Pendiente").astype(str).str.strip().replace("", "Pendiente")

        # Guardar resultados finales
        _guardar_excel_seguro(df, OUTPUT_FILE)

        # ===================================================================
        # IMPLEMENTACIÓN PARALELA - FASE 1
        # ===================================================================
        
        import threading
        
        buscar_nini = selection.get("nini", False)
        buscar_carrefour = selection.get("carrefour", False)
        buscar_vea = selection.get("vea", False)
        buscar_disco = selection.get("disco", False)
        buscar_maxiconsumo = selection.get("maxiconsumo", False)
        buscar_coto = selection.get("coto", False)

        # Preparar estructura de resultados compartida (thread-safe para escritura por keys únicas)
        results_dict = {}
        threads = []
        
        # Crear lista de sitios a procesar
        sites_to_scrape = []
        if buscar_nini:
            sites_to_scrape.append("nini")
        if buscar_carrefour:
            sites_to_scrape.append("carrefour")
        if buscar_vea:
            sites_to_scrape.append("vea")
        if buscar_disco:
            sites_to_scrape.append("disco")
        if buscar_maxiconsumo:
            sites_to_scrape.append("maxiconsumo")
        if buscar_coto:
            sites_to_scrape.append("coto")
        
        if not sites_to_scrape:
            logging.warning("⚠️ No se seleccionó ningún sitio para scraping")
            logging.info("STOP_SIGNAL")
            return
        
        logging.info(f"🚀 Iniciando scraping PARALELO en {len(sites_to_scrape)} sitios: {sites_to_scrape}")
        logging.info("=" * 60)
        
        # Enviar lista inicial de productos al frontend
        if product_queue:
            for idx, row in df.iterrows():
                try:
                    product_queue.put({
                        'type': 'init',
                        'index': int(idx),
                        'sku': str(row['ean']),
                        'codigo': str(row.get('codigo', '')),
                        'descripcion': str(row.get('descripcion', ''))
                    })
                except:
                    pass
        
        # Lanzar threads (uno por sitio)
        for site_name in sites_to_scrape:
            thread = threading.Thread(
                target=worker_site,
                args=(site_name, df, results_dict, selection, log_queue, pause_event, product_queue),
                name=f"Worker-{site_name.upper()}"
            )
            threads.append(thread)
            thread.start()
            logging.info(f"✅ [{site_name.upper()}] Thread lanzado")
        
        # Esperar a que todos terminen
        logging.info("⏳ Esperando finalización de todos los workers...")
        for thread in threads:
            thread.join()
            logging.info(f"✅ [{thread.name}] Thread completado")
        
        logging.info("=" * 60)
        logging.info("📊 Consolidando resultados de todos los sitios...")
        
        # Consolidar resultados en el DataFrame
        total_actualizados = 0
        for site_name, site_results in results_dict.items():
            logging.info(f"[{site_name.upper()}] Consolidando {len(site_results)} resultados...")
            
            for result in site_results:
                idx = result['idx']
                
                if site_name == "nini":
                    df.at[idx, "Precio NINI"] = result['Precio']
                    df.at[idx, "Oferta NINI"] = result['Oferta']
                    total_actualizados += 1
                    
                elif site_name == "carrefour":
                    df.at[idx, "Precio CARREFOUR"] = result['Precio']
                    df.at[idx, "Oferta CARREFOUR"] = result['Oferta']
                    df.at[idx, "Dinamica CARREFOUR"] = result.get('Dinamica', '')
                    total_actualizados += 1
                    
                elif site_name == "vea":
                    df.at[idx, "Precio VEA"] = result['Precio']
                    df.at[idx, "Oferta VEA"] = result['Oferta']
                    df.at[idx, "Dinamica VEA"] = result.get('Dinamica', '')
                    total_actualizados += 1
                    
                elif site_name == "disco":
                    df.at[idx, "Precio DISCO"] = result['Precio']
                    df.at[idx, "Oferta DISCO"] = result['Oferta']
                    df.at[idx, "Dinamica DISCO"] = result.get('Dinamica', '')
                    total_actualizados += 1

                elif site_name == "maxiconsumo":
                    df.at[idx, "Precio Bulto MAXICONSUMO"] = result.get('Precio Bulto', result.get('Precio', ''))
                    df.at[idx, "Precio Unitario MAXICONSUMO"] = result.get('Precio Unitario', result.get('Oferta', ''))
                    total_actualizados += 1
                elif site_name == "coto":
                    df.at[idx, "Precio COTO"] = result['Precio']
                    df.at[idx, "Oferta COTO"] = result['Oferta']
                    if 'PLU' in result and result['PLU']:
                        df.at[idx, "plu"] = result['PLU']
                    total_actualizados += 1
        
        # Guardar resultados finales consolidados
        saved_path = _guardar_excel_seguro(df, OUTPUT_FILE)
        logging.info(f"💾 Resultados guardados en '{os.path.basename(saved_path)}': {total_actualizados} precios actualizados")
        logging.info("=" * 60)

        logging.info("Proceso finalizado correctamente")
        print("✅ Proceso finalizado correctamente")

    except Exception as e:
        logging.critical(f"Error inesperado en la ejecución principal: {e}", exc_info=True)
        print(f"❌ Error fatal: {e}")
    finally:
        # Los drivers ahora son manejados por cada worker thread
        # Señal de fin para el stream
        if log_queue:
            logging.info("STOP_SIGNAL")
        if product_queue:
            product_queue.put("STOP_SIGNAL")


if __name__ == "__main__":
    import logging.handlers # Import inside main to avoid circular deps if needed elsewhere
    try:
        # Mostrar menú y obtener selección del usuario
        paginas_seleccionadas = menu_seleccion_paginas()
        run_scraper(paginas_seleccionadas)

    except KeyboardInterrupt:
        print("\n👋 Programa cancelado por el usuario.")
    except Exception as e:
        print(f"❌ Error fatal: {e}")
