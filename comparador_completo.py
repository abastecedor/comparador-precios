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
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--single-process")
        options.add_argument("--remote-debugging-port=9222")
        logging.info("Configuración Railway/Docker aplicada")

    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

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
    try:
        logging.info("Iniciando pedido en NINI...")
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, "crearPedido"))
        ).click()

        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, "next"))
        ).click()

        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "goToHome"))
        ).click()

        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.ID, "searcher"))
        )

        logging.info("✅ Pedido NINI iniciado correctamente")
        print("✅ Pedido NINI iniciado")
    except Exception as e:
        logging.error(f"Error al iniciar pedido NINI: {e}", exc_info=True)
        print("❌ Error al iniciar pedido NINI")

def buscar_precio_nini(driver, ean):
    try:
        logging.info(f"Buscando en NINI - EAN: {ean}")
        buscador = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "searcher"))
        )

        # Limpiar agresivamente
        buscador.click()
        buscador.send_keys(Keys.CONTROL + "a")
        buscador.send_keys(Keys.DELETE)
        buscador.clear()
        
        buscador.send_keys(str(ean), Keys.RETURN)
        
        # Espera explícita solicitada por el usuario para asegurar carga
        time.sleep(2)
        
        # Esperar a que 'algo' pase. A veces la tabla tarda en refrescarse.
        # Si el precio anterior sigue ahí, es un falso positivo.
        # Lo ideal es esperar que el spinner de carga desaparezca si existe, 
        # pero como heurística, esperaremos un poco y verificaremos "Descripción" del producto.
        
        # Esperar a que aparezca o el precio O el popup de no encontrado
        start_time = time.time()
        found_price = None
        
        while time.time() - start_time < 12: # Damos un poco más de tiempo
            # 1. Popup
            try:
                popup = driver.find_element(By.CLASS_NAME, "confirmation-popup")
                if popup.is_displayed():
                    driver.find_element(By.CLASS_NAME, "ok-btn").click()
                    logging.warning(f"NINI: Producto {ean} no encontrado (popup)")
                    print(f"🔴 NINI | {ean} | No encontrado")
                    return "No encontrado"
            except:
                pass

            # 2. Precio
            try:
                # Intentamos buscar también la descripción para ver qué encontramos
                precio_element = driver.find_element(By.CSS_SELECTOR, ".product-price.actual-price")
                if precio_element.is_displayed():
                    # Verificar descripción si es posible para asegurar que no es el producto anterior
                    # (Esto asume que hay un elemento .product-description, común en este tipo de ecommerces)
                    try:
                        desc_element = driver.find_element(By.CSS_SELECTOR, ".product-description")
                        desc = desc_element.text.strip()
                        logging.info(f"NINI: Potencial coincidencia: '{desc}'")
                    except:
                        pass

                    found_price = precio_element.text.strip()
                    break
            except:
                pass
            
            time.sleep(0.5)

        if found_price:
            logging.info(f"NINI: Producto {ean} encontrado - Precio: {found_price}")
            print(f"🟢 NINI | {ean} | {found_price}")
            return found_price
        else:
            logging.warning(f"NINI: Timeout buscando {ean} (ni precio ni popup)")
            return "No encontrado"

    except Exception as e:
        logging.error(f"Error buscando {ean} en NINI: {e}", exc_info=True)
        print(f"❌ NINI | {ean} | Error")
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
        # Estrategia 1: Clase específica reportada por el usuario
        try:
            if driver.find_elements(By.CSS_SELECTOR, "[class*='row-opss-notfound']"):
                 logging.warning(f"DISCO: Clase 'row-opss-notfound' detectada para {ean}")
                 print(f"🔴 DISCO | {ean} | No encontrado")
                 return "No encontrado"
        except:
             pass

        try:
            if "No encontramos resultados" in driver.page_source:
                logging.warning(f"DISCO: Texto 'No encontramos resultados' detectado para {ean}")
                print(f"🔴 DISCO | {ean} | No encontrado")
                return "No encontrado"
        except:
            pass

        # 2. VALIDACIÓN ESTRICTA
        current_url = driver.current_url.lower()
        match_confirmado = False
        
        if str(ean) in current_url:
             match_confirmado = True
        else:
             if str(ean) in driver.page_source:
                  match_confirmado = True
        
        if not match_confirmado:
             logging.warning(f"DISCO: EAN {ean} no confirmado en URL/Source. Posible falso positivo.")
             print(f"🔴 DISCO | {ean} | No coincidencia exacta")
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

        print(f"🔴 DISCO | {ean} | No encontrado")
        return "No encontrado"

    except Exception as e:
        logging.error(f"Error buscando {ean} en DISCO: {e}", exc_info=True)
        print(f"❌ DISCO | {ean} | Error")
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
                iniciar_pedido_nini(driver)

                for i, row in df.iterrows():
                    check_pause()
                    if str(row["Precio NINI"]) not in ["Pendiente", "No encontrado", "Error"]:
                        continue

                    df.at[i, "Precio NINI"] = buscar_precio_nini(driver, row["SKU"])
                    df.to_excel(OUTPUT_FILE, index=False)
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

                df.at[i, "Precio DISCO"] = buscar_precio_disco(driver, row["SKU"])
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
