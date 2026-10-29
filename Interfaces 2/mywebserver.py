# ==============================================================================
# PROYECTO #2 - UNIDAD II: INTERFACES GRÁFICAS DE USUARIO (INFO1128)
# Archivo: mywebserver.py
# Propósito: Servidor Flask con persistencia en SQLite, API REST en formato
#            JSON y renderizado de gráficos estadísticos con Matplotlib.
# ==============================================================================

import io                           # Manipulación de streams en memoria RAM (para imágenes)
import sqlite3                      # Motor de base de datos relacional estándar y embebido
from datetime import datetime       # Generador de marcas de tiempo precisas (DateTime)
from flask import Flask, jsonify, request as REQ, Response, render_template_string

# CONFIGURACIÓN CRÍTICA DE MATPLOTLIB:
# Se fuerza el backend 'Agg' (sin interfaz de escritorio) para operar en modo "Headless".
# Esto previene bloqueos por concurrencia entre hilos cuando el navegador pide gráficos vía HTTP.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

App = Flask(__name__)
DB_NAME = 'datalogger_ambiental.db'


def init_db():
    """
    Inicializa la estructura relacional creando el esquema de la tabla 'mediciones'
    si el archivo SQLite no existe aún en disco. Cumple el requerimiento formal
    de registrar cada muestra con su respectivo DateTime.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mediciones (
                id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
                uma_id INTEGER NOT NULL,
                mp01 INTEGER NOT NULL,
                mp02 INTEGER NOT NULL,
                mp03 INTEGER NOT NULL,
                hi01 INTEGER NOT NULL,
                hi02 INTEGER NOT NULL,
                hi03 INTEGER NOT NULL,
                hi04 INTEGER NOT NULL,
                hi05 INTEGER NOT NULL,
                hi06 INTEGER NOT NULL,
                te INTEGER NOT NULL,
                hr INTEGER NOT NULL,
                fecha_hora TEXT NOT NULL -- Formato ISO: YYYY-MM-DD HH:MM:SS
            )
        ''')
        conn.commit()


# ==============================================================================
# 1. RECEPTOR DE DATOS EN TIEMPO REAL (MÉTODO POST)
# ==============================================================================
@App.route('/data', methods=['POST'])
def get_data():
    """
    Endpoint consumido por el cliente TFPHttpClient de Lazarus Pascal.
    Parsea el cuerpo JSON, registra el timestamp y ejecuta la inserción en SQLite.
    """
    dD = REQ.json
    if not dD:
        return jsonify({"error": "Payload JSON nulo o inválido"}), 400

    # Captura del DateTime del sistema operativo con formato estandarizado
    fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Registro en la consola estándar del servidor para trazabilidad inmediata
    print(
        f"[{fecha_actual}] Rx UMA: {dD['id']} | "
        f"MP: ({dD['mp01']}, {dD['mp02']}, {dD['mp03']}) | "
        f"Temp: {dD['te']}°C, HR: {dD['hr']}%"
    )

    # Inserción parametrizada (con tuplas) para blindar la base contra inyecciones SQL
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO mediciones (
                uma_id, mp01, mp02, mp03,
                hi01, hi02, hi03, hi04, hi05, hi06,
                te, hr, fecha_hora
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            dD['id'], dD['mp01'], dD['mp02'], dD['mp03'],
            dD['hi01'], dD['hi02'], dD['hi03'], dD['hi04'], dD['hi05'], dD['hi06'],
            dD['te'], dD['hr'], fecha_actual
        ))
        conn.commit()

    return 'Todo OK', 200


# ==============================================================================
# 2. ENDPOINTS DE LA API REST (RESPUESTAS NATIVAS EN JSON)
# ==============================================================================
@App.route('/api/registros', methods=['GET'])
def consultar_todos_json():
    """
    API REST: Retorna el histórico de mediciones en formato JSON.
    Permite opcionalmente paginar (?limit=50) o segmentar por estación (?uma=1).
    Accesible desde cualquier navegador o cliente REST en: http://127.0.0.1:7070/api/registros
    """
    uma_filtro = REQ.args.get('uma', type=int)
    limite = REQ.args.get('limit', default=100, type=int)

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row  # Devuelve tuplas accesibles como diccionarios asociativos
        cursor = conn.cursor()

        if uma_filtro:
            cursor.execute(
                'SELECT * FROM mediciones WHERE uma_id = ? ORDER BY id_registro DESC LIMIT ?',
                (uma_filtro, limite)
            )
        else:
            cursor.execute(
                'SELECT * FROM mediciones ORDER BY id_registro DESC LIMIT ?',
                (limite,)
            )

        filas = [dict(fila) for fila in cursor.fetchall()]

    return jsonify({
        "total_registros": len(filas),
        "filtro_aplicado": f"UMA {uma_filtro}" if uma_filtro else "Todas",
        "datos": filas
    })


@App.route('/api/registros/<int:uma_id>', methods=['GET'])
def consultar_por_uma_json(uma_id):
    """
    API REST jerárquica: Devuelve las últimas 100 lecturas exclusivas de la UMA solicitada.
    Ejemplo: http://127.0.0.1:7070/api/registros/4
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM mediciones WHERE uma_id = ? ORDER BY id_registro DESC LIMIT 100',
            (uma_id,)
        )
        filas = [dict(fila) for fila in cursor.fetchall()]

    return jsonify({
        "estacion_uma": uma_id,
        "conteo_muestras": len(filas),
        "historico": filas
    })


