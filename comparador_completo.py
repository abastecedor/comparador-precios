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

def configurar_driver():
    logging.info("Iniciando configuración del driver...")
    options = Options()
    
    # Detectar si estamos en Railway/Docker (Linux)
    is_railway = os.environ.get('RAILWAY_ENVIRONMENT') or os.path.exists('/.dockerenv')
    
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

    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

        # Timeout implícito corto para evitar esperas infinitas si el navegador falla
        driver.set_page_load_timeout(30)

        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logging.info("Driver configurado exitosamente")
        return driver
    except Exception as e:
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
        time.sleep(2)

        # Paso 2: Continuar (next)
        btn_next = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "next"))
        )
        btn_next.click()
        logging.info("NINI: Click en next OK")
        time.sleep(2)

        # Paso 3: Ir a Home (goToHome)
        btn_home = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "goToHome"))
        )
        btn_home.click()
        logging.info("NINI: Click en goToHome OK")
        time.sleep(3)

        # Verificación del buscador
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "searcher"))
        )
        logging.info("✅ NINI: Buscador listo")
        return True
    except Exception as e:
        logging.error(f"❌ NINI: Fallo al iniciar pedido: {e}")
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
        buscador = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "searcher"))
        )
        buscador.click()
        buscador.send_keys(Keys.CONTROL + "a")
        buscador.send_keys(Keys.DELETE)
        
        # Ingresar EAN y presionar ENTER por separado
        buscador.send_keys(str(ean))
        time.sleep(1) # Esperar a que el sitio registre el input
        buscador.send_keys(Keys.ENTER)
        logging.info(f"NINI: EAN {ean} ingresado y ENTER enviado")
        
        # 2. Esperar resultado o popup
        start_time = time.time()
        while time.time() - start_time < 15:
            # 2.1 Verificar Precio (Éxito)
            precios = driver.find_elements(By.CSS_SELECTOR, ".product-price.actual-price")
            if precios and precios[0].is_displayed():
                precio_txt = precios[0].text.strip()
                if precio_txt and "$" in precio_txt and "0,00" not in precio_txt:
                    logging.info(f"✅ NINI: {ean} encontrado: {precio_txt}")
                    return precio_txt

            # 2.2 Verificar Popup (No encontrado)
            popups = driver.find_elements(By.CLASS_NAME, "confirmation-popup")
            if popups and popups[0].is_displayed():
                logging.warning(f"⚠️ NINI: {ean} no encontrado (popup detectable)")
                # Hacer click en OK si existe para limpiar la pantalla para el siguiente
                try:
                    popups[0].find_element(By.CSS_SELECTOR, "a.ok-btn, .ok-btn").click()
                except:
                    pass
                return "No encontrado"

            time.sleep(1)

        logging.warning(f"⌛ NINI: Timeout buscando {ean}")
        return "No encontrado"

    except Exception as e:
        logging.error(f"❌ NINI: Error buscando {ean}: {e}")
        return "No encontrado"

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

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        time.sleep(3) 

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

        for p in precios:
            texto = p.text.strip()
            if texto and ("$" in texto or any(char.isdigit() for char in texto)):
                logging.info(f"CARREFOUR: Producto {ean} encontrado - Precio: {texto}")
                print(f"🟢 CARREFOUR | {ean} | {texto}")
                return texto

        logging.warning(f"CARREFOUR: Producto {ean} encontrado pero sin precio")
        print(f"🔴 CARREFOUR | {ean} | No encontrado")
        return "No encontrado"

    except Exception as e:
        logging.error(f"Error buscando {ean} en CARREFOUR: {e}", exc_info=True)
        print(f"❌ CARREFOUR | {ean} | Error")
        return "No encontrado"

# =====================================================
# VEA
# =====================================================

