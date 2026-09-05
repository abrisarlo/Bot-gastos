"""
Maneja la planilla de Google Sheets:
- Una hoja por mes con gastos, ingresos y ahorro.
- Hoja fija "Pendientes" para pagos por hacer.
- Hoja fija "Cuentas" con el saldo de efectivo/bancos/billeteras e invertido.
- Hoja fija "Rendimientos" con lo que rindio lo invertido, mes a mes.
"""
import re
import os
import json
from datetime import datetime, date

import gspread

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

PENDIENTES = "Pendientes"
CUENTAS = "Cuentas"
RENDIMIENTOS = "Rendimientos"

COLS_PENDIENTES = ["ID", "Descripcion", "Monto", "FechaVencimiento", "Pagado"]
CUENTAS_INICIALES = ["Efectivo", "Galicia", "Mercado Pago", "Wallbit", "Cuenta DNI", "Invertido"]

# ---- columnas dentro de cada hoja mensual ----
# Gastos:            A Fecha | B Monto | C Categoria | D Descripcion | E Cuenta
# Resumen categoria:  G Categoria | H Total   (alimenta el grafico de torta)
# Ahorro manual:      J Fecha | K Monto
# Ingresos:           M Fecha | N Monto | O Cuenta | P Descripcion
# Panel resumen:      R label | S valor   (filas 2-6), tabla auxiliar (filas 9-11), leyenda (filas 13+)

FILA_TOTAL_GASTADO = 2
FILA_INGRESO = 3
FILA_AHORRO_SOBRANTE = 4
FILA_AHORRO_MANUAL = 5
FILA_AHORRO_TOTAL = 6


def _cliente():
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    return gspread.service_account_from_dict(creds_dict)


def _spreadsheet():
    return _cliente().open_by_key(SPREADSHEET_ID)


def _nombre_mes_actual():
    return date.today().strftime("%Y-%m")


def _a_float(valor):
    """Convierte a float de forma tolerante: saca '$', espacios, etc.
    Sirve como red de seguridad por si alguna celda vuelve formateada
    (ej. '$1,234.56') en vez de como numero puro."""
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = re.sub(r"[^0-9,.\-]", "", str(valor))
    texto = texto.replace(",", ".")
    if texto in ("", "-", "."):
        return 0.0
    try:
        return float(texto)
    except ValueError:
        return 0.0


# ---------- Hojas mensuales ----------

def obtener_o_crear_hoja_mes(sh, nombre=None):
    nombre = nombre or _nombre_mes_actual()
    for ws in sh.worksheets():
        if ws.title == nombre:
            return ws
    return _crear_hoja_mes(sh, nombre)


def _crear_hoja_mes(sh, nombre):
    ws = sh.add_worksheet(title=nombre, rows=500, cols=20)

    ws.update(values=[["Fecha", "Monto", "Categoria", "Descripcion", "Cuenta"]], range_name="A1:E1")
    ws.update(values=[["Categoria", "Total"]], range_name="G1:H1")
    ws.update(values=[["Fecha ahorro", "Monto ahorro"]], range_name="J1:K1")
    ws.update(values=[["Fecha", "Monto", "Cuenta", "Descripcion"]], range_name="M1:P1")
    ws.update(values=[
        ["Total gastado", 0],
        ["Ingreso mensual", 0],
        ["Ahorro (sobrante)", 0],
        ["Ahorro manual", 0],
        ["Ahorro total", 0],
    ], range_name="R2:S6")
    ws.update(values=[["Concepto", "Valor"]], range_name="R9:S9")

    ws.format("A1:E1", {"textFormat": {"bold": True}})
    ws.format("G1:H1", {"textFormat": {"bold": True}})
    ws.format("J1:K1", {"textFormat": {"bold": True}})
    ws.format("M1:P1", {"textFormat": {"bold": True}})
    ws.format("R2:R6", {"textFormat": {"bold": True}})

    _agregar_grafico_torta(sh, ws)
    return ws


