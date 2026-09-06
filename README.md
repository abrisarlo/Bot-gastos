# Bot de gastos para Telegram + Google Sheets

Registrás gastos, ingresos, ahorros y transferencias en texto libre por
Telegram. Todo se guarda en una planilla de Google Sheets. Corre gratis en
Render, sin necesidad de tener tu computadora prendida.

## Qué sabe hacer

### Registrar en texto libre
- `gaste 500 en comida` → gasto en Efectivo (cuenta por default)
- `gaste 500 en comida con galicia` → gasto debitado de esa cuenta
- `gaste 500 de uber en galicia` → el bot reconoce "galicia" como cuenta aunque no digas "con"
- `gaste 500 en comida ayer` (o "anteayer", o "el 3/9") → fecha distinta a hoy
- `cobre 300000 en mercado pago` → ingreso acreditado en esa cuenta
- `transferi 5000 de efectivo a galicia` → mueve plata entre tus cuentas (no es gasto ni ingreso)
- `ahorre 2000` (cualquier frase con "ahorr...") → ahorro manual
- Si mencionás "pendiente" en una frase libre, el bot te pregunta si es algo
  que vos tenés que pagar o plata que te tienen que dar, en vez de anotarlo mal.

Cuentas que reconoce: **efectivo, galicia, mercado pago, wallbit, cuenta dni**.
Categorías: cualquier palabra sirve; hay ~30 sinónimos agrupados automáticamente
(uber/uber/subte/nafta → Transporte, super/coto/carrefour → Supermercado,
netflix/spotify → Streaming, farmacia/dentista → Salud, etc.).

**Si no encuentra ninguna categoría**, el bot igual anota el gasto (con
categoría "Sin categoria", para no perder el dato) y te pregunta cuál es —
respondé con una sola palabra y se la corrige.

### Comandos
- `/resumen` — total gastado, ingreso, ahorro y categorías del mes
- `/saldos` — cuánto tenés en cada cuenta + lo invertido
- `/recalcularsaldos` — reconstruye los saldos de las cuentas sumando TODO lo
  ya anotado (gastos, ingresos, transferencias). Útil si algo quedó desalineado.
- `/invertir Monto` — suma plata a tu saldo invertido
- `/rendimiento Monto` — anota lo que rindió lo invertido este mes (opcional)
- `/transferir Monto Origen Destino` — respaldo si la frase libre no se entiende
- `/pendiente Descripcion - Monto - DD/MM/AAAA` — algo que VOS tenés que pagar
- `/pendientes` — lista lo que falta pagar
- `/pagado ID` — marca un pendiente como pagado
- `/cobrar Descripcion - Monto - Quien` — plata que te tienen que dar a vos
- `/porcobrar` — lista lo que te deben
- `/cobrado ID` — marca algo como ya cobrado
- `/gastos [N]` — últimos N gastos (10 por default) con su número de fila
- `/corregir cuenta|monto|categoria Valor` — corrige el **último** gasto
- `/corregir FILA cuenta|monto|categoria Valor` — corrige una fila puntual (ver `/gastos`)
- `/corregir categoria:comida cuenta|monto|categoria Valor` — corrige el gasto
  más reciente con esa categoría
- `/deshacer` (también acepta FILA o `categoria:X`) — borra un gasto y revierte el saldo
- `/planilla` — te manda el link a la planilla

## Cómo funciona la planilla

- Una **hoja por mes** (ej. `2026-09`) con gastos, ingresos, ahorro manual,
  resumen con gráfico de torta por categoría (colores fuertes, la fila se
  pinta sola según la categoría) y gráfico de ingreso/gastado/ahorro.
- Hoja fija **"Cuentas"**: saldo real de Efectivo, Galicia, Mercado Pago,
  Wallbit, Cuenta DNI e Invertido — se actualiza solo con cada gasto/ingreso/transferencia.
- Hoja fija **"Transferencias"**: historial de movimientos entre tus cuentas.
- Hoja fija **"Rendimientos"**: lo que anotaste con `/rendimiento`, mes a mes.
- Hoja fija **"Pendientes"**: lo que falta pagar.
- Hoja fija **"PorCobrar"**: lo que te deben.
- El **día que arranca un mes nuevo**, el bot cierra la hoja anterior, te
  avisa el resumen por Telegram, y abre la hoja nueva.

