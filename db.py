"""
Capa de acceso a datos compatible con SQLite (local) y PostgreSQL (Vercel/producción).

Localmente:      no definir DATABASE_URL  →  usa mezclas.db (SQLite)
En producción:   DATABASE_URL=postgres://... →  usa PostgreSQL
"""

import os
import sqlite3 as _sqlite3
from flask import g

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL')
# Vercel Postgres usa "postgres://" pero psycopg2 necesita "postgresql://"
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

BACKEND = 'postgres' if DATABASE_URL else 'sqlite'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, 'mezclas.db')
EXCEL_PATH = os.path.join(BASE_DIR, 'Mezclas_Base.xlsx')

if BACKEND == 'postgres':
    import psycopg2
    import psycopg2.extras


# ──────────────────────────────────────────────────────────
# Wrapper PostgreSQL  (imita la interfaz de sqlite3)
# ──────────────────────────────────────────────────────────

def _pg_sql(sql):
    """Convierte placeholders ? de SQLite a %s de PostgreSQL."""
    return sql.replace('?', '%s')


class _PgCursor:
    """Cursor de psycopg2 con la misma interfaz que sqlite3.Cursor."""

    def __init__(self, raw_cur):
        self._cur = raw_cur
        self.lastrowid = None

    def fetchone(self):
        try:
            return self._cur.fetchone()
        except Exception:
            return None

    def fetchall(self):
        try:
            return self._cur.fetchall()
        except Exception:
            return []

    def __iter__(self):
        return iter(self._cur)

    def __getitem__(self, key):
        return self._cur[key]


