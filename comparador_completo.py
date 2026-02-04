from sre_constants import LITERAL
import time
import os
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
import logging.handlers

# =====================================================
# CONFIGURACIÓN LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper_debug.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

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
    
    # Opciones adicionales para Railway/Docker
    if is_railway:
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--remote-debugging-port=9222")
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
            chromedriver_path = ChromeDriverManager().install()
            
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

            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
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
# NINI
# =====================================================

def login_nini(driver):
    try:
        logging.info("Intentando login en NINI...")
        driver.get("http://ecommerce.nini.com.ar:8081/ventas.online/?nini.controllers.login")

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.ID, "userName"))
        ).send_keys("29090")

        driver.find_element(By.ID, "password").send_keys("123456789", Keys.RETURN)

        WebDriverWait(driver, 10).until_not(
            EC.visibility_of_element_located((By.ID, "userName"))
        )

        logging.info("✅ Login NINI OK")
        print("✅ Login NINI OK")
    except Exception as e:
        logging.error(f"Error en login NINI: {e}", exc_info=True)
        print("❌ Error en login NINI")

def iniciar_pedido_nini(driver):
    """
    Inicializa el pedido en NINI siguiendo la ruta:
    1. Click en id="crearPedido"
    2. Click en id="next" (Continuar)
    3. Click en id="goToHome" (Ir al buscador)
    """
    try:
        logging.info("NINI: Iniciando flujo de pedido...")
        
        # Paso 1: Crear Pedido
        btn_crear = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "crearPedido"))
        )
        btn_crear.click()
        logging.info("NINI: Click en crearPedido OK")

        # Paso 2: Continuar (next) - esperar que esté disponible
        btn_next = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "next"))
        )
        btn_next.click()
        logging.info("NINI: Click en next OK")

        # Paso 3: Ir a Home (goToHome) - esperar que esté disponible
        btn_home = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "goToHome"))
        )
        btn_home.click()
        logging.info("NINI: Click en goToHome OK")

        # Verificación del buscador
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "searcher"))
        )
        logging.info("✅ NINI: Buscador listo")
        return True
    except Exception as e:
        logging.error(f"❌ NINI: Fallo al iniciar pedido: {e}")
        return False

def esperar_overlays_nini(driver, timeout=10):
    """
    Espera a que desaparezcan los overlays de bloqueo (.blockUI) en NINI.
    """
    try:
        # Verificar si hay overlays presentes
        overlays = driver.find_elements(By.CLASS_NAME, "blockUI")
        if overlays:
            logging.info(f"NINI: Detectados {len(overlays)} overlays activos (.blockUI). Esperando desaparición...")
            WebDriverWait(driver, timeout).until(
                EC.invisibility_of_element_located((By.CLASS_NAME, "blockUI"))
            )
            logging.info("NINI: Overlays desaparecieron correctamente.")
        return True
    except Exception as e:
        logging.warning(f"⚠️ NINI: Timeout o error esperando overlays: {e}")
        return False