def _agregar_grafico_torta(sh, ws):
    request = {
        "requests": [{
            "addChart": {
                "chart": {
                    "spec": {
                        "title": f"Gastos por categoria - {ws.title}",
                        "pieChart": {
                            "legendPosition": "RIGHT_LEGEND",
                            "domain": {
                                "sourceRange": {"sources": [{
                                    "sheetId": ws.id,
                                    "startRowIndex": 0, "endRowIndex": 30,
                                    "startColumnIndex": 6, "endColumnIndex": 7,
                                }]}
                            },
                            "series": {
                                "sourceRange": {"sources": [{
                                    "sheetId": ws.id,
                                    "startRowIndex": 0, "endRowIndex": 30,
                                    "startColumnIndex": 7, "endColumnIndex": 8,
                                }]}
                            },
                        }
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": ws.id, "rowIndex": 12, "columnIndex": 0}
                        }
                    },
                }
            }
        }]
    }
    sh.batch_update(request)


def _leer_gastos(ws):
    """Devuelve lista de (monto, categoria) de todas las filas cargadas."""
    valores = ws.get("B2:C1000", value_render_option="UNFORMATTED_VALUE")
    resultado = []
    for fila in valores:
        if len(fila) < 2 or fila[0] == "":
            continue
        try:
            resultado.append((_a_float(fila[0]), fila[1]))
        except ValueError:
            continue
    return resultado


def _sumar_columna(ws, rango):
    valores = ws.get(rango, value_render_option="UNFORMATTED_VALUE")
    total = 0.0
    for fila in valores:
        if not fila or fila[0] == "":
            continue
        try:
            total += _a_float(fila[0])
        except ValueError:
            continue
    return total


def _recalcular_resumen(ws):
    gastos = _leer_gastos(ws)
    total_gastado = sum(m for m, _ in gastos)

    por_categoria = {}
    for monto, cat in gastos:
        por_categoria[cat] = por_categoria.get(cat, 0.0) + monto
    filas_categoria = sorted(por_categoria.items(), key=lambda x: -x[1])

    ingreso = _sumar_columna(ws, "N2:N1000")
    ahorro_manual = _sumar_columna(ws, "K2:K1000")
    ahorro_sobrante = ingreso - total_gastado
    ahorro_total = ahorro_sobrante + ahorro_manual

    ws.batch_clear(["G2:H100"])
    if filas_categoria:
        ws.update(values=[[c, t] for c, t in filas_categoria], range_name=f"G2:H{1 + len(filas_categoria)}")

    ws.update(values=[[total_gastado]], range_name="S2")
    ws.update(values=[
        [ingreso],
        [ahorro_sobrante],
        [ahorro_manual],
        [ahorro_total],
    ], range_name="S3:S6")
    ws.update(values=[
        ["Ingreso", ingreso],
        ["Gastado", total_gastado],
        ["Ahorro total", ahorro_total],
    ], range_name="R10:S12")

    return total_gastado, ingreso, ahorro_sobrante, ahorro_manual, ahorro_total, filas_categoria


def agregar_gasto(monto: float, categoria: str, descripcion: str, cuenta: str):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha, monto, categoria, descripcion, cuenta], value_input_option="USER_ENTERED")
    _recalcular_resumen(ws)
    modificar_saldo(cuenta, -monto)


def _ultima_fila_gasto(ws):
    """Datos de la ultima fila cargada en la tabla de gastos (A:E), o None si esta vacia."""
    filas = ws.get("A2:E1000", value_render_option="UNFORMATTED_VALUE")
    if not filas:
        return None
    numero_fila = len(filas) + 1  # +1 porque la fila 1 es el header
    fila = filas[-1] + [""] * (5 - len(filas[-1]))
    fecha, monto, categoria, descripcion, cuenta = fila
    return {
        "fila": numero_fila, "fecha": fecha, "monto": _a_float(monto),
        "categoria": categoria, "descripcion": descripcion,
        "cuenta": cuenta or "Efectivo",
    }


def ultimo_gasto_mes_actual():
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    return _ultima_fila_gasto(ws)