def buscar_precio_vea(driver, ean):
    try:
        logging.info(f"Buscando en VEA - EAN: {ean}")
        url = f"https://www.vea.com.ar/{ean}?_q={ean}&map=ft"
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        time.sleep(3)

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
             return "No encontrado"

        try:
            precio_element = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.ID, "priceContainer"))
            )
            texto = precio_element.text.strip()
            
            if texto and ("$" in texto or any(char.isdigit() for char in texto)):
                 logging.info(f"VEA: Producto {ean} encontrado - Precio: {texto}")
                 print(f"🟢 VEA | {ean} | {texto}")
                 return texto
        except Exception as e:
             logging.warning(f"VEA: No se encontró precio para {ean} (Timeout o elemento no visible)")

        print(f"🔴 VEA | {ean} | No encontrado")
        return "No encontrado"

    except Exception as e:
        logging.error(f"Error buscando {ean} en VEA: {e}", exc_info=True)
        print(f"❌ VEA | {ean} | Error")
        return "No encontrado"

# =====================================================
# DISCO
# =====================================================

def buscar_precio_disco(driver, ean):
    try:
        logging.info(f"Buscando en DISCO - EAN: {ean}")
        url = f"https://www.disco.com.ar/{ean}?_q={ean}&map=ft"
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        time.sleep(3)

        # 1. Chequeo explícito de "No encontrado"
        try:
            if driver.find_elements(By.CSS_SELECTOR, "[class*='row-opss-notfound']"):
                 logging.warning(f"DISCO: Clase 'row-opss-notfound' detectada para {ean}")
                 return "No encontrado"
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
             return "No encontrado"

        try:
            precio_element = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.ID, "priceContainer"))
            )
            texto = precio_element.text.strip()
            
            if texto and ("$" in texto or any(char.isdigit() for char in texto)):
                logging.info(f"DISCO: Producto {ean} encontrado - Precio: {texto}")
                print(f"🟢 DISCO | {ean} | {texto}")
                return texto
        except Exception as e:
            logging.warning(f"DISCO: No se encontró precio para {ean} (Timeout o elemento no visible)")

        return "No encontrado"

    except Exception as e:
        logging.error(f"Error buscando {ean} en DISCO: {e}", exc_info=True)
        return "No encontrado"

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