def buscar_precio_nini(driver, ean):
    """
    Busca el precio siguiendo la ruta:
    1. Introducir EAN en id="searcher" y ENTER.
    2. Si aparece class="product-price actual-price", tomar precio.
    3. Si aparece class="confirmation-popup", marcar como No encontrado.
    """
    try:
        logging.info(f"NINI: Buscando EAN {ean}")
        
        # 1. Localizar buscador e ingresar EAN
        esperar_overlays_nini(driver)
        buscador = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "searcher"))
        )
        
        # Intentar click normal, si falla por interceptación, usar JavaScript
        try:
            esperar_overlays_nini(driver, timeout=5)
            buscador.click()
        except Exception as e:
            if "click intercepted" in str(e).lower():
                logging.warning("NINI: Click interceptado por overlay. Intentando click vía JavaScript...")
                driver.execute_script("arguments[0].click();", buscador)
            else:
                raise e

        buscador.send_keys(Keys.CONTROL + "a")
        buscador.send_keys(Keys.DELETE)
        
        # Ingresar EAN y presionar ENTER por separado
        buscador.send_keys(str(ean))
        time.sleep(0.3) # Breve pausa para que el sitio registre el input
        buscador.send_keys(Keys.ENTER)
        logging.info(f"NINI: EAN {ean} ingresado y ENTER enviado")
        
        # 2. ESPERAR RESULTADOS - LÓGICA SIMPLIFICADA
        start_time = time.time()
        timeout = 30
        
        logging.info(f"NINI: Buscando producto con clase .product.scannedProduct...")
        
        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)
            
            # 2.1 Verificar Error (blockUI)
            try:
                error_divs = driver.find_elements(By.CSS_SELECTOR, "div.blockUI.blockMsg.blockPage")
                for err in error_divs:
                    if err.is_displayed():
                        logging.warning(f"⚠️ NINI [{elapsed}s]: Bloqueo 'blockUI' detectado. No encontrado.")
                        return "No encontrado", ""
            except: pass

            # 2.2 Buscar Producto y Precios
            try:
                # Selector simplificado solicitado por el usuario
                # Usamos clases múltiples para mayor precisión
                rows = driver.find_elements(By.CSS_SELECTOR, "tr.product.scannedProduct, tr.product.nini_models_product_2919095.scannedProduct")
                
                if rows:
                    target_row = rows[0]
                    if target_row.is_displayed():
                        logging.info(f"✅ NINI [{elapsed}s]: Producto encontrado con selector de clase.")
                        
                        precio_reg = "No encontrado"
                        oferta_txt = ""

                        # Extraer Precio Anterior
                        try:
                            prev = target_row.find_element(By.CSS_SELECTOR, ".product-price.previous-price")
                            precio_reg = prev.text.strip()
                        except: pass

                        # Extraer Precio Actual
                        try:
                            act = target_row.find_element(By.CSS_SELECTOR, ".product-price.actual-price")
                            oferta_txt = act.text.strip()
                        except: pass

                        # Lógica de asignación de columnas
                        if (not precio_reg or precio_reg == "No encontrado") and oferta_txt:
                            precio_reg = oferta_txt
                            oferta_txt = ""

                        if precio_reg != "No encontrado" or oferta_txt:
                            logging.info(f"✅ NINI: {ean} -> Reg: {precio_reg} | Oferta: {oferta_txt}")
                            return precio_reg, oferta_txt
            except Exception as e:
                logging.debug(f"NINI [{elapsed}s]: Error buscando elementos: {e}")

            time.sleep(1)

        logging.warning(f"⌛ NINI: Timeout buscando {ean} tras {timeout}s.")
        return "No encontrado", ""

    except Exception as e:
        logging.error(f"❌ NINI: Error fatal buscando {ean}: {e}")
        return "No encontrado", ""

# =====================================================
# CARREFOUR
# =====================================================

# =====================================================
# CARREFOUR
# =====================================================

