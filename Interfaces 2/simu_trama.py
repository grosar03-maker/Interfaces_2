# ==============================================================================
# PROYECTO #2 - UNIDAD II: INTERFACES GRÁFICAS DE USUARIO (INFO1128)
# Archivo: simu_trama.py
# Propósito: Simular la transmisión continua de datos de un sensor ambiental
#            PMS7003ST enviando tramas CSV por el puerto serie COM2.
# ==============================================================================

import serial as rs       # Librería PySerial para la gestión del puerto serie COM
import time as ti         # Módulo para temporizar los intervalos de muestreo (delay)
import random as RA       # Generador de números pseudoaleatorios para simular lecturas

# Parámetros físicos de comunicación serie acordados en el diseño
PUERTO_SERIAL = 'COM2'
VELOCIDAD_BAUDIOS = 9600  # Configuración estándar 9600-8N1


def Make_Data(nId):
    """
    Construye sintéticamente una trama CSV de exactamente 12 campos:
    Posición [0]: Identificador de la Unidad Medio Ambiental (UMA 1 a 5).
    Posiciones [1..3]: Concentraciones de Material Particulado en microgramos/m3.
    Posiciones [4..9]: Conteo de partículas por canales de diámetro óptico (Histograma).
    Posiciones [10..11]: Variables meteorológicas (Temperatura y Humedad Relativa).
    """
    nEMA = nId  # [0] ID de la estación emisora (1 a 5)

    # 1. Concentraciones de masa particulada (ug/m3)
    nMP01 = RA.randint(5, 100)      # [1] PM 1.0 (partículas ultrafinas respirables)
    nMP25 = RA.randint(5, 100)      # [2] PM 2.5 (fracción fina respirable)
    nMP10 = RA.randint(5, 100)      # [3] PM 10 (fracción torácica)

    # 2. Histograma: conteo acumulado de partículas según tamaño de canal óptico (um)
    nH103 = RA.randint(10, 10000)   # [4] Canal de 0.3 micrómetros
    nH105 = RA.randint(10, 10000)   # [5] Canal de 0.5 micrómetros
    nH101 = RA.randint(10, 10000)   # [6] Canal de 1.0 micrómetros
    nH125 = RA.randint(10, 10000)   # [7] Canal de 2.5 micrómetros
    nH150 = RA.randint(10, 10000)   # [8] Canal de 5.0 micrómetros
    nH110 = RA.randint(10, 10000)   # [9] Canal de 10 micrómetros

    # 3. Variables climáticas de contexto
    nTE = RA.randint(5, 30)         # [10] Temperatura ambiental (°C)
    nHR = RA.randint(20, 70)        # [11] Humedad Relativa del aire (%)

    # Estructuración de la trama en formato CSV delimitado por comas
    sLine = (
        f"{nEMA},{nMP01},{nMP25},{nMP10},"
        f"{nH103},{nH105},{nH101},{nH125},{nH150},{nH110},"
        f"{nTE},{nHR}"
    )
    return sLine


if __name__ == '__main__':
    print(f"[*] Iniciando transmisión serie en {PUERTO_SERIAL} @ {VELOCIDAD_BAUDIOS} bps...")

    try:
        # Apertura del puerto serie virtual creado previamente en VSPE (Connector COM2)
        # timeout=1 define que las operaciones de lectura/escritura no bloqueen indefinidamente
        MyCnx = rs.Serial(port=PUERTO_SERIAL, baudrate=VELOCIDAD_BAUDIOS, timeout=1)
        nId = 1  # Inicializamos la rotación en la primera estación

        while True:
            # Generación de la trama para la estación actual
            sAux = Make_Data(nId)
            print(f"[TX] {sAux}")

            # IMPORTANTE: En Python 3 el método .write() exige un flujo binario (bytes),
            # por lo que codificamos la cadena de texto bajo UTF-8.
            MyCnx.write(sAux.encode('utf-8'))

            # Pausa de 300 ms entre envíos para permitir que el buffer serie en Lazarus
            # no sufra colisiones o solapamiento de tramas por saturación.
            ti.sleep(0.3)

            # Algoritmo de multiplexación temporal: alterna cíclicamente entre UMA 1 y 5
            nId += 1
            if nId > 5:
                nId = 1

    except rs.SerialException as e:
        print(f"[!] Error crítico de hardware/puerto: {e}")
        print("    Asegúrate de que VSPE tenga el dispositivo 'Connector' activo en COM2.")
    except KeyboardInterrupt:
        print("\n[*] Detención controlada por el usuario (Ctrl + C).")
    finally:
        # Garantiza el cierre del descriptor del puerto para no dejarlo bloqueado en el SO
        if 'MyCnx' in locals() and MyCnx.is_open:
            MyCnx.close()
            print("[*] Puerto serie COM2 liberado con éxito.")