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


def agregar_gasto(monto: float, categoria: str, descripcion: str, cuenta: str, fecha=None):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    if fecha is not None:
        fecha_str = fecha.strftime("%d/%m/%Y") + " " + datetime.now().strftime("%H:%M")
    else:
        fecha_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha_str, monto, categoria, descripcion, cuenta], value_input_option="USER_ENTERED", table_range="A1")
    _recalcular_resumen(ws)
    modificar_saldo(cuenta, -monto)


def _todos_los_gastos(ws):
    """Todas las filas de la tabla de gastos (A:E), con su numero de fila real.
    La fecha se lee por separado con formato normal (texto legible); el resto,
    sin formato, para que los montos no vengan como '$1,234.00' en texto."""
    fechas = ws.get("A2:A1000")
    resto = ws.get("B2:E1000", value_render_option="UNFORMATTED_VALUE")
    n = max(len(fechas), len(resto))
    resultado = []
    for i in range(n):
        fecha = fechas[i][0] if i < len(fechas) and fechas[i] else ""
        datos_resto = (resto[i] if i < len(resto) else []) + ["", "", "", ""]
        monto, categoria, descripcion, cuenta = datos_resto[:4]
        if fecha == "" and monto == "" and categoria == "" and descripcion == "":
            continue
        resultado.append({
            "fila": i + 2, "fecha": fecha, "monto": _a_float(monto),
            "categoria": categoria, "descripcion": descripcion,
            "cuenta": cuenta or "Efectivo",
        })
    return resultado


def listar_gastos_mes(n=10):
    """Los ultimos n gastos del mes actual, en orden cronologico, con su numero de fila."""
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    return _todos_los_gastos(ws)[-n:]


def _gasto_por_fila(ws, fila):
    fecha_val = ws.get(f"A{fila}:A{fila}")
    resto_val = ws.get(f"B{fila}:E{fila}", value_render_option="UNFORMATTED_VALUE")
    fecha = fecha_val[0][0] if fecha_val and fecha_val[0] else ""
    if fecha == "":
        return None
    datos = (resto_val[0] if resto_val else []) + ["", "", "", ""]
    monto, categoria, descripcion, cuenta = datos[:4]
    return {
        "fila": fila, "fecha": fecha, "monto": _a_float(monto),
        "categoria": categoria, "descripcion": descripcion,
        "cuenta": cuenta or "Efectivo",
    }


def _gasto_por_categoria(ws, categoria_buscada):
    """El gasto MAS RECIENTE que matchea esa categoria (sin importar mayus/minus).
    Devuelve (info_o_none, cuantos_matchearon_en_total)."""
    categoria_low = categoria_buscada.strip().lower()
    coincidencias = [g for g in _todos_los_gastos(ws) if g["categoria"].strip().lower() == categoria_low]
    if not coincidencias:
        return None, 0
    return coincidencias[-1], len(coincidencias)


def _resolver_gasto(ws, selector_tipo, selector_valor):
    """selector_tipo: 'ultimo' | 'id' | 'categoria'. Devuelve (info_o_none, total_matches)."""
    if selector_tipo == "id":
        info = _gasto_por_fila(ws, selector_valor)
        return info, (1 if info else 0)
    if selector_tipo == "categoria":
        return _gasto_por_categoria(ws, selector_valor)
    # 'ultimo'
    todos = _todos_los_gastos(ws)
    info = todos[-1] if todos else None
    return info, (1 if info else 0)


def ultimo_gasto_mes_actual():
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    info, _ = _resolver_gasto(ws, "ultimo", None)
    return info


def corregir_gasto(selector_tipo="ultimo", selector_valor=None,
                    nuevo_monto=None, nueva_categoria=None, nueva_cuenta=None):
    """Corrige un gasto (monto, categoria y/o cuenta) elegido por:
    - 'ultimo': el ultimo cargado
    - 'id': el de esa fila exacta (selector_valor = numero de fila)
    - 'categoria': el mas reciente con esa categoria (selector_valor = texto)
    Devuelve ((info_vieja, info_nueva), total_matches). info_vieja es None si no se
    encontro nada para corregir."""
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    info, total = _resolver_gasto(ws, selector_tipo, selector_valor)
    if info is None:
        return None, total

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
    return (info, nueva_info), total


def deshacer_gasto(selector_tipo="ultimo", selector_valor=None):
    """Borra un gasto elegido por el mismo criterio que corregir_gasto, y revierte
    el debito de su cuenta. Devuelve (info_o_none, total_matches)."""
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    info, total = _resolver_gasto(ws, selector_tipo, selector_valor)
    if info is None:
        return None, total
    fila = info["fila"]
    modificar_saldo(info["cuenta"], info["monto"])
    ws.batch_clear([f"A{fila}:E{fila}"])
    _recalcular_resumen(ws)
    return info, total