def buscar_precio_carrefour(driver, ean):
    try:
        logging.info(f"Buscando en CARREFOUR - EAN: {ean}")
        url = f"https://www.carrefour.com.ar/{ean}?_q={ean}&map=ft"
        driver.get(url)

        # Esperar que la página cargue completamente
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        ) 

        # 1. Chequeo explícito de "No encontrado"
        src = driver.page_source
        
        # Estrategia 1: Clase específica reportada por usuario
        try:
            if driver.find_elements(By.CSS_SELECTOR, "[class*='notFoundRow1']"):
                 logging.warning(f"CARREFOUR: Clase 'notFoundRow1' detectada para {ean}")
                 print(f"🔴 CARREFOUR | {ean} | No encontrado")
                 return "No encontrado"
        except:
             pass

        if "No encontramos resultados para" in src or "No hay productos que coincidan" in src:
             logging.warning(f"CARREFOUR: Texto 'No encontrado' detectado para {ean}")
             print(f"🔴 CARREFOUR | {ean} | No encontrado")
             return "No encontrado"
        
        # 2. VALIDACIÓN ESTRICTA DE EAN
        # En VTEX, si encuentra el producto, la URL suele contener el EAN (como ID o slug).
        # Si estamos en una página de búsqueda genérica, cuidado con los falsos positivos.
        current_url = driver.current_url.lower()
        
        # Check mas estricto: El EAN debe estar en la URL (indicando redirección directa al prod)
        # O BIEN, debemos encontrar el EAN textualmente en algún lugar clave de la ficha (ej: SKU)
        match_confirmado = False
        
        if str(ean) in current_url:
            match_confirmado = True
        else:
            # Si no está en URL, buscamos en el body un indicador de SKU/EAN
            # A veces carrefour muestra "SKU: 12345"
            if f"sku:{ean}" in src.lower() or f"ean:{ean}" in src.lower() or str(ean) in src:
                 # Verificar que no sea solo lo del input de busqueda
                 # Buscamos un container de producto
                 match_confirmado = True # Asumimos riesgo si está en el source fuera de input, pero es mejor que nada

        if not match_confirmado:
             logging.warning(f"CARREFOUR: EAN {ean} no confirmado en URL ni en contenido visible. Posible falso positivo.")
             print(f"🔴 CARREFOUR | {ean} | No coincidencia exacta")
             return "No encontrado"

        precios = driver.find_elements(
            By.CSS_SELECTOR,
            "span.valtech-carrefourar-product-price-0-x-sellingPrice"
        )
        
        if not precios:
             # Intento alternativo de selector
             precios = driver.find_elements(By.XPATH, "//span[contains(@class, 'sellingPrice')]")

        precio_final = "No encontrado"
        promo_info = ""

        for p in precios:
            texto = p.text.strip()
            if texto and ("$" in texto or any(char.isdigit() for char in texto)):
                precio_final = texto
                
                # DETECCION DE OFERTA
                # Si tiene la clase --hasListPrice, es una oferta
                clases = p.get_attribute("class")
                if "valtech-carrefourar-product-price-0-x-sellingPrice--hasListPrice" in clases:
                    logging.info(f"CARREFOUR: Oferta detectada para {ean}")
                    # Buscar el tooltipText
                    tooltips = driver.find_elements(By.CLASS_NAME, "tooltipText")
                    if tooltips:
                        promo_info = tooltips[0].text.strip()
                        logging.info(f"CARREFOUR: Info de promo hallada: {promo_info}")
                    else:
                        promo_info = "Oferta"
                
                logging.info(f"CARREFOUR: Producto {ean} encontrado - Precio: {precio_final}")
                print(f"🟢 CARREFOUR | {ean} | {precio_final} | {promo_info}")
                return precio_final, promo_info

        logging.warning(f"CARREFOUR: Producto {ean} encontrado pero sin precio")
        print(f"🔴 CARREFOUR | {ean} | No encontrado")
        return "No encontrado", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en CARREFOUR: {e}", exc_info=True)
        print(f"❌ CARREFOUR | {ean} | Error")
        return "No encontrado", ""

# =====================================================
# VEA
# =====================================================

