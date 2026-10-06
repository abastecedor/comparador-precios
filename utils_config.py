import logging
import os
import sys
import time
import atexit
import tempfile

# ─── FILE-BASED SINGLETON LOCK ───────────────────────────────────────────────
# More reliable than socket-based locks on Windows (avoids TIME_WAIT issues).

LOCK_FILE = os.path.join(tempfile.gettempdir(), "comparador_precios.lock")
_lock_fd = None

def _is_pid_alive(pid):
    """Check if a process with given PID is still running (cross-platform)."""
    try:
        import os
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False

def get_singleton_lock():
    """
    Tries to acquire a file-based singleton lock.
    Returns True if lock acquired (we are the only instance).
    Returns False if another instance is already running.
    """
    global _lock_fd
    try:
        # Check if a lock file exists and if the PID in it is still alive
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                if old_pid != os.getpid() and _is_pid_alive(old_pid):
                    logging.warning(f"Otra instancia encontrada con PID {old_pid}")
                    return False
                else:
                    logging.info(f"Lock antiguo (PID {old_pid}) ya no existe. Sobreescribiendo.")
            except (ValueError, PermissionError, Exception) as e:
                logging.info(f"Lock antiguo inválido, sobreescribiendo. ({e})")
        
        # Write our PID to the lock file
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        
        # Register cleanup on exit
        atexit.register(_release_lock)
        logging.debug(f"Lock obtenido: {LOCK_FILE} (PID={os.getpid()})")
        return True
        
    except Exception as e:
        logging.warning(f"No se pudo obtener lock: {e}")
        # If we can't even create the lock file, just proceed
        return True


def _release_lock(*args, **kwargs):
    """Removes the lock file on clean exit."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(LOCK_FILE)
                logging.debug("Lock liberado.")
    except Exception:
        pass


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def configurar_logging_shared(filename=None):
    """Configures logging once; subsequent calls are no-ops."""
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured
    
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Optional file handler
    if filename:
        try:
            fh = logging.FileHandler(filename, encoding='utf-8')
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except Exception:
            pass
