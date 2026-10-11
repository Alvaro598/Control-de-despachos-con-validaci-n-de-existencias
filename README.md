# Control de despachos · Distribuidora La Quinta

Aplicación local para registrar solicitudes de despacho, enviar cada solicitud al webhook de Make y consultar el historial de movimientos aprobados. La interfaz usa HTML, CSS y JavaScript nativos; el servidor usa Python estándar y SQLite.

## Inicio local

1. Instala Python 3.10 o posterior.
2. En PowerShell, desde esta carpeta, ejecuta `Copy-Item .env.example .env`.
3. Abre `.env` con un editor de texto y reemplaza el valor de `MAKE_WEBHOOK_URL` por tu URL del webhook de Make. No compartas ese archivo.
4. En la misma ventana, ejecuta `python server.py` (en Windows también puedes usar `py server.py`).
5. Mientras esa ventana siga abierta, visita `http://127.0.0.1:8000` en el navegador.

Para detener el servidor, vuelve a esa ventana y pulsa `Ctrl+C`. Al iniciarlo otra vez, los movimientos locales se conservan en `.data/la_quinta.sqlite3`.

El servidor crea `.data/la_quinta.sqlite3` al iniciar y conserva allí el historial local; no se pierde al cerrar el navegador o reiniciar el servidor. Para mantenerlo ejecutándose, deja abierta la terminal donde lanzaste `python server.py`. El desplegable muestra código y nombre, y se alimenta de `products.json`: agrega allí un objeto por producto con los campos `codigo` y `nombre`, siguiendo el ejemplo incluido. El catálogo es una copia local; cuando cambie la hoja de inventario, actualiza también este archivo.

La URL del webhook funciona como credencial: no la publiques en GitHub, capturas ni mensajes. `.env` está excluido por `.gitignore`. El servidor escucha solo en `127.0.0.1`; esta versión no tiene inicio de sesión ni está preparada para exposición pública.

## Flujo

La interfaz envía `solicitante`, `correo`, `codigo_producto`, `cantidad`, `destino` y `motivo` a `POST /api/dispatch`. El servidor valida el contrato y llama a Make. Make consulta la hoja `Inventario`, calcula `saldo_posterior = existencias - cantidad` y responde JSON. La pantalla muestra el resultado y solo registra en la tabla local `movimientos` las salidas `APROBADO` y `APROBADO CON ALERTA`; `RUTA DE RESPALDO` queda en `incidencias`. `GET /api/history` alimenta el historial.

Respuestas esperadas de Make:

```json
{
  "resultado": "APROBADO CON ALERTA",
  "mensaje": "Existencias por debajo del mínimo; reposición urgente.",
  "saldo_anterior": 8,
  "saldo_posterior": 0
}
```

`resultado` puede ser `APROBADO`, `APROBADO CON ALERTA`, `RECHAZADO` o `RUTA DE RESPALDO`. El escenario debe terminar todas las rutas con un módulo `Webhook response`; de lo contrario, la interfaz no obtiene un resultado.

## Reglas del inventario

- `saldo_posterior >= minimo`: `APROBADO`; actualiza la existencia en la misma fila y agrega el movimiento.
- `0 <= saldo_posterior < minimo`: `APROBADO CON ALERTA`; actualiza la existencia, registra el movimiento y notifica a Compras.
- `saldo_posterior < 0`: `RECHAZADO`; no cambia el inventario ni registra una salida.
- Código inexistente: ruta de respaldo; no cambia el inventario y registra/avisa la incidencia.
- C5, saldo exactamente cero: se aprueba con alerta crítica y reposición urgente cuando el mínimo es positivo.

Configura Make para procesar solicitudes secuencialmente: dos despachos concurrentes no deben leer el mismo saldo antes de que se complete la primera actualización.

## Historial

SQLite crea `.data/la_quinta.sqlite3`. Cada movimiento incluye fecha y hora UTC, solicitante, correo, producto, cantidad, destino, motivo, resultado, saldos anterior/posterior y observación. La interfaz muestra hasta 500 movimientos recientes. Las solicitudes rechazadas no se insertan en `movimientos`, según el criterio de evaluación; se pueden auditar en el historial de ejecuciones de Make.

## Validación de extremo a extremo

Antes de activar el escenario, preparar C1 (saldo final igual o mayor al mínimo), C2 (saldo final positivo por debajo del mínimo), C3 (saldo negativo), C4 (código inexistente) y C5 (saldo final cero). Verificar para cada uno la respuesta de pantalla, el historial de Make y el cambio/no cambio exacto de la fila de inventario. No ejecutar los casos de escritura contra inventario operativo sin una ventana de prueba o productos de prueba aislados.