def buscar_precio_vea(driver, ean):
    try:
        logging.info(f"Buscando en VEA - EAN: {ean}")
        url = f"https://www.vea.com.ar/{ean}?_q={ean}&map=ft"
        driver.get(url)

        # Esperar que la página cargue completamente
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # 1. Chequeo explícito de "No encontrado"
        # Estrategia 1: Clase específica reportada por el usuario
        # vtex-flex-layout-0-x-flexRowContent--row-opss-notfound
        try:
            if driver.find_elements(By.CSS_SELECTOR, "[class*='row-opss-notfound']"):
                 logging.warning(f"VEA: Clase 'row-opss-notfound' detectada para {ean}")
                 print(f"🔴 VEA | {ean} | No encontrado")
                 return "No encontrado"
        except:
             pass

        try:
            if "No encontramos resultados" in driver.page_source:
                logging.warning(f"VEA: Texto 'No encontramos resultados' detectado para {ean}")
                print(f"🔴 VEA | {ean} | No encontrado")
                return "No encontrado"
        except:
            pass
            
        # 2. VALIDACIÓN ESTRICTA DE EAN
        current_url = driver.current_url.lower()
        match_confirmado = False
        
        if str(ean) in current_url:
            match_confirmado = True
        else:
            # Buscar en especificaciones o scripts
            if str(ean) in driver.page_source:
                 match_confirmado = True # Heurística simple

        if not match_confirmado:
             logging.warning(f"VEA: EAN {ean} no confirmado en URL/Source. Posible falso positivo.")
             print(f"🔴 VEA | {ean} | No coincidencia exacta")
             return "No encontrado", "", ""

        # --- ACTUALIZACIÓN SEGÚN SOLICITUD USUARIO ---
        try:
            # 1. Verificar existencia del article con clase específica solicitada por el usuario
            article_selector = "article.vtex-product-summary-2-x-element.pointer.pt3.pb4.flex.flex-column.h-100"
            try:
                article_container = WebDriverWait(driver, 6).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, article_selector))
                )
                logging.info(f"VEA: Articulo verificado para {ean}")
            except:
                # Intento con selector flexible por si hay leves variaciones en clases
                article_container = WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article[class*='vtex-product-summary-2-x-element']"))
                )

            # 2. Buscar precio regular (clase específica)
            precio_txt = "No encontrado"
            try:
                # div class="veaargentina-store-theme-2t-mVsKNpKjmCAEM_AMCQH"
                precio_reg_elem = article_container.find_element(By.CSS_SELECTOR, "div.veaargentina-store-theme-2t-mVsKNpKjmCAEM_AMCQH")
                precio_txt = precio_reg_elem.text.strip()
            except:
                # Fallback
                precio_elems = article_container.find_elements(By.CSS_SELECTOR, "div[class*='2t-mVsKNpKjmCAEM_AMCQH']")
                if precio_elems:
                    precio_txt = precio_elems[0].text.strip()

            # 3. Buscar oferta (id y clase específica)
            oferta_txt = ""
            try:
                # div id="priceContainer" class="veaargentina-store-theme-1dCOMij_MzTzZOCohX1K7w"
                oferta_elem = article_container.find_element(By.CSS_SELECTOR, "div#priceContainer.veaargentina-store-theme-1dCOMij_MzTzZOCohX1K7w")
                oferta_txt = oferta_elem.text.strip().replace("\n", " ")
            except:
                # Fallback
                oferta_elems = article_container.find_elements(By.CSS_SELECTOR, "#priceContainer, div[class*='1dCOMij_MzTzZOCohX1K7w']")
                if oferta_elems:
                    oferta_txt = oferta_elems[0].text.strip().replace("\n", " ")

            # 4. Mantener Dinámica (opcional, pero estaba en el código original)
            dinamica_txt = ""
            try:
                din_elems = article_container.find_elements(By.CSS_SELECTOR, "*[class*='14k7D0cUQ_45k_MeZ_yfFo']")
                for d_e in din_elems:
                    t = d_e.text.strip()
                    if t:
                        dinamica_txt = t
                        break
            except:
                pass

            if precio_txt != "No encontrado" or oferta_txt != "":
                logging.info(f"✅ VEA: {ean} - Regular: {precio_txt} | Oferta: {oferta_txt}")
                print(f"🟢 VEA | {ean} | {precio_txt} | {oferta_txt} | {dinamica_txt}")
                return precio_txt, oferta_txt, dinamica_txt

        except Exception as e:
            logging.error(f"Error interno en captura VEA para {ean}: {e}")

        print(f"🔴 VEA | {ean} | No encontrado")
        return "No encontrado", "", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en VEA: {e}", exc_info=True)
        print(f"❌ VEA | {ean} | Error")
        return "No encontrado", "", ""