def corregir_ultimo_gasto(nuevo_monto=None, nueva_categoria=None, nueva_cuenta=None):
    """Corrige el ultimo gasto cargado (monto, categoria y/o cuenta) y ajusta
    los saldos de las cuentas para que reflejen el cambio. Devuelve
    (info_vieja, info_nueva) o None si no habia ningun gasto cargado."""
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    info = _ultima_fila_gasto(ws)
    if info is None:
        return None

    fila = info["fila"]
    monto_final = nuevo_monto if nuevo_monto is not None else info["monto"]
    categoria_final = nueva_categoria if nueva_categoria is not None else info["categoria"]
    cuenta_final = nueva_cuenta if nueva_cuenta is not None else info["cuenta"]

    modificar_saldo(info["cuenta"], info["monto"])      # deshace el debito viejo
    modificar_saldo(cuenta_final, -monto_final)          # aplica el debito nuevo

    ws.update(values=[[monto_final, categoria_final]], range_name=f"B{fila}:C{fila}")
    ws.update(values=[[cuenta_final]], range_name=f"E{fila}")
    _recalcular_resumen(ws)

    nueva_info = dict(info, monto=monto_final, categoria=categoria_final, cuenta=cuenta_final)
    return info, nueva_info


def deshacer_ultimo_gasto():
    """Borra el ultimo gasto cargado y revierte el debito de su cuenta.
    Devuelve la info del gasto borrado, o None si no habia nada."""
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    info = _ultima_fila_gasto(ws)
    if info is None:
        return None
    fila = info["fila"]
    modificar_saldo(info["cuenta"], info["monto"])
    ws.batch_clear([f"A{fila}:E{fila}"])
    _recalcular_resumen(ws)
    return info


def agregar_ahorro_manual(monto: float):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha, monto], value_input_option="USER_ENTERED", table_range="J1")
    _recalcular_resumen(ws)


def agregar_ingreso(monto: float, cuenta: str, descripcion: str):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha, monto, cuenta, descripcion], value_input_option="USER_ENTERED", table_range="M1")
    _recalcular_resumen(ws)
    modificar_saldo(cuenta, monto)


def resumen_mes_actual():
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    return _recalcular_resumen(ws)


# ---------- Cierre / apertura de mes ----------

def rollover_si_corresponde():
    sh = _spreadsheet()
    nombre_actual = _nombre_mes_actual()
    titulos = [ws.title for ws in sh.worksheets()
               if ws.title not in (PENDIENTES, CUENTAS, RENDIMIENTOS)]

    if nombre_actual in titulos:
        return None

    resumen_cerrado = None
    if titulos:
        ultimo = sorted(titulos)[-1]
        ws_anterior = sh.worksheet(ultimo)
        total_gastado, ingreso, ahorro_sobrante, ahorro_manual, ahorro_total, _ = _recalcular_resumen(ws_anterior)
        resumen_cerrado = {
            "mes": ultimo, "total_gastado": total_gastado, "ingreso": ingreso,
            "ahorro_sobrante": ahorro_sobrante, "ahorro_manual": ahorro_manual,
            "ahorro_total": ahorro_total,
        }

    obtener_o_crear_hoja_mes(sh, nombre_actual)
    return resumen_cerrado


# ---------- Pendientes ----------

def _hoja_pendientes(sh):
    for ws in sh.worksheets():
        if ws.title == PENDIENTES:
            return ws
    ws = sh.add_worksheet(title=PENDIENTES, rows=200, cols=6)
    ws.update(values=[COLS_PENDIENTES], range_name="A1:E1")
    ws.format("A1:E1", {"textFormat": {"bold": True}})
    return ws


def agregar_pendiente(descripcion: str, monto: float, fecha_vencimiento: date):
    sh = _spreadsheet()
    ws = _hoja_pendientes(sh)
    filas = ws.get("A2:A1000")
    ids = [int(f[0]) for f in filas if f and str(f[0]).isdigit()]
    nuevo_id = (max(ids) + 1) if ids else 1
    ws.append_row([nuevo_id, descripcion, monto, fecha_vencimiento.strftime("%d/%m/%Y"), "No"],
                  value_input_option="USER_ENTERED")
    return nuevo_id