def run_scraper(selection, log_queue=None, input_df=None, ignore_cache=False, pause_event=None):
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
    """
    
    def check_pause():
        if pause_event and not pause_event.is_set():
            logging.info("⏸️ Scraper pausado. Esperando reanudación...")
            pause_event.wait()
            logging.info("▶️ Scraper reanudado.")
    
    # Configurar logger para capturar logs en la cola si existe
    if log_queue:
        queue_handler = logging.handlers.QueueHandler(log_queue)
        root_logger = logging.getLogger()
        root_logger.addHandler(queue_handler)
        root_logger.setLevel(logging.INFO)

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

            for col in ["Precio NINI", "Precio CARREFOUR", "Precio VEA", "Precio DISCO"]:
                if f"{col}_old" in df.columns:
                    df[col] = df[f"{col}_old"]

            df = df[df.columns.drop(list(df.filter(regex="_old")))]
        else:
            if ignore_cache and os.path.exists(OUTPUT_FILE):
                logging.info("Ignorando archivo de salida existente (Force Rescan).")
            else:
                logging.info("Creando nuevo archivo de resultados")
            
            # Inicializar columnas por defecto
            for col in ["Precio NINI", "Precio CARREFOUR", "Precio VEA", "Precio DISCO"]:
                 if col not in df.columns:
                      df[col] = "Pendiente"
            
            # Asegurar que no haya NaNs en las columnas de precio si el DF venía con ellas
            for col in ["Precio NINI", "Precio CARREFOUR", "Precio VEA", "Precio DISCO"]:
                 df[col] = df[col].fillna("Pendiente")

        # GUARDAR INICIALMENTE EL ESTADO
        # Esto asegura que si el usuario descarga el archivo inmediatamente, 
        # verá los nuevos productos (con estado "Pendiente") y no el archivo viejo.
        logging.info(f"Guardando estado inicial en {OUTPUT_FILE}")
        df.to_excel(OUTPUT_FILE, index=False)

        driver = configurar_driver()

        if buscar_nini:
            logging.info("--- Iniciando proceso NINI ---")
            try:
                login_nini(driver)
                if iniciar_pedido_nini(driver):
                    for i, row in df.iterrows():
                        check_pause()
                        if str(row["Precio NINI"]) not in ["Pendiente", "No encontrado", "Error"]:
                            continue

                        df.at[i, "Precio NINI"] = buscar_precio_nini(driver, row["SKU"])
                        df.to_excel(OUTPUT_FILE, index=False)
                else:
                    logging.error("⚠️ Se saltará la búsqueda en NINI por falla en la inicialización del pedido.")
                    for i, _ in df.iterrows():
                        if df.at[i, "Precio NINI"] == "Pendiente":
                            df.at[i, "Precio NINI"] = "Error"
            except Exception as e:
                 logging.error(f"Error en bloque NINI: {e}")
            
            # Limpiar cookies para evitar conflictos
            try:
                driver.delete_all_cookies()
                logging.info("Cookies eliminadas tras NINI")
            except:
                pass

        if buscar_carrefour:
            logging.info("--- Iniciando proceso CARREFOUR ---")
            for i, row in df.iterrows():
                check_pause()
                if str(row["Precio CARREFOUR"]) not in ["Pendiente", "No encontrado", "Error"]:
                    continue

                df.at[i, "Precio CARREFOUR"] = buscar_precio_carrefour(driver, row["SKU"])
                df.to_excel(OUTPUT_FILE, index=False)
            
            try:
                driver.delete_all_cookies()
                logging.info("Cookies eliminadas tras CARREFOUR")
            except:
                pass

        if buscar_vea:
            logging.info("--- Iniciando proceso VEA ---")
            for i, row in df.iterrows():
                check_pause()
                if str(row["Precio VEA"]) not in ["Pendiente", "No encontrado", "Error"]:
                    continue

                df.at[i, "Precio VEA"] = buscar_precio_vea(driver, row["SKU"])
                df.to_excel(OUTPUT_FILE, index=False)
            
            try:
                driver.delete_all_cookies()
                logging.info("Cookies eliminadas tras VEA")
            except:
                pass

        if buscar_disco:
            logging.info("--- Iniciando proceso DISCO ---")
            for i, row in df.iterrows():
                check_pause()
                if str(row["Precio DISCO"]) not in ["Pendiente", "No encontrado", "Error"]:
                    continue

                try:
                    df.at[i, "Precio DISCO"] = buscar_precio_disco(driver, row["SKU"])
                except Exception as e:
                    error_msg = str(e).lower()
                    if "tab crashed" in error_msg or "session deleted" in error_msg or "not reachable" in error_msg:
                        logging.error(f"⚠️ DISCO: El navegador crasheó ('tab crashed'). Reiniciando driver...")
                        try:
                            driver.quit()
                        except:
                            pass
                        driver = configurar_driver()
                        df.at[i, "Precio DISCO"] = "Error"
                    else:
                        logging.error(f"Error procesando {ean} en DISCO: {e}")
                        df.at[i, "Precio DISCO"] = "No encontrado"

                df.to_excel(OUTPUT_FILE, index=False)
            
            try:
                driver.delete_all_cookies()
                logging.info("Cookies eliminadas tras DISCO")
            except:
                pass

        logging.info("Proceso finalizado correctamente")
        print("✅ Proceso finalizado correctamente")

    except Exception as e:
        logging.critical(f"Error inesperado en la ejecución principal: {e}", exc_info=True)
        print(f"❌ Error fatal: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        # Señal de fin para el stream
        if log_queue:
            logging.info("STOP_SIGNAL")
            # Limpiar handler para no duplicar en futuras ejecuciones
            if 'queue_handler' in locals():
                root_logger.removeHandler(queue_handler)


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