# =====================================================
# DISCO
# =====================================================

def buscar_precio_disco(driver, ean):
    try:
        logging.info(f"Buscando en DISCO - EAN: {ean}")
        url = f"https://www.disco.com.ar/{ean}?_q={ean}&map=ft"
        driver.get(url)

        # Esperar que la página cargue completamente
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # 1. Chequeo explícito de "No encontrado"
        try:
            if driver.find_elements(By.CSS_SELECTOR, "[class*='row-opss-notfound']"):
                 logging.warning(f"DISCO: Clase 'row-opss-notfound' detectada para {ean}")
                 return "No encontrado", "", ""
        except:
             pass

        # 2. VALIDACIÓN ESTRICTA
        try:
            current_url = driver.current_url.lower()
            match_confirmado = (str(ean) in current_url)
            
            if not match_confirmado:
                # Búsqueda liviana en el texto visible del body
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if str(ean) in body_text:
                    match_confirmado = True
        except:
            match_confirmado = False
        
        if not match_confirmado:
             logging.warning(f"DISCO: EAN {ean} no confirmado. Posible falso positivo.")
             return "No encontrado", "", ""

        # --- ACTUALIZACIÓN SEGÚN SOLICITUD USUARIO (DISCO) ---
        try:
            # 1. Verificar existencia del article con clase específica solicitada por el usuario
            article_selector = "article.vtex-product-summary-2-x-element.pointer.pt3.pb4.flex.flex-column.h-100"
            try:
                article_container = WebDriverWait(driver, 6).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, article_selector))
                )
                logging.info(f"DISCO: Articulo verificado para {ean}")
            except:
                # Intento con selector flexible por si hay leves variaciones en clases
                article_container = WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article[class*='vtex-product-summary-2-x-element']"))
                )

            # 2. Buscar precio regular (clase específica discoargentina)
            precio_txt = "No encontrado"
            try:
                # div class="discoargentina-store-theme-2t-mVsKNpKjmCAEM_AMCQH"
                precio_reg_elem = article_container.find_element(By.CSS_SELECTOR, "div.discoargentina-store-theme-2t-mVsKNpKjmCAEM_AMCQH")
                precio_txt = precio_reg_elem.text.strip()
            except:
                # Fallback
                precio_elems = article_container.find_elements(By.CSS_SELECTOR, "div[class*='2t-mVsKNpKjmCAEM_AMCQH']")
                if precio_elems:
                    precio_txt = precio_elems[0].text.strip()

            # 3. Buscar oferta (id y clase específica discoargentina)
            oferta_txt = ""
            try:
                # div id="priceContainer" class="discoargentina-store-theme-1dCOMij_MzTzZOCohX1K7w"
                oferta_elem = article_container.find_element(By.CSS_SELECTOR, "div#priceContainer.discoargentina-store-theme-1dCOMij_MzTzZOCohX1K7w")
                oferta_txt = oferta_elem.text.strip().replace("\n", " ")
            except:
                # Fallback
                oferta_elems = article_container.find_elements(By.CSS_SELECTOR, "#priceContainer, div[class*='1dCOMij_MzTzZOCohX1K7w']")
                if oferta_elems:
                    oferta_txt = oferta_elems[0].text.strip().replace("\n", " ")

            # 4. Mantener Dinámica
            dinamica_txt = ""
            try:
                din_elems = article_container.find_elements(By.CSS_SELECTOR, "*[class*='14k7D0cUQ_45k_MeZ_yfFo']")
                for d_e in din_elems:
                    t = d_e.text.strip()
                    if t:
                        dinamica_txt = t
                        break
            except:
                pass

            if precio_txt != "No encontrado" or oferta_txt != "":
                logging.info(f"✅ DISCO: {ean} - Regular: {precio_txt} | Oferta: {oferta_txt}")
                print(f"🟢 DISCO | {ean} | {precio_txt} | {oferta_txt} | {dinamica_txt}")
                return precio_txt, oferta_txt, dinamica_txt

        except Exception as e:
            logging.error(f"Error interno en captura DISCO para {ean}: {e}")

        print(f"🔴 DISCO | {ean} | No encontrado")
        return "No encontrado", "", ""

    except Exception as e:
        logging.error(f"Error buscando {ean} en DISCO: {e}", exc_info=True)
        return "No encontrado", "", ""

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
                    "disco": True
                }
            
            elif opcion == "2":
                seleccion = {
                    "nini": False,
                    "carrefour": False,
                    "vea": False,
                    "disco": False
                }
                
                print("\n📝 Selecciona las páginas que deseas buscar (s/n):")
                
                respuesta = input("  🔹 NINI (s/n): ").strip().lower()
                seleccion["nini"] = respuesta == "s"
                
                respuesta = input("  🔹 CARREFOUR (s/n): ").strip().lower()
                seleccion["carrefour"] = respuesta == "s"
                
                respuesta = input("  🔹 VEA (s/n): ").strip().lower()
                seleccion["vea"] = respuesta == "s"
                
                respuesta = input("  🔹 DISCO (s/n): ").strip().lower()
                seleccion["disco"] = respuesta == "s"
                
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
            login_nini(driver)
            if iniciar_pedido_nini(driver):
                for idx, row in df.iterrows():
                    check_pause()
                    # Verificar si ya tiene resultado válido
                    if str(row.get("Precio NINI", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                        continue
                    
                    res = buscar_precio_nini(driver, row["SKU"])
                    if isinstance(res, tuple):
                        precio, oferta = res[0], res[1]
                        site_results.append({
                            'idx': idx,
                            'SKU': row['SKU'],
                            'Precio': precio,
                            'Oferta': oferta
                        })
                        emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta)
                    else:
                        site_results.append({
                            'idx': idx,
                            'SKU': row['SKU'],
                            'Precio': res,
                            'Oferta': ''
                        })
                        emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), res)
            else:
                logging.error(f"[{site_name.upper()}] ⚠️ Falla en inicialización del pedido")
        
        elif site_name == "carrefour":
            for idx, row in df.iterrows():
                check_pause()
                if str(row.get("Precio CARREFOUR", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                res = buscar_precio_carrefour(driver, row["SKU"])
                if isinstance(res, tuple):
                    precio, oferta = res[0], res[1]
                    site_results.append({
                        'idx': idx,
                        'SKU': row['SKU'],
                        'Precio': precio,
                        'Oferta': oferta
                    })
                    emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['SKU'],
                        'Precio': res,
                        'Oferta': ''
                    })
                    emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), res)
        
        elif site_name == "vea":
            for idx, row in df.iterrows():
                check_pause()
                if str(row.get("Precio VEA", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                res = buscar_precio_vea(driver, row["SKU"])
                if isinstance(res, tuple):
                    precio, oferta, dinamica = res[0], res[1], res[2] if len(res) > 2 else ''
                    site_results.append({
                        'idx': idx,
                        'SKU': row['SKU'],
                        'Precio': precio,
                        'Oferta': oferta,
                        'Dinamica': dinamica
                    })
                    emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta, dinamica)
                else:
                    site_results.append({
                        'idx': idx,
                        'SKU': row['SKU'],
                        'Precio': res,
                        'Oferta': '',
                        'Dinamica': ''
                    })
                    emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), res)
        
        elif site_name == "disco":
            for idx, row in df.iterrows():
                check_pause()
                if str(row.get("Precio DISCO", "Pendiente")) not in ["Pendiente", "No encontrado", "Error"]:
                    continue
                
                try:
                    res = buscar_precio_disco(driver, row["SKU"])
                    if isinstance(res, tuple):
                        precio, oferta, dinamica = res[0], res[1], res[2] if len(res) > 2 else ''
                        site_results.append({
                            'idx': idx,
                            'SKU': row['SKU'],
                            'Precio': precio,
                            'Oferta': oferta,
                            'Dinamica': dinamica
                        })
                        emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), precio, oferta, dinamica)
                    else:
                        site_results.append({
                            'idx': idx,
                            'SKU': row['SKU'],
                            'Precio': res,
                            'Oferta': '',
                            'Dinamica': ''
                        })
                        emit_product_update(idx, row['SKU'], row.get('codigo', ''), row.get('descripcion', ''), res)
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
                            'SKU': row['SKU'],
                            'Precio': 'Error',
                            'Oferta': '',
                            'Dinamica': ''
                        })
                    else:
                        logging.error(f"[{site_name.upper()}] Error procesando {row['SKU']}: {e}")
                        site_results.append({
                            'idx': idx,
                            'SKU': row['SKU'],
                            'Precio': 'No encontrado',
                            'Oferta': '',
                            'Dinamica': ''
                        })
        
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
            df = pd.read_excel(INPUT_FILE, dtype={"SKU": str})

        # Loguear primeros 5 SKUs para que el usuario verifique
        if df is not None:
             first_skus = df['SKU'].head(5).tolist()
             logging.info(f"Cargados {len(df)} productos. Primeros SKUs: {first_skus}")

        if not ignore_cache and os.path.exists(OUTPUT_FILE):
            logging.info(f"Leyendo archivo de salida existente: {OUTPUT_FILE}")
            df_old = pd.read_excel(OUTPUT_FILE, dtype={"SKU": str})
            df = df.merge(df_old, on="SKU", how="left", suffixes=("", "_old"))

            for col in ["Precio NINI", "Oferta NINI", "Precio CARREFOUR", "Oferta CARREFOUR", "Precio VEA", "Oferta VEA", "Dinamica VEA", "Precio DISCO", "Oferta DISCO", "Dinamica DISCO"]:
                if f"{col}_old" in df.columns:
                    df[col] = df[f"{col}_old"]

            df = df[df.columns.drop(list(df.filter(regex="_old")))]
        else:
            if ignore_cache and os.path.exists(OUTPUT_FILE):
                logging.info("Ignorando archivo de salida existente (Force Rescan).")
            else:
                logging.info("Creando nuevo archivo de resultados")
            
            # Inicializar columnas por defecto
            for col in ["Precio NINI", "Oferta NINI", "Precio CARREFOUR", "Oferta CARREFOUR", "Precio VEA", "Oferta VEA", "Dinamica VEA", "Precio DISCO", "Oferta DISCO", "Dinamica DISCO"]:
                 if col not in df.columns:
                      df[col] = "Pendiente"
            
            # Asegurar que no haya NaNs en las columnas de precio si el DF venía con ellas
            for col in ["Precio NINI", "Precio CARREFOUR", "Oferta CARREFOUR", "Precio VEA", "Oferta VEA", "Dinamica VEA", "Precio DISCO", "Oferta DISCO", "Dinamica DISCO"]:
                 df[col] = df[col].fillna("Pendiente")

        # Guardar resultados finales
        df.to_excel(OUTPUT_FILE, index=False)

        # ===================================================================
        # IMPLEMENTACIÓN PARALELA - FASE 1
        # ===================================================================
        
        import threading
        
        buscar_nini = selection.get("nini", False)
        buscar_carrefour = selection.get("carrefour", False)
        buscar_vea = selection.get("vea", False)
        buscar_disco = selection.get("disco", False)

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
                        'sku': str(row['SKU']),
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
        
        # Guardar resultados finales consolidados
        df.to_excel(OUTPUT_FILE, index=False)
        logging.info(f"💾 Resultados guardados: {total_actualizados} precios actualizados")
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