---

## Paso a paso para activarlo

### 1. Crear el bot en Telegram
1. Hablale a **@BotFather** en Telegram.
2. Mandale `/newbot` y seguí los pasos (nombre y username).
3. Te va a dar un **token**. Guardalo.

### 2. Conseguir tu chat_id
1. Hablale a tu bot (cualquier mensaje, ej: "hola").
2. Abrí en el navegador: `https://api.telegram.org/botTU_TOKEN/getUpdates`
3. Buscá `"chat":{"id":...}` — ese número es tu `TELEGRAM_CHAT_ID`.

### 3. Crear la planilla de Google Sheets
1. Andá a https://sheets.new — creá una planilla, no hace falta armar nada adentro.
2. Copiá el ID de la URL (entre `/d/` y `/edit`) — es tu `SPREADSHEET_ID`.

### 4. Crear una cuenta de servicio de Google
1. https://console.cloud.google.com/ → creá un proyecto.
2. Habilitá **Google Sheets API** y **Google Drive API** (buscándolas en la
   barra de arriba y tocando "Habilitar"). No hace falta tarjeta ni facturación.
3. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**.
4. Entrá a la cuenta creada → **Claves → Agregar clave → Crear clave nueva → JSON**.
5. Abrí el JSON, copiá el `client_email`, y **compartí tu planilla con ese
   email** (botón Compartir → Editor). Sin este paso el bot no puede escribir.
6. Guardá todo el contenido del JSON para el paso 6.

### 5. Subir el código a GitHub
Subí: `main.py`, `sheets_manager.py`, `parser.py`, `requirements.txt`, `render.yaml`.

### 6. Desplegar en Render (gratis)
1. https://render.com → **New +** → **Blueprint** → elegí tu repo.
2. Variables de entorno:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SPREADSHEET_ID`
   - `GOOGLE_CREDENTIALS_JSON` (todo el contenido del `.json`, pegado tal cual)
   - `CRON_SECRET` (una palabra secreta inventada por vos)
3. Esperá el deploy. Vas a tener una URL tipo `https://gastobot-xxxx.onrender.com`.

### 7. Conectar el webhook (una sola vez)
```
pip install requests
python set_webhook.py TU_TOKEN https://gastobot-xxxx.onrender.com
```
Debería responder `{"ok": true, ...}`.

### 8. Recordatorios y cierre de mes (gratis, sin usar Cron Jobs de Render)
Los Cron Jobs de Render tienen un costo mínimo de $1/mes — mejor usar un
servicio externo gratis:
1. Creá una cuenta gratis en https://cron-job.org (sin tarjeta).
2. Creá un cronjob con URL: `https://gastobot-xxxx.onrender.com/cron/diario?token=TU_CRON_SECRET`
3. Horario: todos los días a las **12:00 UTC** (9:00 AM Argentina).

---

## Actualizar el código después de un cambio

1. Entrá a tu repo en GitHub.
2. **Add file → Upload files**, arrastrá los archivos que cambiaron (podés
   arrastrar varios juntos en un solo commit).
3. **Commit changes**. Render detecta el cambio solo y redeploya.
4. Esperá a que diga "Live" antes de probar en Telegram.

## Cosas a tener en cuenta

- El plan gratis de Render "duerme" el servicio a los 15 minutos sin uso.
  El primer mensaje después de un rato tarda unos segundos — es normal.
- Los datos viven en Google Sheets, no en Render, así que un redeploy nunca
  te hace perder nada.
- El bot solo responde a tu `TELEGRAM_CHAT_ID`.
- Si el bot no responde, revisá **Render → tu servicio → Logs** — ahí suele
  decir el error exacto (token mal copiado, planilla no compartida, etc.).
- Si `/corregir` o `/deshacer` no encuentran el gasto que buscás, puede que
  ya no sea "el último" — usá `/gastos` para ver el número de fila y apuntá
  con `/corregir FILA ...`.