def listar_pendientes(solo_no_pagados=True):
    sh = _spreadsheet()
    ws = _hoja_pendientes(sh)
    filas = ws.get("A2:E1000", value_render_option="UNFORMATTED_VALUE")
    resultado = []
    for f in filas:
        if not f or f[0] == "":
            continue
        f = f + [""] * (5 - len(f))
        id_, desc, monto, fecha_venc, pagado = f
        if solo_no_pagados and pagado == "Si":
            continue
        resultado.append({
            "id": int(id_), "descripcion": desc, "monto": _a_float(monto),
            "fecha_vencimiento": fecha_venc, "pagado": pagado,
        })
    return resultado


def marcar_pagado(id_pendiente: int) -> bool:
    sh = _spreadsheet()
    ws = _hoja_pendientes(sh)
    celdas = ws.findall(str(id_pendiente), in_column=1)
    for c in celdas:
        if str(ws.cell(c.row, 1).value) == str(id_pendiente):
            ws.update_cell(c.row, 5, "Si")
            return True
    return False


def pendientes_por_vencer(dias=3):
    hoy = date.today()
    resultado = []
    for p in listar_pendientes(solo_no_pagados=True):
        try:
            fecha_venc = datetime.strptime(p["fecha_vencimiento"], "%d/%m/%Y").date()
        except (ValueError, TypeError):
            continue
        delta = (fecha_venc - hoy).days
        if delta <= dias:
            p["dias_restantes"] = delta
            resultado.append(p)
    return resultado


# ---------- Cuentas (efectivo / bancos / billeteras / invertido) ----------

def _hoja_cuentas(sh):
    for ws in sh.worksheets():
        if ws.title == CUENTAS:
            return ws
    ws = sh.add_worksheet(title=CUENTAS, rows=20, cols=2)
    ws.update(values=[["Cuenta", "Saldo"]], range_name="A1:B1")
    ws.format("A1:B1", {"textFormat": {"bold": True}})
    ws.update(values=[[c, 0] for c in CUENTAS_INICIALES], range_name=f"A2:B{1 + len(CUENTAS_INICIALES)}")
    return ws


def _fila_cuenta(ws, cuenta):
    filas = ws.get("A2:A100")
    for i, f in enumerate(filas, start=2):
        if f and f[0] == cuenta:
            return i
    return None


def modificar_saldo(cuenta: str, delta: float):
    sh = _spreadsheet()
    ws = _hoja_cuentas(sh)
    fila = _fila_cuenta(ws, cuenta)
    if fila is None:
        ws.append_row([cuenta, delta], value_input_option="USER_ENTERED")
        return
    actual = ws.acell(f"B{fila}", value_render_option="UNFORMATTED_VALUE").value or 0
    nuevo = _a_float(actual) + delta
    ws.update(values=[[nuevo]], range_name=f"B{fila}")


def obtener_saldos():
    sh = _spreadsheet()
    ws = _hoja_cuentas(sh)
    filas = ws.get("A2:B100", value_render_option="UNFORMATTED_VALUE")
    resultado = []
    for f in filas:
        if not f or f[0] == "":
            continue
        saldo = _a_float(f[1]) if len(f) > 1 else 0.0
        resultado.append((f[0], saldo))
    return resultado


def invertir(monto: float):
    modificar_saldo("Invertido", monto)


# ---------- Rendimientos de lo invertido ----------

def _hoja_rendimientos(sh):
    for ws in sh.worksheets():
        if ws.title == RENDIMIENTOS:
            return ws
    ws = sh.add_worksheet(title=RENDIMIENTOS, rows=200, cols=2)
    ws.update(values=[["Mes", "Monto"]], range_name="A1:B1")
    ws.format("A1:B1", {"textFormat": {"bold": True}})
    return ws


def registrar_rendimiento(monto: float):
    sh = _spreadsheet()
    ws = _hoja_rendimientos(sh)
    ws.append_row([_nombre_mes_actual(), monto], value_input_option="USER_ENTERED")


def rendimiento_mes_actual():
    sh = _spreadsheet()
    ws = _hoja_rendimientos(sh)
    filas = ws.get("A2:B200", value_render_option="UNFORMATTED_VALUE")
    total = 0.0
    mes = _nombre_mes_actual()
    for f in filas:
        if f and f[0] == mes and len(f) > 1:
            try:
                total += _a_float(f[1])
            except ValueError:
                pass
    return total


def url_planilla():
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