def agregar_ahorro_manual(monto: float):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha, monto], value_input_option="USER_ENTERED", table_range="J1")
    _recalcular_resumen(ws)


def agregar_ingreso(monto: float, cuenta: str, descripcion: str, fecha=None):
    sh = _spreadsheet()
    ws = obtener_o_crear_hoja_mes(sh)
    if fecha is not None:
        fecha_str = fecha.strftime("%d/%m/%Y") + " " + datetime.now().strftime("%H:%M")
    else:
        fecha_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha_str, monto, cuenta, descripcion], value_input_option="USER_ENTERED", table_range="M1")
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
               if ws.title not in (PENDIENTES, CUENTAS, RENDIMIENTOS, TRANSFERENCIAS, POR_COBRAR)]

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
                  value_input_option="USER_ENTERED", table_range="A1")
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


# ---------- Por cobrar (plata que te deben a vos) ----------

POR_COBRAR = "PorCobrar"
COLS_POR_COBRAR = ["ID", "Descripcion", "Monto", "Quien", "Cobrado"]


def _hoja_por_cobrar(sh):
    for ws in sh.worksheets():
        if ws.title == POR_COBRAR:
            return ws
    ws = sh.add_worksheet(title=POR_COBRAR, rows=200, cols=6)
    ws.update(values=[COLS_POR_COBRAR], range_name="A1:E1")
    ws.format("A1:E1", {"textFormat": {"bold": True}})
    return ws


def agregar_por_cobrar(descripcion: str, monto: float, quien: str = ""):
    sh = _spreadsheet()
    ws = _hoja_por_cobrar(sh)
    filas = ws.get("A2:A1000")
    ids = [int(f[0]) for f in filas if f and str(f[0]).isdigit()]
    nuevo_id = (max(ids) + 1) if ids else 1
    ws.append_row([nuevo_id, descripcion, monto, quien, "No"],
                  value_input_option="USER_ENTERED", table_range="A1")
    return nuevo_id


def listar_por_cobrar(solo_no_cobrados=True):
    sh = _spreadsheet()
    ws = _hoja_por_cobrar(sh)
    filas = ws.get("A2:E1000", value_render_option="UNFORMATTED_VALUE")
    resultado = []
    for f in filas:
        if not f or f[0] == "":
            continue
        f = f + [""] * (5 - len(f))
        id_, desc, monto, quien, cobrado = f
        if solo_no_cobrados and cobrado == "Si":
            continue
        resultado.append({
            "id": int(id_), "descripcion": desc, "monto": _a_float(monto),
            "quien": quien, "cobrado": cobrado,
        })
    return resultado


def marcar_cobrado(id_cobrar: int) -> bool:
    sh = _spreadsheet()
    ws = _hoja_por_cobrar(sh)
    celdas = ws.findall(str(id_cobrar), in_column=1)
    for c in celdas:
        if str(ws.cell(c.row, 1).value) == str(id_cobrar):
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
        ws.append_row([cuenta, delta], value_input_option="USER_ENTERED", table_range="A1")
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


# ---------- Transferencias entre cuentas propias ----------

TRANSFERENCIAS = "Transferencias"


def _hoja_transferencias(sh):
    for ws in sh.worksheets():
        if ws.title == TRANSFERENCIAS:
            return ws
    ws = sh.add_worksheet(title=TRANSFERENCIAS, rows=500, cols=4)
    ws.update(values=[["Fecha", "Monto", "Origen", "Destino"]], range_name="A1:D1")
    ws.format("A1:D1", {"textFormat": {"bold": True}})
    return ws


def transferir(monto: float, origen: str, destino: str):
    """Mueve plata entre dos cuentas propias: no cuenta como gasto ni como
    ingreso, solo ajusta los saldos y queda anotado en la hoja Transferencias."""
    sh = _spreadsheet()
    ws = _hoja_transferencias(sh)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    ws.append_row([fecha, monto, origen, destino], value_input_option="USER_ENTERED", table_range="A1")
    modificar_saldo(origen, -monto)
    modificar_saldo(destino, monto)


