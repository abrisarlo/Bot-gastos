# Bot de gastos para Telegram + Google Sheets

Registrás gastos, ingresos y ahorros en texto libre por Telegram. Todo se
guarda en una planilla de Google Sheets (nunca en el servidor, así que no
se pierde nada). Corre gratis en Render, sin necesidad de tener tu
computadora prendida.

## Qué sabe hacer

- `gaste 500 en comida` → gasto en Efectivo (cuenta por default)
- `gaste 500 en comida con galicia` → gasto debitado de esa cuenta
- `cobre 300000 en mercado pago` → ingreso acreditado en esa cuenta
- `ahorre 2000` (cualquier frase con "ahorr...") → ahorro manual
- Cuentas que reconoce: **efectivo, galicia, mercado pago, wallbit, cuenta dni**
- `/resumen` → total gastado, ingreso, ahorro (sobrante + manual + total), por categoría
- `/saldos` → cuánto tenés en cada cuenta + lo invertido
- `/invertir 5000` → suma plata a tu saldo invertido
- `/rendimiento 8000` → anota lo que rindió lo invertido este mes (opcional)
- `/pendiente Alquiler - 50000 - 10/09/2026` → algo que tenés que pagar
- `/pendientes` → lista lo que falta pagar
- `/pagado 3` → marca el pendiente #3 como pagado
- `/planilla` → te manda el link a la planilla

## Cómo funciona la planilla

- Una **hoja por mes** (ej. `2026-09`) con la tabla de gastos, ingresos,
  ahorro manual, resumen con gráfico de torta por categoría (colores
  fuertes, la fila se pinta sola según la categoría) y gráfico de
  ingreso/gastado/ahorro.
- Hoja fija **"Cuentas"**: saldo de Efectivo, Galicia, Mercado Pago,
  Wallbit, Cuenta DNI e Invertido — se actualiza solo con cada gasto/ingreso.
- Hoja fija **"Rendimientos"**: lo que anotaste con `/rendimiento`, mes a mes.
- Hoja fija **"Pendientes"**: lo que falta pagar.
- El **día que arranca un mes nuevo**, el bot cierra la hoja anterior
  (deja los números fijos), te avisa el resumen por Telegram, y abre la
  hoja nueva. Vos borrás las hojas viejas a mano cuando ya no las necesites.

---

## Paso a paso para activarlo

### 1. Crear el bot en Telegram
1. Hablale a **@BotFather** en Telegram.
2. Mandale `/newbot` y seguí los pasos (nombre y username, ej. `mis_gastos_bot`).
3. Te va a dar un **token** tipo `123456789:ABCdefGHI...`. Guardalo, lo vas a necesitar dos veces más abajo.

### 2. Conseguir tu chat_id
1. Hablale a tu bot recién creado (cualquier mensaje, ej: "hola"). Vas a ver que no responde nada todavía, es normal.
2. Abrí en el navegador (reemplazando TU_TOKEN por el token real):
   `https://api.telegram.org/botTU_TOKEN/getUpdates`
3. Buscá `"chat":{"id":...}` en el texto que aparece — ese número es tu `TELEGRAM_CHAT_ID`.

### 3. Crear la planilla de Google Sheets
1. Andá a https://sheets.new — se crea una planilla nueva. Ponele nombre, ej. "Gastos". No hace falta que armes nada adentro, el bot arma las hojas solo la primera vez que le escribas.
2. Mirá la URL de esa planilla: `https://docs.google.com/spreadsheets/d/ESTO_ES_EL_ID/edit`. Copiá esa parte — es tu `SPREADSHEET_ID`.

### 4. Crear una cuenta de servicio de Google (para que el bot pueda escribir)
1. Andá a https://console.cloud.google.com/ y creá un proyecto nuevo (o usá uno existente).
2. Buscá **"Google Sheets API"** → **Habilitar**. Buscá también **"Google Drive API"** → **Habilitar**.
3. Andá a **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**. Ponele un nombre (ej. "gastobot") y creála, no hace falta asignarle roles.
4. Entrá a la cuenta de servicio creada → pestaña **Claves** → **Agregar clave → Crear clave nueva → JSON**. Se descarga un archivo `.json`.
5. Abrí ese archivo con el bloc de notas: dentro vas a ver un campo `"client_email"`, algo como `gastobot@tu-proyecto.iam.gserviceaccount.com`.
6. **Compartí tu planilla de Google Sheets con ese email** (botón "Compartir" arriba a la derecha en Sheets, pegá el email, dale permiso de **Editor**). **Sin este paso el bot no puede escribir nada.**
7. Guardá todo el contenido del archivo `.json` — lo vas a pegar como una variable de entorno en el paso 6.

### 5. Subir el código a GitHub
1. Creá un repositorio nuevo en GitHub (puede ser privado).
2. Subí estos archivos: `main.py`, `sheets_manager.py`, `parser.py`, `requirements.txt`, `render.yaml`.

### 6. Desplegar en Render (gratis)
1. Creá una cuenta en https://render.com (podés entrar con GitHub).
2. **New +** → **Blueprint** → elegí tu repo (lee `render.yaml` solo y configura todo), o a mano: **New +** → **Web Service**, conectá el repo, Build Command: `pip install -r requirements.txt`, Start Command: `gunicorn main:app`, plan **Free**.
3. Variables de entorno a cargar:
   - `TELEGRAM_BOT_TOKEN` = el token del paso 1
   - `TELEGRAM_CHAT_ID` = tu chat id del paso 2
   - `SPREADSHEET_ID` = el ID de la planilla del paso 3
   - `GOOGLE_CREDENTIALS_JSON` = todo el contenido del archivo `.json` del paso 4, pegado tal cual (con las `{ }` y todo)
   - `CRON_SECRET` = cualquier palabra secreta inventada por vos (ej. `laclave123`)
4. Dale **Create Web Service** / **Apply** y esperá a que el deploy termine (mirá los logs, tarda uno o dos minutos). Vas a tener una URL tipo `https://gastobot.onrender.com`.

### 7. Conectar el bot con esa URL (una sola vez)
En tu computadora, con Python instalado:
```
pip install requests
python set_webhook.py TU_TOKEN https://gastobot.onrender.com
```
Debería responder `{"ok": true, ...}`. A partir de acá, andá a Telegram y escribile a tu bot: **`/help`**. Si te responde, ¡ya está funcionando! Probá `gaste 500 en comida con galicia` y después `/resumen`.

### 8. Recordatorios y cierre de mes automático
1. En Render: **New +** → **Cron Job**.
2. Command: `curl "https://gastobot.onrender.com/cron/diario?token=TU_CRON_SECRET"` (usá la misma palabra que pusiste en `CRON_SECRET`).
3. Schedule: `0 12 * * *` (todos los días a las 12:00 UTC = 9:00 en Argentina). Este job revisa pendientes por vencer Y detecta cuándo hay que cerrar el mes y abrir el nuevo.
4. Plan **Free**.

---

## Cosas a tener en cuenta

- El plan gratis de Render "duerme" el servicio a los 15 minutos sin uso. El primer mensaje después de un rato tarda unos segundos en responder — es normal, no está roto.
- Los datos viven en Google Sheets, no en Render, así que un redeploy nunca te hace perder nada.
- El bot solo responde a tu `TELEGRAM_CHAT_ID`, nadie más puede usarlo aunque encuentre tu bot.
- Si en algún momento el bot deja de responder, revisá en Render → tu servicio → **Logs**, ahí suele decir por qué (token mal copiado, planilla no compartida con la cuenta de servicio, etc.).