class _PgConn:
    """Conexión de psycopg2 con la misma interfaz que sqlite3.Connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(_pg_sql(sql), params or ())
        wrapper = _PgCursor(cur)
        # Si el INSERT tiene RETURNING, capturamos el id generado
        if sql.strip().upper().startswith('INSERT') and 'RETURNING' in sql.upper():
            row = cur.fetchone()
            if row:
                wrapper.lastrowid = row[0]
        return wrapper

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ──────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────

def get_db():
    """Devuelve la conexión activa para el request actual (Flask g)."""
    if 'db' not in g:
        if BACKEND == 'postgres':
            conn = psycopg2.connect(DATABASE_URL)
            g.db = _PgConn(conn)
        else:
            conn = _sqlite3.connect(DB_PATH)
            conn.row_factory = _sqlite3.Row
            conn.execute('PRAGMA foreign_keys = ON')
            g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


# ──────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────

_SCHEMA_SQLITE = '''
    CREATE TABLE IF NOT EXISTS clientes (
        id_cliente          INTEGER PRIMARY KEY,
        razon_social        TEXT NOT NULL,
        tecnico_responsable TEXT,
        cuit                TEXT,
        condicion_iva       TEXT,
        grupo               TEXT,
        rubro               TEXT,
        direccion           TEXT,
        localidad           TEXT,
        provincia           TEXT
    );
    CREATE TABLE IF NOT EXISTS productos (
        id_producto      INTEGER PRIMARY KEY,
        nombre_comercial TEXT NOT NULL,
        categoria        TEXT,
        empresa          TEXT,
        formulacion      TEXT,
        principio_activo TEXT,
        unidad_medida    TEXT,
        familia          TEXT,
        precio_unit_usd  REAL
    );
    CREATE TABLE IF NOT EXISTS ensayos (
        id_ensayo          INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha              TEXT,
        id_cliente         INTEGER,
        objetivo           TEXT,
        tipo_agua          TEXT,
        ph                 REAL,
        conductividad      REAL,
        dureza             REAL,
        volumen_simulado   REAL,
        temperatura        REAL,
        tiempo_observacion REAL,
        resultado_final    TEXT,
        recomendacion      TEXT,
        espuma             TEXT,
        precipitado        TEXT,
        separacion_fases   TEXT,
        redispersion       TEXT,
        obs_microscopio    TEXT,
        FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente)
    );
    CREATE TABLE IF NOT EXISTS detalle_mezcla (
        id_detalle  INTEGER PRIMARY KEY AUTOINCREMENT,
        id_ensayo   INTEGER,
        orden_carga INTEGER,
        id_producto INTEGER,
        dosis       REAL,
        unidad      TEXT DEFAULT 'L',
        observacion TEXT,
        FOREIGN KEY (id_ensayo)   REFERENCES ensayos(id_ensayo),
        FOREIGN KEY (id_producto) REFERENCES productos(id_producto)
    );
    CREATE TABLE IF NOT EXISTS fotos_ensayo (
        id_foto        INTEGER PRIMARY KEY AUTOINCREMENT,
        id_ensayo      INTEGER,
        nombre_archivo TEXT,
        descripcion    TEXT,
        fecha_carga    TEXT,
        FOREIGN KEY (id_ensayo) REFERENCES ensayos(id_ensayo)
    );
'''

_SCHEMA_PG = [
    '''CREATE TABLE IF NOT EXISTS clientes (
        id_cliente          INTEGER PRIMARY KEY,
        razon_social        TEXT NOT NULL,
        tecnico_responsable TEXT,
        cuit                TEXT,
        condicion_iva       TEXT,
        grupo               TEXT,
        rubro               TEXT,
        direccion           TEXT,
        localidad           TEXT,
        provincia           TEXT
    )''',
    '''CREATE TABLE IF NOT EXISTS productos (
        id_producto      INTEGER PRIMARY KEY,
        nombre_comercial TEXT NOT NULL,
        categoria        TEXT,
        empresa          TEXT,
        formulacion      TEXT,
        principio_activo TEXT,
        unidad_medida    TEXT,
        familia          TEXT,
        precio_unit_usd  REAL
    )''',
    '''CREATE TABLE IF NOT EXISTS ensayos (
        id_ensayo          SERIAL PRIMARY KEY,
        fecha              TEXT,
        id_cliente         INTEGER,
        objetivo           TEXT,
        tipo_agua          TEXT,
        ph                 REAL,
        conductividad      REAL,
        dureza             REAL,
        volumen_simulado   REAL,
        temperatura        REAL,
        tiempo_observacion REAL,
        resultado_final    TEXT,
        recomendacion      TEXT,
        espuma             TEXT,
        precipitado        TEXT,
        separacion_fases   TEXT,
        redispersion       TEXT,
        obs_microscopio    TEXT,
        FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente)
    )''',
    '''CREATE TABLE IF NOT EXISTS detalle_mezcla (
        id_detalle  SERIAL PRIMARY KEY,
        id_ensayo   INTEGER,
        orden_carga INTEGER,
        id_producto INTEGER,
        dosis       REAL,
        unidad      TEXT DEFAULT 'L',
        observacion TEXT,
        FOREIGN KEY (id_ensayo)   REFERENCES ensayos(id_ensayo),
        FOREIGN KEY (id_producto) REFERENCES productos(id_producto)
    )''',
    '''CREATE TABLE IF NOT EXISTS fotos_ensayo (
        id_foto        SERIAL PRIMARY KEY,
        id_ensayo      INTEGER,
        nombre_archivo TEXT,
        descripcion    TEXT,
        fecha_carga    TEXT,
        FOREIGN KEY (id_ensayo) REFERENCES ensayos(id_ensayo)
    )''',
]


# ──────────────────────────────────────────────────────────
# Inicialización y migración desde Excel
# ──────────────────────────────────────────────────────────

def init_db():
    if BACKEND == 'postgres':
        _init_postgres()
    else:
        _init_sqlite()


def _init_sqlite():
    conn = _sqlite3.connect(DB_PATH)
    conn.row_factory = _sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(_SCHEMA_SQLITE)
    conn.commit()
    count = conn.execute('SELECT COUNT(*) FROM clientes').fetchone()[0]
    if count == 0 and os.path.exists(EXCEL_PATH):
        _import_from_excel(conn, 'sqlite')
    conn.close()


def _init_postgres():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    for stmt in _SCHEMA_PG:
        cur.execute(stmt)
    conn.commit()
    cur.execute('SELECT COUNT(*) FROM clientes')
    count = cur.fetchone()[0]
    cur.close()
    if count == 0 and os.path.exists(EXCEL_PATH):
        _import_from_excel(conn, 'postgres')
        # Actualizar secuencias SERIAL para que no choquen con los IDs importados
        cur2 = conn.cursor()
        for tbl, col in [('ensayos', 'id_ensayo'), ('detalle_mezcla', 'id_detalle'), ('fotos_ensayo', 'id_foto')]:
            cur2.execute(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {tbl}), 0) + 1, false)"
            )
        conn.commit()
        cur2.close()
    conn.close()


def _exec(conn, sql, params=(), backend=None):
    """Ejecuta SQL en una conexión raw (fuera del contexto de Flask g)."""
    bk = backend or BACKEND
    if bk == 'postgres':
        cur = conn.cursor()
        cur.execute(_pg_sql(sql), params or ())
        return cur
    else:
        return conn.execute(sql, params or ())


def _import_from_excel(conn, backend):
    try:
        import pandas as pd
        xl = pd.read_excel(EXCEL_PATH, sheet_name=None)

        def safe(row, key):
            v = row.get(key)
            return str(v) if v is not None and str(v) != 'nan' else None

        def safe_int(row, key):
            v = row.get(key)
            try:
                return int(v) if v is not None and str(v) != 'nan' else None
            except Exception:
                return None

        def safe_float(row, key):
            v = row.get(key)
            try:
                return float(v) if v is not None and str(v) != 'nan' else None
            except Exception:
                return None

        conflict = 'ON CONFLICT DO NOTHING'

        if 'CLIENTES' in xl:
            for _, r in xl['CLIENTES'].iterrows():
                _exec(conn,
                    f'INSERT INTO clientes VALUES (?,?,?,?,?,?,?,?,?,?) {conflict}',
                    (safe_int(r, 'ID_Cliente'),
                     safe(r, 'Razón Social') or safe(r, 'Razon Social') or '',
                     safe(r, 'Tecnico Responsable'), safe(r, 'C.U.I.T.'),
                     safe(r, 'Condición IVA') or safe(r, 'Condicion IVA'),
                     safe(r, 'Grupo'), safe(r, 'Rubro'),
                     safe(r, 'Dirección') or safe(r, 'Direccion'),
                     safe(r, 'Localidad'), safe(r, 'Provincia')),
                    backend)

        if 'PRODUCTOS' in xl:
            for _, r in xl['PRODUCTOS'].iterrows():
                precio = None
                raw = safe(r, 'P. Unit. USD')
                if raw:
                    try:
                        precio = float(raw.replace('$', '').replace(',', '.').strip())
                    except Exception:
                        pass
                _exec(conn,
                    f'INSERT INTO productos VALUES (?,?,?,?,?,?,?,?,?) {conflict}',
                    (safe_int(r, 'ID_Producto'), safe(r, 'Nombre Comercial') or '',
                     safe(r, 'Categoria'), safe(r, 'Empresa'),
                     safe(r, 'Formulacion'), safe(r, 'Principio activo'),
                     safe(r, 'Un. Medida'), safe(r, 'Familia'), precio),
                    backend)

        if 'ENSAYOS' in xl:
            for _, r in xl['ENSAYOS'].iterrows():
                fecha = None
                if r.get('FECHA') is not None and str(r.get('FECHA')) != 'nan':
                    try:
                        fecha = pd.to_datetime(r['FECHA']).strftime('%Y-%m-%d')
                    except Exception:
                        fecha = str(r['FECHA'])
                _exec(conn,
                    f'INSERT INTO ensayos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) {conflict}',
                    (safe_int(r, 'ID_ENSAYO'), fecha, safe_int(r, 'ID_CLIENTE'),
                     safe(r, 'OBJETIVO'), safe(r, 'TIPO_AGUA'),
                     safe_float(r, 'PH'), safe_float(r, 'CONDUCTIVIDAD'),
                     safe_float(r, 'DUREZA'), safe_float(r, 'VOLUMEN_SIMULADO'),
                     safe_float(r, 'TEMPERATURA'), safe_float(r, 'TIEMPO_OBSERVACION'),
                     safe(r, 'RESULTADO_FINAL'), safe(r, 'RECOMENDACION'),
                     safe(r, 'ESPUMA'), safe(r, 'PRECIPITADO'),
                     safe(r, 'SEPARACION_FASES'), safe(r, 'REDISPERSION'),
                     safe(r, 'OBS_MICROSCOPIO')),
                    backend)

        if 'DETALLE_MEZCLA' in xl:
            for _, r in xl['DETALLE_MEZCLA'].iterrows():
                _exec(conn,
                    f'INSERT INTO detalle_mezcla VALUES (?,?,?,?,?,?,?) {conflict}',
                    (safe_int(r, 'ID_DETALLE'), safe_int(r, 'ID_ENSAYO'),
                     safe_int(r, 'ORDEN_CARGA'), safe_int(r, 'ID_PRODUCTO'),
                     safe_float(r, 'DOSIS U/Ha'),
                     safe(r, 'UNIDAD') or 'L', safe(r, 'OBSERVACION')),
                    backend)

        conn.commit()
        print('OK: Datos importados desde Excel')
    except Exception as e:
        print(f'Error importando Excel: {e}')
        conn.rollback()