# ==============================================================================
# 3. GENERADOR DE GRÁFICAS BINARIAS CON MATPLOTLIB (SALIDA PNG)
# ==============================================================================
@App.route('/grafica.png', methods=['GET'])
def generar_imagen_matplotlib():
    """
    Construye al vuelo un gráfico doble (Series Temporales + Histograma del último registro)
    leyendo directamente desde la base de datos SQLite y sirviendo el binario de imagen
    directamente desde un buffer en RAM, evitando escritura de archivos temporales en disco.
    """
    uma_filtro = REQ.args.get('uma', type=int)

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if uma_filtro:
            cursor.execute(
                'SELECT * FROM mediciones WHERE uma_id = ? ORDER BY id_registro DESC LIMIT 15',
                (uma_filtro,)
            )
        else:
            cursor.execute('SELECT * FROM mediciones ORDER BY id_registro DESC LIMIT 15')
        # Invertimos el orden para graficar cronológicamente de izquierda a derecha (más viejo a más nuevo)
        filas = list(reversed(cursor.fetchall()))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.patch.set_facecolor('#f8f9fa')

    if not filas:
        ax1.text(0.5, 0.5, 'Sin registros almacenados en SQLite aún.\nActive el checkbox "Envía" en Lazarus.',
                 ha='center', va='center', fontsize=12, color='crimson')
        ax2.axis('off')
    else:
        # A. Subgráfico Izquierdo: Series Temporales de Concentración
        horas = [f['fecha_hora'].split(' ')[1] for f in filas]
        v_mp01 = [f['mp01'] for f in filas]
        v_mp25 = [f['mp02'] for f in filas]
        v_mp10 = [f['mp03'] for f in filas]

        ax1.plot(horas, v_mp01, marker='o', color='red', label='PM 1.0 (ug/m3)', linewidth=2)
        ax1.plot(horas, v_mp25, marker='s', color='blue', label='PM 2.5 (ug/m3)', linewidth=2)
        ax1.plot(horas, v_mp10, marker='^', color='green', label='PM 10 (ug/m3)', linewidth=2)
        titulo = f"UMA {uma_filtro}" if uma_filtro else "General (Todas las UMAs)"
        ax1.set_title(f'Tendencia de Contaminación - {titulo}', fontweight='bold')
        ax1.set_xlabel('Timestamp (Hora:Minuto:Segundo)')
        ax1.set_ylabel('Concentración (ug/m3)')
        ax1.grid(True, linestyle='--', alpha=0.6)
        ax1.legend(loc='upper right')
        ax1.tick_params(axis='x', rotation=45)

        # B. Subgráfico Derecho: Histograma de Conteo Óptico de la última muestra registrada
        ultima = filas[-1]
        canales = ['0.3um', '0.5um', '1.0um', '2.5um', '5.0um', '10um']
        conteos = [ultima['hi01'], ultima['hi02'], ultima['hi03'],
                   ultima['hi04'], ultima['hi05'], ultima['hi06']]
        paleta = ['#ff0000', '#008000', '#0000ff', '#ffff00', '#00ff00', '#add8e6']

        barras = ax2.bar(canales, conteos, color=paleta, edgecolor='black')
        ax2.set_title(
            f"Distribución Última Muestra (UMA {ultima['uma_id']} | T:{ultima['te']}°C | HR:{ultima['hr']}%)",
            fontweight='bold'
        )
        ax2.set_xlabel('Canal Óptico')
        ax2.set_ylabel('Conteo Absoluto de Partículas')
        ax2.grid(axis='y', linestyle='--', alpha=0.6)

        # Anotación numérica sobre cada barra del histograma
        for b in barras:
            val = b.get_height()
            ax2.annotate(f'{val}',
                         xy=(b.get_x() + b.get_width() / 2, val),
                         xytext=(0, 3), textcoords="offset points",
                         ha='center', va='bottom', fontsize=9, fontweight='bold')

    plt.tight_layout()

    # Volcado de la imagen generada en un buffer de memoria volátil
    buffer_memoria = io.BytesIO()
    plt.savefig(buffer_memoria, format='png', dpi=100)
    plt.close(fig) # Cierre explícito de la figura para evitar fuga de descriptores gráficos
    buffer_memoria.seek(0)

    return Response(buffer_memoria.getvalue(), mimetype='image/png')