def detalle_cuenta(cuenta: str):
    """Desglose transparente de como se arma el saldo de UNA cuenta: cuanto
    entra y sale por gastos, ingresos y transferencias, hoja por hoja, para
    poder auditar a mano un numero que no cierra."""
    sh = _spreadsheet()
    nombres_mes = [ws.title for ws in sh.worksheets()
                   if ws.title not in (PENDIENTES, CUENTAS, RENDIMIENTOS, TRANSFERENCIAS, POR_COBRAR)]

    total_gastos = 0.0
    cant_gastos = 0
    total_ingresos = 0.0
    cant_ingresos = 0

    for nombre in nombres_mes:
        ws = sh.worksheet(nombre)
        for g in _todos_los_gastos(ws):
            if (g["cuenta"] or "Efectivo") == cuenta:
                total_gastos += g["monto"]
                cant_gastos += 1

        ingresos = ws.get("M2:P1000", value_render_option="UNFORMATTED_VALUE")
        for fila in ingresos:
            if not fila or fila[0] == "":
                continue
            fila = fila + ["", "", "", ""]
            monto, c = fila[1], (fila[2] or "Efectivo")
            if monto == "" or c != cuenta:
                continue
            total_ingresos += _a_float(monto)
            cant_ingresos += 1

    total_transf_entrante = 0.0
    total_transf_saliente = 0.0
    cant_transf = 0
    filas_t = _hoja_transferencias(sh).get("A2:D1000", value_render_option="UNFORMATTED_VALUE")
    for fila in filas_t:
        if not fila or fila[0] == "":
            continue
        fila = fila + ["", "", "", ""]
        monto, origen, destino = fila[1], fila[2], fila[3]
        if monto == "":
            continue
        monto = _a_float(monto)
        if origen == cuenta:
            total_transf_saliente += monto
            cant_transf += 1
        if destino == cuenta:
            total_transf_entrante += monto
            cant_transf += 1

    saldo_calculado = total_ingresos - total_gastos + total_transf_entrante - total_transf_saliente
    saldo_actual = dict(obtener_saldos()).get(cuenta, 0.0)

    return {
        "cuenta": cuenta,
        "total_gastos": total_gastos, "cant_gastos": cant_gastos,
        "total_ingresos": total_ingresos, "cant_ingresos": cant_ingresos,
        "total_transf_entrante": total_transf_entrante,
        "total_transf_saliente": total_transf_saliente,
        "cant_transf": cant_transf,
        "saldo_calculado": saldo_calculado,
        "saldo_actual_en_cuentas": saldo_actual,
    }


def recalcular_saldos_desde_historial():
    """Reconstruye los saldos de Efectivo/Galicia/Mercado Pago/Wallbit/Cuenta DNI
    sumando y restando TODO lo que ya esta anotado (gastos, ingresos y
    transferencias en todas las hojas de mes). No toca 'Invertido' porque
    eso no tiene un historial propio, es un saldo que se carga directo con
    /invertir. Devuelve (saldos_anteriores, saldos_nuevos)."""
    sh = _spreadsheet()
    cuentas_a_recalcular = ["Efectivo", "Galicia", "Mercado Pago", "Wallbit", "Cuenta DNI"]
    saldos = {c: 0.0 for c in cuentas_a_recalcular}

    nombres_mes = [ws.title for ws in sh.worksheets()
                   if ws.title not in (PENDIENTES, CUENTAS, RENDIMIENTOS, TRANSFERENCIAS, POR_COBRAR)]

    for nombre in nombres_mes:
        ws = sh.worksheet(nombre)

        for g in _todos_los_gastos(ws):
            cuenta = g["cuenta"] or "Efectivo"
            saldos[cuenta] = saldos.get(cuenta, 0.0) - g["monto"]

        ingresos = ws.get("M2:P1000", value_render_option="UNFORMATTED_VALUE")
        for fila in ingresos:
            if not fila or fila[0] == "":
                continue
            fila = fila + ["", "", "", ""]
            monto, cuenta = fila[1], (fila[2] or "Efectivo")
            if monto == "":
                continue
            saldos[cuenta] = saldos.get(cuenta, 0.0) + _a_float(monto)

    filas_t = _hoja_transferencias(sh).get("A2:D1000", value_render_option="UNFORMATTED_VALUE")
    for fila in filas_t:
        if not fila or fila[0] == "":
            continue
        fila = fila + ["", "", "", ""]
        monto, origen, destino = fila[1], fila[2], fila[3]
        if monto == "" or not origen or not destino:
            continue
        monto = _a_float(monto)
        saldos[origen] = saldos.get(origen, 0.0) - monto
        saldos[destino] = saldos.get(destino, 0.0) + monto

    anteriores = dict(obtener_saldos())
    ws_cuentas = _hoja_cuentas(sh)
    for cuenta, nuevo_saldo in saldos.items():
        fila = _fila_cuenta(ws_cuentas, cuenta)
        if fila is None:
            ws_cuentas.append_row([cuenta, nuevo_saldo], value_input_option="USER_ENTERED", table_range="A1")
        else:
            ws_cuentas.update(values=[[nuevo_saldo]], range_name=f"B{fila}")

    return anteriores, saldos


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
    ws.append_row([_nombre_mes_actual(), monto], value_input_option="USER_ENTERED", table_range="A1")


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