# ==============================================================================
# 4. TABLERO DE CONTROL WEB INTEGRADO (HTML)
# ==============================================================================
@App.route('/', methods=['GET'])
@App.route('/grafica', methods=['GET'])
def panel_navegador():
    """
    Ruta raíz que renderiza una interfaz web responsiva donde el usuario puede
    visualizar la gráfica generada por Matplotlib y acceder a las consultas REST.
    Se actualiza automáticamente cada 5 segundos mediante un meta tag HTML.
    """
    uma_activa = REQ.args.get('uma', default='')
    html = '''
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="5">
        <title>Panel Ambiental Flask - INFO1128</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
                   background: #edf2f7; margin: 0; padding: 25px; text-align: center; color: #2d3748; }
            .card { background: #ffffff; max-width: 1080px; margin: 0 auto; padding: 25px;
                    border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
            h2 { margin-top: 0; color: #1a202c; }
            .btn-group { margin: 15px 0; }
            .btn { display: inline-block; padding: 7px 14px; margin: 3px; font-size: 13px; font-weight: 600;
                   color: #ffffff; background: #3182ce; border-radius: 6px; text-decoration: none; }
            .btn:hover { background: #2b6cb0; }
            .btn-alt { background: #4a5568; }
            .btn-alt:hover { background: #2d3748; }
            .img-box { margin-top: 20px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
            img { width: 100%; height: auto; display: block; }
            .info-footer { font-size: 12px; color: #a0aec0; margin-top: 15px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Sistema de Monitoreo Ambiental - Servidor de Datos (INFO1128)</h2>

            <div class="btn-group">
                <span style="font-size: 14px; font-weight: bold; margin-right: 10px;">Consultas API REST (JSON):</span>
                <a class="btn" href="/api/registros" target="_blank">Todos los Datos</a>
                <a class="btn" href="/api/registros/1" target="_blank">UMA 1</a>
                <a class="btn" href="/api/registros/2" target="_blank">UMA 2</a>
                <a class="btn" href="/api/registros/3" target="_blank">UMA 3</a>
                <a class="btn" href="/api/registros/4" target="_blank">UMA 4</a>
                <a class="btn" href="/api/registros/5" target="_blank">UMA 5</a>
            </div>

            <div class="btn-group">
                <span style="font-size: 14px; font-weight: bold; margin-right: 10px;">Filtrar Matplotlib:</span>
                <a class="btn btn-alt" href="/grafica">Todas</a>
                <a class="btn btn-alt" href="/grafica?uma=1">UMA 1</a>
                <a class="btn btn-alt" href="/grafica?uma=2">UMA 2</a>
                <a class="btn btn-alt" href="/grafica?uma=3">UMA 3</a>
                <a class="btn btn-alt" href="/grafica?uma=4">UMA 4</a>
                <a class="btn btn-alt" href="/grafica?uma=5">UMA 5</a>
            </div>

            <div class="img-box">
                <img src="/grafica.png?uma={{ uma }}" alt="Render de Matplotlib">
            </div>

            <div class="info-footer">
                Actualización automática activa cada 5 segundos | Base de datos SQLite: datalogger_ambiental.db
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html, uma=uma_activa)


if __name__ == '__main__':
    # Creación preventiva de la base de datos y su tabla al levantar el servidor
    init_db()
    print("[*] Base de datos relacional SQLite inicializada con éxito.")
    print("[*] Servidor Flask activo en escucha en: http://127.0.0.1:7070")
    print("    - Interfaz gráfica web: http://127.0.0.1:7070/grafica")
    print("    - Endpoint REST JSON:   http://127.0.0.1:7070/api/registros")

    # Inicia la aplicación en todas las interfaces (0.0.0.0) en el puerto asignado 7070
    App.run(debug=True, host='0.0.0.0', port=7070)